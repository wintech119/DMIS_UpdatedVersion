import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { EMPTY, Observable, of, throwError } from 'rxjs';
import { catchError, finalize, tap } from 'rxjs/operators';

import {
  AllocationCandidate,
  AllocationCommitPayload,
  AllocationItemGroup,
  AllocationOptionsResponse,
  AllocationSelectionPayload,
  ConsolidationLeg,
  ConsolidationLegDispatchPayload,
  ConsolidationLegDispatchResponse,
  ConsolidationLegReceivePayload,
  ConsolidationLegReceiveResponse,
  FulfillmentMode,
  OVERRIDE_REASON_OPTIONS,
  OverrideApprovalPayload,
  PackageDetailResponse,
  PackageDraftPayload,
  PackageLockConflict,
  PackageLockReleaseResponse,
  PartialReleaseApprovePayload,
  PartialReleaseApproveResponse,
  PartialReleaseRequestPayload,
  PartialReleaseRequestResponse,
  PickupReleasePayload,
  PickupReleaseResponse,
  StagingRecommendationResponse,
  WaybillResponse,
  AllocationMethod,
} from '../models/operations.model';
import { OperationsService } from './operations.service';

/**
 * Attempt to parse a DMIS Operations package-lock conflict out of an HttpErrorResponse.
 *
 * The backend returns HTTP 400 with `{errors: {lock, lock_owner_user_id, lock_owner_role_code,
 * lock_expires_at}}` when another actor holds the package lock. This helper lifts that shape
 * out so the UI can present it as a first-class workflow safeguard rather than a raw toast.
 * Returns null for any other kind of error.
 */
export function tryParsePackageLockConflict(
  error: HttpErrorResponse | unknown,
): PackageLockConflict | null {
  if (!(error instanceof HttpErrorResponse) || error.status !== 400) {
    return null;
  }
  const body = error.error as { errors?: Record<string, unknown> } | null | undefined;
  const errors = body?.errors;
  if (!errors || typeof errors !== 'object') {
    return null;
  }
  const lockMessage = (errors as Record<string, unknown>)['lock'];
  if (typeof lockMessage !== 'string' || !lockMessage.trim()) {
    return null;
  }
  return {
    lock: lockMessage,
    lock_owner_user_id: asNullablePackageLockString((errors as Record<string, unknown>)['lock_owner_user_id']),
    lock_owner_role_code: asNullablePackageLockString((errors as Record<string, unknown>)['lock_owner_role_code']),
    lock_expires_at: asNullablePackageLockString((errors as Record<string, unknown>)['lock_expires_at']),
  };
}

function asNullablePackageLockString(value: unknown): string | null {
  if (value == null) {
    return null;
  }
  const normalized = String(value).trim();
  return normalized ? normalized : null;
}

interface WorkspaceDraft {
  source_warehouse_id: string;
  to_inventory_id: string;
  transport_mode: string;
  comments_text: string;
  override_reason_code: string;
  override_note: string;
  fulfillment_mode: FulfillmentMode;
  staging_warehouse_id: string;
  staging_override_reason: string;
}

export interface StockAvailabilityIssue {
  kind: 'missing-warehouse' | 'no-candidates';
  scope: 'request' | 'item';
  detail?: string | null;
}

const MISSING_WAREHOUSE_ERROR =
  'source_warehouse_id is required when no needs-list compatibility bridge exists.';

const DEFAULT_DRAFT: WorkspaceDraft = {
  source_warehouse_id: '',
  to_inventory_id: '',
  transport_mode: '',
  comments_text: '',
  override_reason_code: '',
  override_note: '',
  fulfillment_mode: 'DIRECT',
  staging_warehouse_id: '',
  staging_override_reason: '',
};

@Injectable()
export class OperationsWorkspaceStateService {
  private readonly operationsService = inject(OperationsService);
  private latestWorkspaceGeneration = 0;
  private latestSourceWarehouseRequestId = 0;
  private latestItemWarehouseRequestIds: Record<number, number> = {};
  private latestItemPreviewRequestIds: Record<number, number> = {};
  private latestItemAddRequestIds: Record<number, number> = {};
  private latestLegsRequestId = 0;
  private latestRecommendationRequestId = 0;

  readonly reliefrqstId = signal(0);
  readonly reliefpkgId = signal(0);
  readonly packageDetail = signal<PackageDetailResponse | null>(null);
  readonly options = signal<AllocationOptionsResponse | null>(null);
  readonly waybill = signal<WaybillResponse | null>(null);

  readonly consolidationLegs = signal<ConsolidationLeg[]>([]);
  readonly legsLoading = signal(false);
  readonly legsError = signal<string | null>(null);
  readonly stagingRecommendation = signal<StagingRecommendationResponse | null>(null);
  readonly recommendationLoading = signal(false);
  readonly recommendationError = signal<string | null>(null);

  readonly loading = signal(false);
  readonly waybillLoading = signal(false);
  readonly submitting = signal(false);
  readonly unlocking = signal(false);

  readonly loadError = signal<string | null>(null);
  readonly optionsError = signal<string | null>(null);
  readonly waybillError = signal<string | null>(null);

  /**
   * Captured DMIS package-lock conflict when another actor holds the lock on the current
   * package. Set by any write path that hits the backend's lock guard; cleared by
   * {@link load} or by a successful {@link releasePackageLock}. When non-null the workspace
   * surfaces a first-class blocker card instead of a generic error toast.
   */
  readonly lockConflict = signal<PackageLockConflict | null>(null);

  readonly draft = signal<WorkspaceDraft>({ ...DEFAULT_DRAFT });
  readonly selectedRowsByItem = signal<Record<number, AllocationSelectionPayload[]>>({});

  /** Per-item warehouse overrides: item_id -> warehouse_id string. */
  readonly itemWarehouseOverrides = signal<Record<number, string>>({});

  /** Original per-item warehouse seed from the last full allocation load. */
  readonly seededWarehousesByItem = signal<Record<number, string>>({});

  /** Warehouses currently contributing to each item: item_id -> ordered list of warehouse ids. */
  readonly loadedWarehousesByItem = signal<Record<number, number[]>>({});

  /** True per-item while a draft-aware POST preview recompute is in flight. */
  readonly previewLoadingByItem = signal<Record<number, boolean>>({});

  /** True per-item while an additive warehouse load is in flight. */
  readonly addingWarehouseByItem = signal<Record<number, boolean>>({});

  /** True while a per-item warehouse switch is loading (does NOT clear existing data). */
  readonly switching = signal(false);

  readonly selectedLineCount = computed(() =>
    Object.values(this.selectedRowsByItem()).reduce((sum, rows) => sum + rows.length, 0),
  );

  readonly hasCommittedAllocation = computed(() => {
    const detail = this.packageDetail();
    if (!detail) {
      return false;
    }
    const lines = detail.allocation?.allocation_lines?.length ?? 0;
    if (lines === 0) {
      return false;
    }
    // Draft packages (new 'DRAFT' and legacy 'A') may carry allocation lines
    // from a prior Save Draft but are not yet committed. Only packages in a
    // non-draft status with allocation lines count as committed.
    const status = String(detail.package?.status_code ?? '').trim().toUpperCase();
    return status !== 'DRAFT' && status !== 'A';
  });

  readonly hasPendingOverride = computed(() => {
    const pkg = this.packageDetail()?.package;
    const execStatus = String(pkg?.execution_status ?? '').trim().toUpperCase();
    return execStatus === 'PENDING_OVERRIDE_APPROVAL';
  });

  readonly hasWaybill = computed(() => !!(this.waybill()?.waybill_no));

  // ── Staged fulfillment derived state ───────────────────────────
  readonly fulfillmentMode = computed<FulfillmentMode>(() =>
    (this.packageDetail()?.package?.fulfillment_mode ?? 'DIRECT') as FulfillmentMode,
  );
  readonly isStagedFulfillment = computed(() => this.fulfillmentMode() !== 'DIRECT');
  readonly isPickupMode = computed(() => this.fulfillmentMode() === 'PICKUP_AT_STAGING');
  readonly isDeliverFromStaging = computed(() => this.fulfillmentMode() === 'DELIVER_FROM_STAGING');

