import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { EMPTY, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import {
  AllocationCandidate,
  AllocationCommitPayload,
  AllocationItemGroup,
  AllocationOptionsResponse,
  AllocationSelectionPayload,
  OVERRIDE_REASON_OPTIONS,
  OverrideApprovalPayload,
  PackageDetailResponse,
  WaybillResponse,
  AllocationMethod,
} from '../models/operations.model';
import { OperationsService } from './operations.service';

interface WorkspaceDraft {
  source_warehouse_id: string;
  to_inventory_id: string;
  transport_mode: string;
  comments_text: string;
  override_reason_code: string;
  override_note: string;
}

interface LoadResult {
  packageDetail: PackageDetailResponse | null;
  options: AllocationOptionsResponse | null;
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
};

@Injectable()
export class OperationsWorkspaceStateService {
  private readonly operationsService = inject(OperationsService);
  private latestSourceWarehouseRequestId = 0;

  readonly reliefrqstId = signal(0);
  readonly reliefpkgId = signal(0);
  readonly packageDetail = signal<PackageDetailResponse | null>(null);
  readonly options = signal<AllocationOptionsResponse | null>(null);
  readonly waybill = signal<WaybillResponse | null>(null);

  readonly loading = signal(false);
  readonly waybillLoading = signal(false);
  readonly submitting = signal(false);

  readonly loadError = signal<string | null>(null);
  readonly optionsError = signal<string | null>(null);
  readonly waybillError = signal<string | null>(null);

  readonly draft = signal<WorkspaceDraft>({ ...DEFAULT_DRAFT });
  readonly selectedRowsByItem = signal<Record<number, AllocationSelectionPayload[]>>({});

  /** Per-item warehouse overrides: item_id -> warehouse_id string. */
  readonly itemWarehouseOverrides = signal<Record<number, string>>({});

  /** True while a per-item warehouse switch is loading (does NOT clear existing data). */
  readonly switching = signal(false);

  /** Number of items using a warehouse different from the default. */
  readonly overrideCount = computed(() => Object.keys(this.itemWarehouseOverrides()).length);

  readonly selectedLineCount = computed(() =>
    Object.values(this.selectedRowsByItem()).reduce((sum, rows) => sum + rows.length, 0),
  );

  readonly hasCommittedAllocation = computed(() => {
    const alloc = this.packageDetail()?.allocation;
    return (alloc?.allocation_lines?.length ?? 0) > 0;
  });

  readonly hasPendingOverride = computed(() => {
    const pkg = this.packageDetail()?.package;
    const execStatus = String(pkg?.execution_status ?? '').trim().toUpperCase();
    return execStatus === 'PENDING_OVERRIDE_APPROVAL';
  });

  readonly hasWaybill = computed(() => !!(this.waybill()?.waybill_no));

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

  /** Returns the effective warehouse for a given item (override if set, else default). */
  effectiveWarehouseForItem(itemId: number): string {
    return this.itemWarehouseOverrides()[itemId] ?? this.sourceWarehouseId();
  }

  // ── Loading ────────────────────────────────────────────────────

  load(reliefrqstId: number, loadOptions = true): void {
    this.reliefrqstId.set(reliefrqstId);
    this.loading.set(true);
    this.loadError.set(null);
    this.optionsError.set(null);
    this.packageDetail.set(null);
    this.options.set(null);
    this.waybill.set(null);
    this.waybillError.set(null);
    this.selectedRowsByItem.set({});
    this.itemWarehouseOverrides.set({});
    this.draft.set({ ...DEFAULT_DRAFT });

    this.operationsService.getPackage(reliefrqstId).pipe(
      catchError((error: HttpErrorResponse) => {
        this.loadError.set(this.extractError(error, 'Failed to load package details.'));
        this.loading.set(false);
        return EMPTY;
      }),
    ).subscribe({
      next: (packageDetail) => {
        this.packageDetail.set(packageDetail);
        if (packageDetail) {
          this.hydrateDraft(packageDetail);
          if (packageDetail.package) {
            this.reliefpkgId.set(packageDetail.package.reliefpkg_id);
          }
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
        );
      },
      error: () => {
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
    this.operationsService.getPackage(reliefrqstId).subscribe({
      next: (detail) => {
        this.packageDetail.set(detail);
        this.hydrateDraft(detail);
        if (detail.package) {
          this.reliefpkgId.set(detail.package.reliefpkg_id);
        }
      },
      error: (error: HttpErrorResponse) => {
        this.loadError.set(this.extractError(error, 'Failed to refresh package status.'));
      },
    });
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
    const prevOptions = this.options();
    const prevSelections = this.selectedRowsByItem();

    this.patchDraft({ source_warehouse_id: normalizedSourceWarehouseId });

    // Changing the default warehouse resets all per-item overrides.
    this.itemWarehouseOverrides.set({});

    this.loading.set(true);
    this.optionsError.set(null);
    this.options.set(null);
    this.selectedRowsByItem.set({});
    const requestId = ++this.latestSourceWarehouseRequestId;

    const draft = this.draft();
    this.operationsService.savePackageDraft(reliefrqstId, {
      source_warehouse_id: normalizedSourceWarehouseId ? Number(normalizedSourceWarehouseId) : undefined,
      to_inventory_id: draft.to_inventory_id ? Number(draft.to_inventory_id) : undefined,
      transport_mode: draft.transport_mode.trim() || undefined,
      comments_text: draft.comments_text.trim() || undefined,
    }).subscribe({
      next: (detail) => {
        if (this.latestSourceWarehouseRequestId !== requestId) {
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
          requestId,
        );
      },
      error: (error: HttpErrorResponse) => {
        if (this.latestSourceWarehouseRequestId !== requestId) {
          return;
        }
        this.patchDraft({ source_warehouse_id: prevDraft.source_warehouse_id });
        this.itemWarehouseOverrides.set(prevOverrides);
        this.options.set(prevOptions);
        this.selectedRowsByItem.set(prevSelections);
        this.loading.set(false);
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
    const defaultWarehouseId = this.sourceWarehouseId();
    const reliefrqstId = this.reliefrqstId();
    if (!reliefrqstId || !normalizedWarehouseId) {
      return;
    }
    const prevOverrides = this.itemWarehouseOverrides();
    const prevSelections = this.selectedRowsByItem();

    this.switching.set(true);

    this.operationsService.getItemAllocationOptions(
      reliefrqstId,
      itemId,
      Number(normalizedWarehouseId),
    ).subscribe({
      next: (itemGroup) => {
        const nextOverrides = { ...prevOverrides };
        if (normalizedWarehouseId === defaultWarehouseId) {
          delete nextOverrides[itemId];
        } else {
          nextOverrides[itemId] = normalizedWarehouseId;
        }
        this.itemWarehouseOverrides.set(nextOverrides);
        this.optionsError.set(null);

        const currentOptions = this.options();
        if (currentOptions) {
          const updatedItems = currentOptions.items.map((existing) =>
            existing.item_id === itemId ? itemGroup : existing,
          );
          this.options.set({ ...currentOptions, items: updatedItems });
        }
        this.selectedRowsByItem.set({
          ...prevSelections,
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
        this.switching.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.itemWarehouseOverrides.set(prevOverrides);
        this.selectedRowsByItem.set(prevSelections);
        this.optionsError.set(this.extractError(error, 'Failed to load stock for this item.'));
        this.switching.set(false);
      },
    });
  }

  /** Clear all per-item warehouse overrides and reload with the default warehouse. */
  clearWarehouseOverrides(): void {
    this.itemWarehouseOverrides.set({});
    const reliefrqstId = this.reliefrqstId();
    const sourceWarehouseId = this.sourceWarehouseId();
    if (reliefrqstId && sourceWarehouseId) {
      this.updateSourceWarehouse(sourceWarehouseId);
    }
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
  }

  clearItemSelection(itemId: number): void {
    const next = { ...this.selectedRowsByItem() };
    next[itemId] = [];
    this.selectedRowsByItem.set(next);
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
    const allocations = Object.values(this.selectedRowsByItem())
      .flat()
      .filter((row) => this.toNumber(row.quantity) > 0)
      .map((row) => ({
        ...row,
        quantity: this.formatQuantity(this.toNumber(row.quantity)),
      }));

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

    const draft = this.draft();
    const payload: AllocationCommitPayload = {
      source_warehouse_id: draft.source_warehouse_id ? Number(draft.source_warehouse_id) : undefined,
      allocations,
      to_inventory_id: draft.to_inventory_id ? Number(draft.to_inventory_id) : undefined,
      transport_mode: draft.transport_mode.trim() || undefined,
      comments_text: draft.comments_text.trim() || undefined,
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
    this.draft.update((d) => ({
      ...d,
      source_warehouse_id: d.source_warehouse_id || (pkg.source_warehouse_id != null ? String(pkg.source_warehouse_id) : ''),
      to_inventory_id: d.to_inventory_id || (pkg.to_inventory_id != null ? String(pkg.to_inventory_id) : ''),
      transport_mode: d.transport_mode || pkg.transport_mode || '',
      comments_text: d.comments_text || pkg.comments_text || '',
    }));
  }

  private loadAllocationOptions(
    reliefrqstId: number,
    sourceWarehouseId: number | undefined,
    packageDetail: PackageDetailResponse | null,
    sourceWarehouseRequestId?: number,
  ): void {
    this.operationsService.getAllocationOptions(reliefrqstId, sourceWarehouseId).pipe(
      catchError((error: HttpErrorResponse) => {
        if (sourceWarehouseRequestId !== undefined && this.latestSourceWarehouseRequestId !== sourceWarehouseRequestId) {
          return EMPTY;
        }
        this.optionsError.set(this.extractError(error, 'Failed to load allocation options.'));
        return of(null);
      }),
    ).subscribe({
      next: (options) => {
        if (sourceWarehouseRequestId !== undefined && this.latestSourceWarehouseRequestId !== sourceWarehouseRequestId) {
          return;
        }
        this.options.set(options);
        if (options) {
          this.initializeSelections(packageDetail, options);
        }
        this.loading.set(false);
      },
      error: () => {
        if (sourceWarehouseRequestId !== undefined && this.latestSourceWarehouseRequestId !== sourceWarehouseRequestId) {
          return;
        }
        this.loading.set(false);
        this.loadError.set('Failed to load fulfillment workspace.');
      },
    });
  }

  private initializeSelections(
    detail: PackageDetailResponse | null,
    options: AllocationOptionsResponse,
  ): void {
    const committed = detail?.allocation?.allocation_lines ?? [];
    const nextSelections: Record<number, AllocationSelectionPayload[]> = {};
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
        continue;
      }
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
    this.selectedRowsByItem.set(nextSelections);
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