  readonly stagingWarehouseId = computed(
    () => this.packageDetail()?.package?.staging_warehouse_id ?? null,
  );
  readonly recommendedStagingWarehouseId = computed(
    () => this.packageDetail()?.package?.recommended_staging_warehouse_id ?? null,
  );
  readonly stagingSelectionBasis = computed(
    () => this.packageDetail()?.package?.staging_selection_basis ?? null,
  );
  readonly stagingOverrideReason = computed(
    () => this.packageDetail()?.package?.staging_override_reason ?? null,
  );
  readonly consolidationStatus = computed(
    () => this.packageDetail()?.package?.consolidation_status ?? null,
  );
  readonly effectiveDispatchSourceWarehouseId = computed(
    () => this.packageDetail()?.package?.effective_dispatch_source_warehouse_id ?? null,
  );

  readonly legSummary = computed(() => this.packageDetail()?.package?.leg_summary ?? null);
  readonly consolidationProgress = computed(() => {
    const summary = this.legSummary();
    return summary
      ? { received: summary.received_legs, total: summary.total_legs }
      : { received: 0, total: 0 };
  });
  readonly allLegsReceived = computed(() => this.legSummary()?.all_received ?? false);

  readonly canDispatchFromStaging = computed(() => {
    const pkg = this.packageDetail()?.package;
    const status = String(pkg?.status_code ?? '').trim().toUpperCase();
    return this.isDeliverFromStaging() && status === 'READY_FOR_DISPATCH';
  });
  readonly canReleaseForPickup = computed(() => {
    const pkg = this.packageDetail()?.package;
    const status = String(pkg?.status_code ?? '').trim().toUpperCase();
    return this.isPickupMode() && status === 'READY_FOR_PICKUP';
  });
  readonly canRequestPartialRelease = computed(() => {
    const status = String(this.consolidationStatus() ?? '').trim().toUpperCase();
    return this.isStagedFulfillment() && status === 'PARTIALLY_RECEIVED';
  });
  readonly canApprovePartialRelease = computed(() => {
    const status = String(this.consolidationStatus() ?? '').trim().toUpperCase();
    return status === 'PARTIAL_RELEASE_REQUESTED';
  });

  readonly splitChildren = computed(
    () => this.packageDetail()?.package?.split?.split_children ?? [],
  );
  readonly parentSplitInfo = computed(() => {
    const split = this.packageDetail()?.package?.split;
    if (!split?.split_from_package_id) {
      return null;
    }
    return { id: split.split_from_package_id, no: split.split_from_package_no };
  });

  readonly requestAvailabilityIssue = computed<StockAvailabilityIssue | null>(() => {
    const message = this.optionsError();
    if (!message) {
      return null;
    }
    if (message.includes(MISSING_WAREHOUSE_ERROR)) {
      return {
        kind: 'missing-warehouse',
        scope: 'request',
        detail: message,
      };
    }
    return null;
  });

  readonly selectedMethod = computed<AllocationMethod | undefined>(() => {
    const itemGroups = this.options()?.items ?? [];
    if (!itemGroups.length) {
      return undefined;
    }

    const hasBypass = itemGroups.some((group) => this.isRuleBypassedForItem(group.item_id));
    if (hasBypass) {
      return 'MANUAL';
    }

    const selectedGroups = itemGroups.filter((group) => this.getSelectedTotalForItem(group.item_id) > 0);
    if (!selectedGroups.length) {
      return undefined;
    }

    const issuanceOrders = new Set(
      selectedGroups
        .map((group) => {
          const normalized = String(group.issuance_order ?? '').trim().toUpperCase();
          return normalized === 'FEFO' || normalized === 'FIFO' ? normalized : null;
        })
        .filter((v): v is 'FEFO' | 'FIFO' => v !== null),
    );
    if (issuanceOrders.size === 1) {
      return [...issuanceOrders][0];
    }
    return 'MIXED';
  });

  readonly planRequiresOverride = computed(() =>
    (this.options()?.items ?? []).some((group) => {
      const total = this.getSelectedTotalForItem(group.item_id);
      return total > 0 && this.isRuleBypassedForItem(group.item_id);
    }),
  );

  readonly totalSelectedQty = computed(() =>
    Object.values(this.selectedRowsByItem())
      .flat()
      .reduce((sum, row) => sum + this.toNumber(row.quantity), 0),
  );

  readonly sourceWarehouseId = computed(() => this.draft().source_warehouse_id);

  /** Returns the effective warehouse for a given item (override if set, else item seed). */
  effectiveWarehouseForItem(itemId: number): string {
    const overrideWarehouseId = this.itemWarehouseOverrides()[itemId];
    if (overrideWarehouseId) {
      return overrideWarehouseId;
    }
    const seededWarehouseId = this.options()?.items.find((entry) => entry.item_id === itemId)?.source_warehouse_id;
    if (seededWarehouseId != null) {
      return String(seededWarehouseId);
    }
    return this.sourceWarehouseId();
  }

  // ── Loading ────────────────────────────────────────────────────

  load(reliefrqstId: number, loadOptions = true): void {
    const workspaceGeneration = this.beginWorkspaceGeneration();
    this.reliefrqstId.set(reliefrqstId);
    this.reliefpkgId.set(0);
    this.loading.set(true);
    this.loadError.set(null);
    this.optionsError.set(null);
    this.packageDetail.set(null);
    this.options.set(null);
    this.waybill.set(null);
    this.waybillError.set(null);
    this.selectedRowsByItem.set({});
    this.itemWarehouseOverrides.set({});
    this.seededWarehousesByItem.set({});
    this.loadedWarehousesByItem.set({});
    this.previewLoadingByItem.set({});
    this.addingWarehouseByItem.set({});
    this.draft.set({ ...DEFAULT_DRAFT });
    this.consolidationLegs.set([]);
    this.legsError.set(null);
    this.legsLoading.set(false);
    this.stagingRecommendation.set(null);
    this.recommendationError.set(null);
    this.recommendationLoading.set(false);
    this.lockConflict.set(null);

    this.operationsService.getPackage(reliefrqstId).pipe(
      catchError((error: HttpErrorResponse) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration)) {
          return EMPTY;
        }
        this.loadError.set(this.extractError(error, 'Failed to load package details.'));
        this.loading.set(false);
        return EMPTY;
      }),
    ).subscribe({
      next: (packageDetail) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration)) {
          return;
        }
        this.packageDetail.set(packageDetail);
        if (packageDetail) {
          this.hydrateDraft(packageDetail);
          if (packageDetail.package) {
            this.reliefpkgId.set(packageDetail.package.reliefpkg_id);
          }
        }

        // Eagerly load consolidation legs when package is staged so the
        // consolidation panel is synchronous with the rest of the workspace.
        const mode = packageDetail?.package?.fulfillment_mode;
        const pkgId = packageDetail?.package?.reliefpkg_id;
        if (mode && mode !== 'DIRECT' && pkgId) {
          this.loadConsolidationLegs(pkgId);
        }

        if (!loadOptions) {
          this.options.set(null);
          this.loading.set(false);
          return;
        }
        this.loadAllocationOptions(
          reliefrqstId,
          packageDetail?.package?.source_warehouse_id ?? undefined,
          packageDetail,
          workspaceGeneration,
        );
      },
      error: () => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration)) {
          return;
        }
        this.loading.set(false);
        this.loadError.set('Failed to load fulfillment workspace.');
      },
    });
  }

  refreshPackage(): void {
    const reliefrqstId = this.reliefrqstId();
    if (!reliefrqstId) {
      return;
    }
    const workspaceGeneration = this.latestWorkspaceGeneration;
    this.operationsService.getPackage(reliefrqstId).subscribe({
      next: (detail) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration)) {
          return;
        }
        this.packageDetail.set(detail);
        this.hydrateDraft(detail);
        if (detail.package) {
          this.reliefpkgId.set(detail.package.reliefpkg_id);
        }
      },
      error: (error: HttpErrorResponse) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration)) {
          return;
        }
        this.loadError.set(this.extractError(error, 'Failed to refresh package status.'));
      },
    });
  }

  // ── Staged fulfillment loading ─────────────────────────────────

  loadConsolidationLegs(reliefpkgId: number): void {
    if (!reliefpkgId) {
      return;
    }
    const workspaceGeneration = this.latestWorkspaceGeneration;
    const requestId = ++this.latestLegsRequestId;
    this.legsLoading.set(true);
    this.legsError.set(null);

    this.operationsService.getConsolidationLegs(reliefpkgId).subscribe({
      next: (response) => {
        if (
          !this.isCurrentWorkspaceGeneration(workspaceGeneration)
          || this.latestLegsRequestId !== requestId
        ) {
          return;
        }
        this.consolidationLegs.set(response.results ?? []);
        if (response.package) {
          this.packageDetail.update((current) => {
            if (current) {
              return { ...current, package: response.package };
            }
            return this.buildStandalonePackageDetail(response.package);
          });
          this.reliefpkgId.set(response.package.reliefpkg_id);
          if (response.package.reliefrqst_id) {
            this.reliefrqstId.set(response.package.reliefrqst_id);
          }
        }
        this.legsLoading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        if (
          !this.isCurrentWorkspaceGeneration(workspaceGeneration)
          || this.latestLegsRequestId !== requestId
        ) {
          return;
        }
        this.legsLoading.set(false);
        this.legsError.set(this.extractError(error, 'Failed to load consolidation legs.'));
      },
    });
  }

  /**
   * For standalone consolidation pages that load by reliefpkg_id — builds
   * a minimal PackageDetailResponse shell so computed signals work without a
   * full workspace load.
   */
  private buildStandalonePackageDetail(pkg: NonNullable<PackageDetailResponse['package']>): PackageDetailResponse {
    return {
      request: {
        reliefrqst_id: pkg.reliefrqst_id,
        tracking_no: pkg.tracking_no,
        agency_id: pkg.agency_id,
        agency_name: null,
        eligible_event_id: pkg.eligible_event_id,
        event_name: null,
        urgency_ind: null,
        status_code: 'DRAFT',
        status_label: '',
        request_date: null,
        create_dtime: null,
        review_dtime: null,
        action_dtime: null,
        rqst_notes_text: null,
        review_notes_text: null,
        status_reason_desc: null,
        version_nbr: 0,
        item_count: 0,
        total_requested_qty: '0',
        total_issued_qty: '0',
        reliefpkg_id: pkg.reliefpkg_id,
        package_tracking_no: pkg.tracking_no,
        package_status: pkg.status_code,
        execution_status: pkg.execution_status,
        needs_list_id: pkg.needs_list_id,
        compatibility_bridge: pkg.compatibility_bridge,
        request_mode: null,
        authority_context: null,
      } as PackageDetailResponse['request'],
      package: pkg,
      items: [],
      compatibility_only: false,
    };
  }

  refreshConsolidationLegs(): void {
    const pkgId = this.reliefpkgId();
    if (pkgId) {
      this.loadConsolidationLegs(pkgId);
    }
  }

  loadStagingRecommendation(reliefrqstId: number): void {
    if (!reliefrqstId) {
      return;
    }
    const workspaceGeneration = this.latestWorkspaceGeneration;
    const requestId = ++this.latestRecommendationRequestId;
    this.recommendationLoading.set(true);
    this.recommendationError.set(null);

    this.operationsService.getStagingRecommendation(reliefrqstId).subscribe({
      next: (recommendation) => {
        if (
          !this.isCurrentWorkspaceGeneration(workspaceGeneration)
          || this.latestRecommendationRequestId !== requestId
        ) {
          return;
        }
        this.stagingRecommendation.set(recommendation);
        this.recommendationLoading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        if (
          !this.isCurrentWorkspaceGeneration(workspaceGeneration)
          || this.latestRecommendationRequestId !== requestId
        ) {
          return;
        }
        this.recommendationLoading.set(false);
        this.recommendationError.set(
          this.extractError(error, 'Failed to load staging recommendation.'),
        );
      },
    });
  }

  dispatchLeg(
    legId: number,
    payload: ConsolidationLegDispatchPayload,
  ): Observable<ConsolidationLegDispatchResponse> {
    const pkgId = this.reliefpkgId();
    if (!pkgId) {
      return EMPTY as unknown as Observable<ConsolidationLegDispatchResponse>;
    }
    return this.operationsService.dispatchConsolidationLeg(pkgId, legId, payload).pipe(
      tap((response) => {
        if (response.package) {
          this.packageDetail.update((current) =>
            current ? { ...current, package: response.package } : current,
          );
        }
        this.refreshConsolidationLegs();
      }),
    );
  }

  receiveLeg(
    legId: number,
    payload: ConsolidationLegReceivePayload,
  ): Observable<ConsolidationLegReceiveResponse> {
    const pkgId = this.reliefpkgId();
    if (!pkgId) {
      return EMPTY as unknown as Observable<ConsolidationLegReceiveResponse>;
    }
    return this.operationsService.receiveConsolidationLeg(pkgId, legId, payload).pipe(
      tap((response) => {
        if (response.package) {
          this.packageDetail.update((current) =>
            current ? { ...current, package: response.package } : current,
          );
        }
        this.refreshConsolidationLegs();
      }),
    );
  }

  requestPartialRelease(
    payload: PartialReleaseRequestPayload,
  ): Observable<PartialReleaseRequestResponse> {
    const pkgId = this.reliefpkgId();
    if (!pkgId) {
      return EMPTY as unknown as Observable<PartialReleaseRequestResponse>;
    }
    return this.operationsService.requestPartialRelease(pkgId, payload).pipe(
      tap((response) => {
        if (response.package) {
          this.packageDetail.update((current) =>
            current ? { ...current, package: response.package } : current,
          );
        }
        this.refreshConsolidationLegs();
      }),
    );
  }

  approvePartialRelease(
    payload: PartialReleaseApprovePayload,
  ): Observable<PartialReleaseApproveResponse> {
    const pkgId = this.reliefpkgId();
    if (!pkgId) {
      return EMPTY as unknown as Observable<PartialReleaseApproveResponse>;
    }
    return this.operationsService.approvePartialRelease(pkgId, payload).pipe(
      tap((response) => {
        if (response.parent) {
          this.packageDetail.update((current) =>
            current ? { ...current, package: response.parent } : current,
          );
        }
        this.refreshConsolidationLegs();
      }),
    );
  }

  releaseForPickup(payload: PickupReleasePayload): Observable<PickupReleaseResponse> {
    const pkgId = this.reliefpkgId();
    if (!pkgId) {
      return EMPTY as unknown as Observable<PickupReleaseResponse>;
    }
    return this.operationsService.submitPickupRelease(pkgId, payload).pipe(
      tap((response) => {
        if (response.package) {
          this.packageDetail.update((current) =>
            current ? { ...current, package: response.package } : current,
          );
        }
      }),
    );
  }

  saveDraft(): Observable<PackageDetailResponse> {
    const reliefrqstId = this.reliefrqstId();
    if (!reliefrqstId) {
      return EMPTY as unknown as Observable<PackageDetailResponse>;
    }
    const payload = this.buildPackageDraftPayload();
    return this.operationsService.savePackageDraft(reliefrqstId, payload).pipe(
      tap((detail) => {
        this.packageDetail.set(detail);
        this.hydrateDraft(detail);
        if (detail.package) {
          this.reliefpkgId.set(detail.package.reliefpkg_id);
        }
      }),
      catchError((error: HttpErrorResponse) => this.routeWriteError(error)),
    );
  }

  saveFulfillmentModeDraft(
    fulfillmentMode: FulfillmentMode,
    stagingWarehouseId: number | null,
    stagingOverrideReason: string | null,
  ): Observable<PackageDetailResponse> {
    const reliefrqstId = this.reliefrqstId();
    const payload = this.buildPackageDraftPayload({
      fulfillment_mode: fulfillmentMode,
      staging_warehouse_id: stagingWarehouseId != null ? String(stagingWarehouseId) : '',
      staging_override_reason: stagingOverrideReason ?? '',
    });
    this.patchDraft({
      fulfillment_mode: fulfillmentMode,
      staging_warehouse_id: stagingWarehouseId != null ? String(stagingWarehouseId) : '',
      staging_override_reason: stagingOverrideReason ?? '',
    });
    return this.operationsService.savePackageDraft(reliefrqstId, payload).pipe(
      tap((detail) => {
        this.packageDetail.set(detail);
        this.hydrateDraft(detail);
        if (detail.package) {
          this.reliefpkgId.set(detail.package.reliefpkg_id);
          if (
            detail.package.fulfillment_mode
            && detail.package.fulfillment_mode !== 'DIRECT'
          ) {
            this.loadConsolidationLegs(detail.package.reliefpkg_id);
          } else {
            this.consolidationLegs.set([]);
          }
        }
      }),
      catchError((error: HttpErrorResponse) => this.routeWriteError(error)),
    );
  }

  /**
   * Release the package lock for the current request. With `force=false` this is a
   * self-release (only the owner may succeed). With `force=true` this is a takeover
   * (backend enforces the LOGISTICS_MANAGER / SYSTEM_ADMINISTRATOR role rule).
   *
   * On any terminal response the lockConflict signal is cleared, because both a real
   * release and a no-op response mean the blocker is no longer meaningful. A real
   * release (`released: true`) also reloads the package so the workspace re-hydrates
   * with lock-free state.
   */
  releasePackageLock(force: boolean): Observable<PackageLockReleaseResponse> {
    const reliefrqstId = this.reliefrqstId();
    if (!reliefrqstId || this.unlocking()) {
      return EMPTY as unknown as Observable<PackageLockReleaseResponse>;
    }
    this.unlocking.set(true);
    return this.operationsService.releasePackageLock(reliefrqstId, force).pipe(
      tap((response) => {
        this.lockConflict.set(null);
        if (response.released) {
          this.load(reliefrqstId, true);
        }
      }),
      finalize(() => this.unlocking.set(false)),
    );
  }

  /**
   * Centralised write-path error router. If the error is a package-lock conflict,
   * populate the blocker signal and re-throw so callers can still short-circuit via
   * their own error handlers. All other errors pass through untouched.
   */
  private routeWriteError(error: unknown): Observable<never> {
    this.captureLockConflict(error);
    return throwError(() => error);
  }

  /**
   * Public entry point for component-level error handlers that call write endpoints
   * directly (e.g. commitAllocations, approveOverride via runAllocationAction). Returns
   * true when a package-lock conflict was detected and captured, so the component can
   * skip its own generic error snackbar.
   */
  captureLockConflict(error: unknown): boolean {
    const conflict = tryParsePackageLockConflict(error);
    if (!conflict) {
      return false;
    }
    this.lockConflict.set(conflict);
    return true;
  }

  clearLockConflict(): void {
    this.lockConflict.set(null);
  }

  loadWaybill(): void {
    const pkgId = this.reliefpkgId();
    if (!pkgId) {
      return;
    }
    this.waybillLoading.set(true);
    this.waybillError.set(null);
    this.operationsService.getWaybill(pkgId).subscribe({
      next: (payload) => {
        this.waybill.set(payload);
        this.waybillLoading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.waybillLoading.set(false);
        this.waybillError.set(this.extractError(error, 'Waybill details are not available yet.'));
      },
    });
  }

  // ── Draft management ───────────────────────────────────────────

  patchDraft(patch: Partial<WorkspaceDraft>): void {
    this.draft.update((current) => ({ ...current, ...patch }));
  }

  updateSourceWarehouse(sourceWarehouseId: string): void {
    const normalizedSourceWarehouseId = this.sanitizeInteger(sourceWarehouseId);

    const reliefrqstId = this.reliefrqstId();
    if (!reliefrqstId) {
      this.patchDraft({ source_warehouse_id: normalizedSourceWarehouseId });
      this.itemWarehouseOverrides.set({});
      return;
    }

    // Capture previous state for rollback on error.
    const prevDraft = this.draft();
    const prevOverrides = this.itemWarehouseOverrides();
    const prevSeededWarehouses = this.seededWarehousesByItem();
    const prevOptions = this.options();
    const prevSelections = this.selectedRowsByItem();

    this.patchDraft({ source_warehouse_id: normalizedSourceWarehouseId });

    // Changing the default warehouse resets all per-item overrides.
    this.itemWarehouseOverrides.set({});

    this.loading.set(true);
    this.loadError.set(null);
    this.optionsError.set(null);
    this.options.set(null);
    this.selectedRowsByItem.set({});
    const workspaceGeneration = this.beginWorkspaceGeneration();
    const requestId = ++this.latestSourceWarehouseRequestId;

    const draft = this.draft();
    this.operationsService.savePackageDraft(reliefrqstId, {
      source_warehouse_id: normalizedSourceWarehouseId ? Number(normalizedSourceWarehouseId) : undefined,
      to_inventory_id: draft.to_inventory_id ? Number(draft.to_inventory_id) : undefined,
      transport_mode: draft.transport_mode.trim() || undefined,
      comments_text: draft.comments_text.trim() || undefined,
      fulfillment_mode: draft.fulfillment_mode,
      staging_warehouse_id: draft.staging_warehouse_id
        ? Number(draft.staging_warehouse_id)
        : undefined,
      staging_override_reason: draft.staging_override_reason.trim() || undefined,
    }).subscribe({
      next: (detail) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration) || this.latestSourceWarehouseRequestId !== requestId) {
          return;
        }
        this.packageDetail.set(detail);
        this.hydrateDraft(detail);
        if (detail.package) {
          this.reliefpkgId.set(detail.package.reliefpkg_id);
        }
        this.loadAllocationOptions(
          reliefrqstId,
          detail.package?.source_warehouse_id ?? undefined,
          detail,
          workspaceGeneration,
          requestId,
        );
      },
      error: (error: HttpErrorResponse) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration) || this.latestSourceWarehouseRequestId !== requestId) {
          return;
        }
        this.patchDraft({ source_warehouse_id: prevDraft.source_warehouse_id });
        this.itemWarehouseOverrides.set(prevOverrides);
        this.seededWarehousesByItem.set(prevSeededWarehouses);
        this.options.set(prevOptions);
        this.selectedRowsByItem.set(prevSelections);
        this.loading.set(false);
        const lockConflict = tryParsePackageLockConflict(error);
        if (lockConflict) {
          // Lock is surfaced as a first-class blocker; suppress the generic loadError banner.
          this.lockConflict.set(lockConflict);
          return;
        }
        this.loadError.set(this.extractError(error, 'Failed to save package draft.'));
      },
    });
  }

  /**
   * Change the source warehouse for a single item without reloading all items.
   * Only the target item's candidates and selections are refreshed.
   */
  updateItemWarehouse(itemId: number, warehouseId: string): void {
    const normalizedWarehouseId = this.sanitizeInteger(warehouseId);
    const seededWarehouseId = this.getSeededWarehouseIdForItem(itemId);
    const reliefrqstId = this.reliefrqstId();
    const workspaceGeneration = this.latestWorkspaceGeneration;
    if (!reliefrqstId || !normalizedWarehouseId) {
      return;
    }
    const prevOverrideValue = this.itemWarehouseOverrides()[itemId];
    const prevSelectionValue = this.selectedRowsByItem()[itemId];

    const requestId = (this.latestItemWarehouseRequestIds[itemId] ?? 0) + 1;
    this.latestItemWarehouseRequestIds[itemId] = requestId;

    this.switching.set(true);

    this.operationsService.getItemAllocationOptions(
      reliefrqstId,
      itemId,
      Number(normalizedWarehouseId),
    ).subscribe({
      next: (itemGroup) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration) || this.latestItemWarehouseRequestIds[itemId] !== requestId) {
          return;
        }
        if (seededWarehouseId && !this.seededWarehousesByItem()[itemId]) {
          this.seededWarehousesByItem.update((map) => ({ ...map, [itemId]: seededWarehouseId }));
        }
        const currentOverrides = { ...this.itemWarehouseOverrides() };
        if (seededWarehouseId && normalizedWarehouseId === seededWarehouseId) {
          delete currentOverrides[itemId];
        } else {
          currentOverrides[itemId] = normalizedWarehouseId;
        }
        this.itemWarehouseOverrides.set(currentOverrides);
        this.optionsError.set(null);

        const currentOptions = this.options();
        if (currentOptions) {
          const updatedItems = currentOptions.items.map((existing) =>
            existing.item_id === itemId ? itemGroup : existing,
          );
          this.options.set({ ...currentOptions, items: updatedItems });
        }
        this.selectedRowsByItem.set({
          ...this.selectedRowsByItem(),
          [itemId]: itemGroup.suggested_allocations.map((line) => ({
            item_id: line.item_id,
            inventory_id: line.inventory_id,
            batch_id: line.batch_id,
            quantity: line.quantity,
            source_type: line.source_type,
            source_record_id: line.source_record_id ?? null,
            uom_code: line.uom_code ?? null,
          })),
        });
        // Override is a swap, not an add — reset multi-warehouse tracking for this item.
        this.loadedWarehousesByItem.set({
          ...this.loadedWarehousesByItem(),
          [itemId]: [Number(normalizedWarehouseId)],
        });
        this.switching.set(false);
      },
      error: (error: HttpErrorResponse) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration) || this.latestItemWarehouseRequestIds[itemId] !== requestId) {
          return;
        }
        const rollbackOverrides = { ...this.itemWarehouseOverrides() };
        if (prevOverrideValue !== undefined) {
          rollbackOverrides[itemId] = prevOverrideValue;
        } else {
          delete rollbackOverrides[itemId];
        }
        this.itemWarehouseOverrides.set(rollbackOverrides);
        const rollbackSelections = { ...this.selectedRowsByItem() };
        if (prevSelectionValue !== undefined) {
          rollbackSelections[itemId] = prevSelectionValue;
        } else {
          delete rollbackSelections[itemId];
        }
        this.selectedRowsByItem.set(rollbackSelections);
        this.optionsError.set(this.extractError(error, 'Failed to load stock for this item.'));
        this.switching.set(false);
      },
    });
  }

  /**
   * Add an additional warehouse to an item's allocation, preserving prior selections.
   * Used by the multi-warehouse continuation flow when a single warehouse cannot
   * cover the full requested quantity.
   */
  addItemWarehouse(itemId: number, warehouseId: number): void {
    const reliefrqstId = this.reliefrqstId();
    const workspaceGeneration = this.latestWorkspaceGeneration;
    if (!reliefrqstId || !warehouseId || warehouseId <= 0) {
      return;
    }
    const alreadyLoaded = this.loadedWarehousesByItem()[itemId] ?? [];
    if (alreadyLoaded.includes(warehouseId)) {
      return;
    }

    const requestId = (this.latestItemAddRequestIds[itemId] ?? 0) + 1;
    this.latestItemAddRequestIds[itemId] = requestId;

    this.addingWarehouseByItem.update((map) => ({ ...map, [itemId]: true }));
    const draftAllocations = (this.selectedRowsByItem()[itemId] ?? [])
      .filter((row) => this.toNumber(row.quantity) > 0)
      .map((row) => ({
        item_id: row.item_id,
        inventory_id: row.inventory_id,
        batch_id: row.batch_id,
        quantity: this.formatQuantity(this.toNumber(row.quantity)),
        source_type: row.source_type ?? 'ON_HAND',
        source_record_id: row.source_record_id ?? null,
        uom_code: row.uom_code ?? null,
      }));

    this.operationsService.previewItemAllocationOptions(reliefrqstId, itemId, {
      source_warehouse_id: warehouseId,
      draft_allocations: draftAllocations,
    }).subscribe({
      next: (newGroup) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration)) {
          return;
        }
        if (this.latestItemAddRequestIds[itemId] !== requestId) {
          return;
        }

        const currentOptions = this.options();
        if (!currentOptions) {
          this.addingWarehouseByItem.update((map) => ({ ...map, [itemId]: false }));
          return;
        }

        const existing = currentOptions.items.find((entry) => entry.item_id === itemId);
        if (!existing) {
          this.addingWarehouseByItem.update((map) => ({ ...map, [itemId]: false }));
          return;
        }

        // Append candidates from the new warehouse, de-duplicating by selection key.
        const existingKeys = new Set(existing.candidates.map((c) => this.selectionKey(c)));
        const appendedCandidates = newGroup.candidates.filter(
          (c) => !existingKeys.has(this.selectionKey(c)),
        );
        const mergedCandidates = [...existing.candidates, ...appendedCandidates];

        // Append the new warehouse's suggested allocations to the existing selections.
        const priorSelections = this.selectedRowsByItem()[itemId] ?? [];
        const priorSelectionKeys = new Set(priorSelections.map((r) => this.selectionKey(r)));
        const newSelections = newGroup.suggested_allocations
          .filter((line) => !priorSelectionKeys.has(this.selectionKey(line)))
          .map((line) => ({
            item_id: line.item_id,
            inventory_id: line.inventory_id,
            batch_id: line.batch_id,
            quantity: line.quantity,
            source_type: line.source_type,
            source_record_id: line.source_record_id ?? null,
            uom_code: line.uom_code ?? null,
          }));
        const mergedSelections = [...priorSelections, ...newSelections];

        // Merge the item group: keep prior fields, update continuation hints from the
        // server response, and replace the candidate list with the merged one.
        const mergedItem: AllocationItemGroup = {
          ...existing,
          candidates: mergedCandidates,
          source_warehouse_id: existing.source_warehouse_id ?? newGroup.source_warehouse_id,
          remaining_shortfall_qty: newGroup.remaining_shortfall_qty,
          continuation_recommended: newGroup.continuation_recommended,
          alternate_warehouses: newGroup.alternate_warehouses,
          draft_selected_qty: newGroup.draft_selected_qty,
          effective_remaining_qty: newGroup.effective_remaining_qty,
        };

        this.options.set({
          ...currentOptions,
          items: currentOptions.items.map((entry) =>
            entry.item_id === itemId ? mergedItem : entry,
          ),
        });
        this.selectedRowsByItem.set({
          ...this.selectedRowsByItem(),
          [itemId]: this.sortSelections(itemId, mergedSelections),
        });
        this.loadedWarehousesByItem.set({
          ...this.loadedWarehousesByItem(),
          [itemId]: [...alreadyLoaded, warehouseId],
        });
        this.addingWarehouseByItem.update((map) => ({ ...map, [itemId]: false }));
        this.optionsError.set(null);
        this.previewItemAllocations(itemId, warehouseId);
      },
      error: (error: HttpErrorResponse) => {
        if (!this.isCurrentWorkspaceGeneration(workspaceGeneration)) {
          return;
        }
        if (this.latestItemAddRequestIds[itemId] !== requestId) {
          return;
        }
        this.addingWarehouseByItem.update((map) => ({ ...map, [itemId]: false }));
        this.optionsError.set(this.extractError(error, 'Failed to load stock for this item.'));
      },
    });
  }

  /**
   * Recompute the draft-aware continuation metrics for a single item against the
   * currently-selected draft allocations. Only continuation fields are merged into
   * the cached item group — candidates and selections are user-driven and untouched.
   */
  previewItemAllocations(itemId: number, sourceWarehouseId: number): void {
    const reliefrqstId = this.reliefrqstId();
    if (!reliefrqstId || !sourceWarehouseId || sourceWarehouseId <= 0) {
      return;
    }
    const workspaceGeneration = this.latestWorkspaceGeneration;
    const requestId = (this.latestItemPreviewRequestIds[itemId] ?? 0) + 1;
    this.latestItemPreviewRequestIds[itemId] = requestId;

    this.previewLoadingByItem.update((map) => ({ ...map, [itemId]: true }));

    const draftAllocations = (this.selectedRowsByItem()[itemId] ?? [])
      .filter((row) => this.toNumber(row.quantity) > 0)
      .map((row) => ({
        item_id: row.item_id,
        inventory_id: row.inventory_id,
        batch_id: row.batch_id,
        quantity: this.formatQuantity(this.toNumber(row.quantity)),
        source_type: row.source_type ?? 'ON_HAND',
        source_record_id: row.source_record_id ?? null,
        uom_code: row.uom_code ?? null,
      }));

    this.operationsService
      .previewItemAllocationOptions(reliefrqstId, itemId, {
        source_warehouse_id: sourceWarehouseId,
        draft_allocations: draftAllocations,
      })
      .subscribe({
        next: (preview) => {
          if (!this.isCurrentWorkspaceGeneration(workspaceGeneration)) {
            return;
          }
          if (this.latestItemPreviewRequestIds[itemId] !== requestId) {
            return;
          }
          const currentOptions = this.options();
          if (currentOptions) {
            const updatedItems = currentOptions.items.map((existing) =>
              existing.item_id === itemId
                ? {
                    ...existing,
                    remaining_shortfall_qty: preview.remaining_shortfall_qty,
                    continuation_recommended: preview.continuation_recommended,
                    alternate_warehouses: preview.alternate_warehouses,
                    draft_selected_qty: preview.draft_selected_qty,
                    effective_remaining_qty: preview.effective_remaining_qty,
                  }
                : existing,
            );
            this.options.set({ ...currentOptions, items: updatedItems });
          }
          this.previewLoadingByItem.update((map) => ({ ...map, [itemId]: false }));
        },
        error: () => {
          if (!this.isCurrentWorkspaceGeneration(workspaceGeneration)) {
            return;
          }
          if (this.latestItemPreviewRequestIds[itemId] !== requestId) {
            return;
          }
          // Soft-fail: continuation hint just won't refresh; don't disrupt the user.
          this.previewLoadingByItem.update((map) => ({ ...map, [itemId]: false }));
        },
      });
  }

  /** Clear all per-item warehouse overrides and reload with the default warehouse. */
  clearWarehouseOverrides(): void {
    const reliefrqstId = this.reliefrqstId();
    const sourceWarehouseId = this.sanitizeInteger(this.sourceWarehouseId());

    if (reliefrqstId) {
      const workspaceGeneration = this.beginWorkspaceGeneration();
      this.loading.set(true);
      this.loadError.set(null);
      this.optionsError.set(null);
      this.itemWarehouseOverrides.set({});
      this.options.set(null);
      this.selectedRowsByItem.set({});
      this.loadAllocationOptions(
        reliefrqstId,
        sourceWarehouseId ? Number(sourceWarehouseId) : undefined,
        this.packageDetail(),
        workspaceGeneration,
      );
      return;
    }

    this.itemWarehouseOverrides.set({});
    this.options.set(null);
    this.selectedRowsByItem.set({});
  }

  // ── Selection management ───────────────────────────────────────

  useSuggestedPlan(itemId: number): void {
    const group = this.getItemGroup(itemId);
    if (!group) {
      return;
    }
    const next = {
      ...this.selectedRowsByItem(),
      [itemId]: group.suggested_allocations.map((row) => ({
        item_id: row.item_id,
        inventory_id: row.inventory_id,
        batch_id: row.batch_id,
        quantity: row.quantity,
        source_type: row.source_type,
        source_record_id: row.source_record_id ?? null,
        uom_code: row.uom_code ?? null,
      })),
    };
    this.selectedRowsByItem.set(next);
    this.maybeRefreshContinuationPreview(itemId);
  }

  clearItemSelection(itemId: number): void {
    const next = { ...this.selectedRowsByItem() };
    next[itemId] = [];
    this.selectedRowsByItem.set(next);
    this.maybeRefreshContinuationPreview(itemId);
  }

  setCandidateQuantity(itemId: number, candidate: AllocationCandidate, quantity: number): void {
    const normalizedQty = this.toFixedQuantity(Math.max(0, quantity));
    const rows = [...(this.selectedRowsByItem()[itemId] ?? [])];
    const existingIndex = rows.findIndex(
      (row) => this.selectionKey(row) === this.selectionKey(candidate),
    );
    if (normalizedQty <= 0) {
      if (existingIndex >= 0) {
        rows.splice(existingIndex, 1);
      }
    } else {
      const nextRow: AllocationSelectionPayload = {
        item_id: itemId,
        inventory_id: candidate.inventory_id,
        batch_id: candidate.batch_id,
        quantity: this.formatQuantity(normalizedQty),
        source_type: candidate.source_type,
        source_record_id: candidate.source_record_id ?? null,
        uom_code: candidate.uom_code ?? null,
      };
      if (existingIndex >= 0) {
        rows[existingIndex] = nextRow;
      } else {
        rows.push(nextRow);
      }
    }
    this.selectedRowsByItem.set({
      ...this.selectedRowsByItem(),
      [itemId]: this.sortSelections(itemId, rows),
    });
    this.maybeRefreshContinuationPreview(itemId);
  }

  /**
   * Recompute the draft-aware continuation hints whenever an item's selections
   * change AND continuation guidance is currently active for that item. Guidance
   * is active when the backend recommends continuation (single warehouse, has
   * shortfall) OR when the item is already spread across multiple warehouses
   * (in which case effective_remaining_qty is the only honest figure). Items
   * with no continuation guidance skip the preview entirely.
   */
  private maybeRefreshContinuationPreview(itemId: number): void {
    const loaded = this.loadedWarehousesByItem()[itemId] ?? [];
    if (loaded.length === 0) {
      return;
    }
    const item = this.getItemGroup(itemId);
    const continuationActive =
      (item?.continuation_recommended ?? false) || loaded.length > 1;
    if (!continuationActive) {
      return;
    }
    const previewWarehouseId = loaded[loaded.length - 1];
    if (!previewWarehouseId) {
      return;
    }
    this.previewItemAllocations(itemId, previewWarehouseId);
  }

  getSelectedRows(itemId: number): AllocationSelectionPayload[] {
    return this.selectedRowsByItem()[itemId] ?? [];
  }

  getSelectedQtyForCandidate(itemId: number, candidate: AllocationCandidate): number {
    const row = this.getSelectedRows(itemId).find(
      (entry) => this.selectionKey(entry) === this.selectionKey(candidate),
    );
    return this.toNumber(row?.quantity);
  }

  getSelectedTotalForItem(itemId: number): number {
    return this.getSelectedRows(itemId).reduce(
      (sum, row) => sum + this.toNumber(row.quantity),
      0,
    );
  }

  getRemainingQtyForItem(itemId: number): number {
    return this.toNumber(this.getItemGroup(itemId)?.remaining_qty);
  }

  getUncoveredQtyForItem(itemId: number): number {
    return Math.max(0, this.getRemainingQtyForItem(itemId) - this.getSelectedTotalForItem(itemId));
  }

  getGreedyRecommendationForSelectedTotal(itemId: number): AllocationSelectionPayload[] {
    const group = this.getItemGroup(itemId);
    if (!group) {
      return [];
    }
    let remaining = this.getSelectedTotalForItem(itemId);
    const rows: AllocationSelectionPayload[] = [];
    for (const candidate of group.candidates) {
      if (remaining <= 0) {
        break;
      }
      const available = this.toNumber(candidate.available_qty);
      if (available <= 0) {
        continue;
      }
      const quantity = Math.min(available, remaining);
      rows.push({
        item_id: itemId,
        inventory_id: candidate.inventory_id,
        batch_id: candidate.batch_id,
        quantity: this.formatQuantity(quantity),
        source_type: candidate.source_type,
        source_record_id: candidate.source_record_id ?? null,
        uom_code: candidate.uom_code ?? null,
      });
      remaining = this.toFixedQuantity(remaining - quantity);
    }
    return rows;
  }

  isRuleBypassedForItem(itemId: number): boolean {
    const selectedRows = this.getSelectedRows(itemId).filter(
      (row) => this.toNumber(row.quantity) > 0,
    );
    if (!selectedRows.length) {
      return false;
    }
    return (
      this.selectionSignature(selectedRows) !==
      this.selectionSignature(this.getGreedyRecommendationForSelectedTotal(itemId))
    );
  }

  getItemValidationMessage(item: AllocationItemGroup): string | null {
    const selected = this.getSelectedTotalForItem(item.item_id);
    const remaining = this.toNumber(item.remaining_qty);
    if (selected <= 0) {
      return 'Select at least one stock line before continuing.';
    }
    if (selected > remaining + 0.0001) {
      return 'You cannot allocate more than the item still needs.';
    }
    for (const candidate of item.candidates) {
      const selectedQty = this.getSelectedQtyForCandidate(item.item_id, candidate);
      if (selectedQty > this.toNumber(candidate.available_qty) + 0.0001) {
        return `You cannot allocate more than batch ${candidate.batch_no || candidate.batch_id} has available.`;
      }
    }
    return null;
  }

  getItemAvailabilityIssue(item: AllocationItemGroup): StockAvailabilityIssue | null {
    const remaining = this.toNumber(item.remaining_qty);
    if (remaining > 0 && item.candidates.length === 0) {
      return {
        kind: 'no-candidates',
        scope: 'item',
      };
    }
    return null;
  }

  // ── Payload builders ───────────────────────────────────────────

  buildCommitPayload(): { payload: AllocationCommitPayload | null; errors: string[] } {
    const errors: string[] = [];
    const allocations = this.buildDraftAllocationSelections();

    if (!allocations.length) {
      errors.push('Select at least one stock line to reserve.');
    }

    for (const item of this.options()?.items ?? []) {
      const validation = this.getItemValidationMessage(item);
      if (validation) {
        errors.push(`${item.item_name || `Item ${item.item_id}`}: ${validation}`);
      }
    }

    if (errors.length) {
      return { payload: null, errors: [...new Set(errors)] };
    }

    const payload: AllocationCommitPayload = {
      source_warehouse_id: this.getDerivedSourceWarehouseId(),
      allocations,
      to_inventory_id: this.draft().to_inventory_id ? Number(this.draft().to_inventory_id) : undefined,
      transport_mode: this.draft().transport_mode.trim() || undefined,
      comments_text: this.draft().comments_text.trim() || undefined,
      override_reason_code: this.planRequiresOverride() ? (this.draft().override_reason_code.trim() || undefined) : undefined,
      override_note: this.planRequiresOverride() ? (this.draft().override_note.trim() || undefined) : undefined,
    };
    return { payload, errors: [] };
  }

  buildOverrideApprovalPayload(): { payload: OverrideApprovalPayload | null; errors: string[] } {
    const draft = this.draft();
    const errors: string[] = [];
    if (!draft.override_reason_code.trim()) {
      errors.push('Select an override reason before approving.');
    }
    if (!draft.override_note.trim()) {
      errors.push('Add an override note before approving.');
    }
    if (errors.length) {
      return { payload: null, errors };
    }

    const allocationLines = this.packageDetail()?.allocation?.allocation_lines ?? [];
    return {
      payload: {
        allocations: allocationLines.map((line) => ({
          item_id: line.item_id,
          inventory_id: line.inventory_id,
          batch_id: line.batch_id,
          quantity: line.quantity,
          source_type: line.source_type,
          source_record_id: line.source_record_id ?? null,
          uom_code: line.uom_code ?? null,
        })),
        override_reason_code: draft.override_reason_code.trim(),
        override_note: draft.override_note.trim(),
      },
      errors: [],
    };
  }

  setSubmitting(isSubmitting: boolean): void {
    this.submitting.set(isSubmitting);
  }

  // ── Private helpers ────────────────────────────────────────────

  private hydrateDraft(detail: PackageDetailResponse): void {
    const pkg = detail.package;
    if (!pkg) {
      return;
    }
    const storedOverrideReason =
      detail.allocation?.allocation_lines.find((line) => !!String(line.override_reason_code ?? '').trim())
        ?.override_reason_code ?? '';
    this.draft.update((d) => ({
      ...d,
      source_warehouse_id: pkg.source_warehouse_id != null ? String(pkg.source_warehouse_id) : (d.source_warehouse_id || ''),
      to_inventory_id: d.to_inventory_id || (pkg.to_inventory_id != null ? String(pkg.to_inventory_id) : ''),
      transport_mode: d.transport_mode || pkg.transport_mode || '',
      comments_text: d.comments_text || pkg.comments_text || '',
      override_reason_code: d.override_reason_code || storedOverrideReason,
      fulfillment_mode: (pkg.fulfillment_mode ?? d.fulfillment_mode ?? 'DIRECT') as FulfillmentMode,
      staging_warehouse_id:
        pkg.staging_warehouse_id != null
          ? String(pkg.staging_warehouse_id)
          : (d.staging_warehouse_id || ''),
      staging_override_reason: pkg.staging_override_reason ?? d.staging_override_reason ?? '',
    }));
  }

  private loadAllocationOptions(
    reliefrqstId: number,
    sourceWarehouseId: number | undefined,
    packageDetail: PackageDetailResponse | null,
    workspaceGeneration: number,
    sourceWarehouseRequestId?: number,
  ): void {
    this.operationsService.getAllocationOptions(reliefrqstId, sourceWarehouseId).pipe(
      catchError((error: HttpErrorResponse) => {
        if (
          !this.isCurrentWorkspaceGeneration(workspaceGeneration)
          || (sourceWarehouseRequestId !== undefined && this.latestSourceWarehouseRequestId !== sourceWarehouseRequestId)
        ) {
          return EMPTY;
        }
        this.optionsError.set(this.extractError(error, 'Failed to load allocation options.'));
        return of(null);
      }),
    ).subscribe({
      next: (options) => {
        if (
          !this.isCurrentWorkspaceGeneration(workspaceGeneration)
          || (sourceWarehouseRequestId !== undefined && this.latestSourceWarehouseRequestId !== sourceWarehouseRequestId)
        ) {
          return;
        }
        this.options.set(options);
        if (options) {
          this.initializeSelections(packageDetail, options);
        }
        this.loading.set(false);
      },
      error: () => {
        if (
          !this.isCurrentWorkspaceGeneration(workspaceGeneration)
          || (sourceWarehouseRequestId !== undefined && this.latestSourceWarehouseRequestId !== sourceWarehouseRequestId)
        ) {
          return;
        }
        this.loading.set(false);
        this.loadError.set('Failed to load fulfillment workspace.');
      },
    });
  }

  private beginWorkspaceGeneration(): number {
    this.latestWorkspaceGeneration += 1;
    this.latestSourceWarehouseRequestId = 0;
    this.latestItemWarehouseRequestIds = {};
    this.latestItemPreviewRequestIds = {};
    this.latestItemAddRequestIds = {};
    this.latestLegsRequestId = 0;
    this.latestRecommendationRequestId = 0;
    return this.latestWorkspaceGeneration;
  }

  private isCurrentWorkspaceGeneration(generation: number): boolean {
    return this.latestWorkspaceGeneration === generation;
  }

  private initializeSelections(
    detail: PackageDetailResponse | null,
    options: AllocationOptionsResponse,
  ): void {
    const committed = detail?.allocation?.allocation_lines ?? [];
    const nextSelections: Record<number, AllocationSelectionPayload[]> = {};
    const nextSeededWarehouses: Record<number, string> = {};
    const nextLoadedWarehouses: Record<number, number[]> = {};
    const nextOverrides: Record<number, string> = {};
    for (const item of options.items) {
      const itemCommitted = committed.filter((line) => line.item_id === item.item_id);
      if (itemCommitted.length) {
        nextSelections[item.item_id] = this.sortSelections(
          item.item_id,
          itemCommitted.map((line) => ({
            item_id: line.item_id,
            inventory_id: line.inventory_id,
            batch_id: line.batch_id,
            quantity: line.quantity,
            source_type: line.source_type,
            source_record_id: line.source_record_id ?? null,
            uom_code: line.uom_code ?? null,
          })),
        );
      } else {
        nextSelections[item.item_id] = item.suggested_allocations.map((line) => ({
          item_id: line.item_id,
          inventory_id: line.inventory_id,
          batch_id: line.batch_id,
          quantity: line.quantity,
          source_type: line.source_type,
          source_record_id: line.source_record_id ?? null,
          uom_code: line.uom_code ?? null,
        }));
      }

      const committedWarehouseIds = [...new Set(
        itemCommitted
          .map((line) => Number(line.inventory_id))
          .filter((warehouseId) => Number.isFinite(warehouseId) && warehouseId > 0),
      )];
      const seededWarehouseId = item.source_warehouse_id != null ? Number(item.source_warehouse_id) : 0;
      const hasSeed = Number.isFinite(seededWarehouseId) && seededWarehouseId > 0;

      if (committedWarehouseIds.length) {
        nextLoadedWarehouses[item.item_id] = committedWarehouseIds;
        // Rehydrate the per-item override so the draft's non-default warehouse is
        // visible on reload (fixes the handoff bug where the warehouse card was
        // hidden even though the committed allocation lines were preserved).
        const overrideWarehouseId = committedWarehouseIds.find(
          (warehouseId) => !hasSeed || warehouseId !== seededWarehouseId,
        );
        if (overrideWarehouseId != null) {
          nextOverrides[item.item_id] = String(overrideWarehouseId);
        }
        if (hasSeed) {
          // Capture the original seed so a later rollback via updateItemWarehouse
          // can restore the server-suggested warehouse even when the user
          // reopened a draft that already overrode it.
          nextSeededWarehouses[item.item_id] = String(seededWarehouseId);
        }
        continue;
      }

      if (hasSeed) {
        nextSeededWarehouses[item.item_id] = String(seededWarehouseId);
        nextLoadedWarehouses[item.item_id] = [seededWarehouseId];
      }
    }
    this.selectedRowsByItem.set(nextSelections);
    this.seededWarehousesByItem.set(nextSeededWarehouses);
    this.loadedWarehousesByItem.set(nextLoadedWarehouses);
    this.itemWarehouseOverrides.set(nextOverrides);
  }

  private getItemGroup(itemId: number): AllocationItemGroup | undefined {
    return this.options()?.items.find((entry) => entry.item_id === itemId);
  }

  private sortSelections(
    itemId: number,
    rows: AllocationSelectionPayload[],
  ): AllocationSelectionPayload[] {
    const group = this.getItemGroup(itemId);
    if (!group) {
      return [...rows];
    }
    const candidateOrder = new Map(
      group.candidates.map((candidate, index) => [this.selectionKey(candidate), index]),
    );
    return [...rows].sort(
      (left, right) =>
        (candidateOrder.get(this.selectionKey(left)) ?? Number.MAX_SAFE_INTEGER) -
        (candidateOrder.get(this.selectionKey(right)) ?? Number.MAX_SAFE_INTEGER),
    );
  }

  private selectionKey(
    value: Pick<AllocationSelectionPayload, 'inventory_id' | 'batch_id' | 'source_type' | 'source_record_id'>,
  ): string {
    return [
      String(value.inventory_id),
      String(value.batch_id),
      String(value.source_type || 'ON_HAND').toUpperCase(),
      String(value.source_record_id ?? ''),
    ].join('|');
  }

  private selectionSignature(rows: AllocationSelectionPayload[]): string {
    return rows
      .filter((row) => this.toNumber(row.quantity) > 0)
      .map((row) => ({
        key: this.selectionKey(row),
        quantity: this.formatQuantity(this.toNumber(row.quantity)),
      }))
      .sort((left, right) => left.key.localeCompare(right.key))
      .map((row) => `${row.key}:${row.quantity}`)
      .join(';');
  }

  private buildPackageDraftPayload(
    draftOverrides: Partial<Pick<WorkspaceDraft, 'fulfillment_mode' | 'staging_warehouse_id' | 'staging_override_reason'>> = {},
  ): PackageDraftPayload {
    const draft = { ...this.draft(), ...draftOverrides };
    const payload: PackageDraftPayload = {
      source_warehouse_id: this.getDerivedSourceWarehouseId(),
      to_inventory_id: draft.to_inventory_id ? Number(draft.to_inventory_id) : undefined,
      transport_mode: draft.transport_mode.trim() || undefined,
      comments_text: draft.comments_text.trim() || undefined,
      fulfillment_mode: draft.fulfillment_mode,
      staging_warehouse_id: draft.staging_warehouse_id ? Number(draft.staging_warehouse_id) : null,
      staging_override_reason: draft.staging_override_reason.trim() || null,
    };
    if (this.options() || Object.keys(this.selectedRowsByItem()).length) {
      payload.allocations = this.buildDraftAllocationSelections();
    }
    return payload;
  }

  private getSeededWarehouseIdForItem(itemId: number): string {
    const seededWarehouseId = this.seededWarehousesByItem()[itemId];
    if (seededWarehouseId) {
      return seededWarehouseId;
    }
    const currentItemWarehouseId = this.getItemGroup(itemId)?.source_warehouse_id;
    if (currentItemWarehouseId != null) {
      return String(currentItemWarehouseId);
    }
    return this.sourceWarehouseId();
  }

  private getDerivedSourceWarehouseId(): number | undefined {
    // Only send a package-level default when the user explicitly set one in the
    // draft. Do NOT fall back to the persisted package value or a value inferred
    // from per-item selections — per-item warehouse selection is first-class
    // and must not fabricate a default that the backend would persist.
    const explicitSourceWarehouseId = this.sanitizeInteger(this.draft().source_warehouse_id);
    return explicitSourceWarehouseId ? Number(explicitSourceWarehouseId) : undefined;
  }

  private buildDraftAllocationSelections(): AllocationSelectionPayload[] {
    return Object.values(this.selectedRowsByItem())
      .flat()
      .filter((row) => this.toNumber(row.quantity) > 0)
      .map((row) => ({
        ...row,
        quantity: this.formatQuantity(this.toNumber(row.quantity)),
      }));
  }

  private toNumber(value: string | number | null | undefined): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : 0;
    }
    const parsed = Number.parseFloat(String(value ?? '0'));
    return Number.isFinite(parsed) ? parsed : 0;
  }

  private toFixedQuantity(value: number): number {
    return Math.round(value * 10_000) / 10_000;
  }

  private formatQuantity(value: number): string {
    return this.toFixedQuantity(value).toFixed(4);
  }

  private sanitizeInteger(value: unknown): string {
    return String(value ?? '').replace(/[^\d]/g, '');
  }

  private extractError(error: HttpErrorResponse, fallback: string): string {
    const errorMap = error.error?.errors;
    if (errorMap && typeof errorMap === 'object') {
      const messages = Object.values(errorMap)
        .flatMap((value) => (Array.isArray(value) ? value : [value]))
        .map((value) => String(value ?? '').trim())
        .filter(Boolean);
      if (messages.length) {
        return messages[0];
      }
    }
    const directMessage = typeof error.error?.message === 'string' ? error.error.message.trim() : '';
    const fallbackDetail = typeof error.error?.detail === 'string' ? error.error.detail.trim() : '';
    return directMessage || fallbackDetail || fallback;
  }
}

export { OVERRIDE_REASON_OPTIONS };
