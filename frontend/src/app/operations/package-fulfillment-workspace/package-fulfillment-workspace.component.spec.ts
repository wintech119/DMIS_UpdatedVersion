import { Component, Input, signal } from '@angular/core';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { MatDialog } from '@angular/material/dialog';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { EMPTY, of, throwError } from 'rxjs';

import { PackageFulfillmentWorkspaceComponent } from './package-fulfillment-workspace.component';
import { FulfillmentPlanStepComponent } from './steps/fulfillment-plan-step.component';
import { FulfillmentDetailsStepComponent } from './steps/fulfillment-details-step.component';
import { FulfillmentReviewStepComponent } from './steps/fulfillment-review-step.component';
import { MasterDataService } from '../../master-data/services/master-data.service';
import { OperationsService } from '../services/operations.service';
import { OperationsWorkspaceStateService } from '../services/operations-workspace-state.service';
import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import {
  ConfirmDialogData,
  DmisConfirmDialogComponent,
} from '../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import {
  PackageAbandonDraftResponse,
  PackageDetailResponse,
  PackageLockConflict,
  PackageLockReleaseResponse,
  PackageSummary,
  RequestSummary,
} from '../models/operations.model';
import { AllocationItemGroup } from '../models/operations.model';
import { OpsSourceWarehousePickerComponent } from '../shared/ops-source-warehouse-picker.component';

// Stub replacements for the heavy fulfillment step children. They keep the parent
// template binding surface intact without dragging in their MasterDataService /
// MatForm deps, which are not relevant to the gating + force-takeover tests.

@Component({
  selector: 'app-fulfillment-plan-step',
  standalone: true,
  template: '<div class="stub-plan-step" data-testid="stub-plan-step"></div>',
})
class StubFulfillmentPlanStepComponent {
  @Input() readOnly = false;
}

@Component({
  selector: 'app-fulfillment-details-step',
  standalone: true,
  template: '<div class="stub-details-step" data-testid="stub-details-step"></div>',
})
class StubFulfillmentDetailsStepComponent {
  @Input() lockOperationalFields = false;
}

@Component({
  selector: 'app-fulfillment-review-step',
  standalone: true,
  template: '<div class="stub-review-step" data-testid="stub-review-step"></div>',
})
class StubFulfillmentReviewStepComponent {
  @Input() submissionErrors: readonly string[] = [];
  @Input() overrideApprovalHint: string | null = null;
  @Input() canApproveOverride = false;
}

describe('PackageFulfillmentWorkspaceComponent — lock conflict UX', () => {
  let fixture: ComponentFixture<PackageFulfillmentWorkspaceComponent>;
  let component: PackageFulfillmentWorkspaceComponent;
  let operationsService: jasmine.SpyObj<OperationsService>;
  let dialog: jasmine.SpyObj<MatDialog>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;
  let fakeAuth: {
    load: jasmine.Spy;
    hasPermission: jasmine.Spy;
    roles: ReturnType<typeof signal<readonly string[]>>;
    currentUserRef: ReturnType<typeof signal<string | null>>;
    permissions: ReturnType<typeof signal<readonly string[]>>;
  };

  const LOCK_CONFLICT: PackageLockConflict = {
    lock: 'Package is locked by another fulfillment actor.',
    lock_owner_user_id: 'other.user',
    lock_owner_role_code: 'LOGISTICS_MANAGER',
    lock_expires_at: '2026-04-07T16:00:00+00:00',
  };

  function buildPackageDetail(): PackageDetailResponse {
    const pkg: PackageSummary = {
      reliefpkg_id: 77001,
      tracking_no: 'PKG-00001',
      reliefrqst_id: 95009,
      agency_id: 1,
      eligible_event_id: null,
      source_warehouse_id: 9001,
      to_inventory_id: 9002,
      destination_warehouse_name: 'Destination WH',
      status_code: 'DRAFT',
      status_label: 'Draft',
      dispatch_dtime: null,
      received_dtime: null,
      transport_mode: 'TRUCK',
      comments_text: null,
      version_nbr: 1,
      execution_status: null,
      needs_list_id: null,
      compatibility_bridge: false,
      fulfillment_mode: 'DIRECT',
      staging_warehouse_id: null,
      staging_override_reason: null,
    };
    const request: RequestSummary = {
      reliefrqst_id: 95009,
      tracking_no: 'RQ-00001',
      agency_id: 1,
      agency_name: 'Parish Shelter',
      eligible_event_id: null,
      event_name: 'Flood Response',
      urgency_ind: 'H',
      status_code: 'APPROVED_FOR_FULFILLMENT',
      status_label: 'Approved',
      request_date: '2026-03-26',
      create_dtime: '2026-03-26T09:00:00Z',
      review_dtime: null,
      action_dtime: null,
      rqst_notes_text: null,
      review_notes_text: null,
      status_reason_desc: null,
      version_nbr: 1,
      item_count: 0,
      total_requested_qty: '0',
      total_issued_qty: '0',
      reliefpkg_id: 77001,
      package_tracking_no: 'PKG-00001',
      package_status: 'DRAFT',
      execution_status: null,
      needs_list_id: null,
      compatibility_bridge: false,
      request_mode: null,
      authority_context: null,
    };
    return {
      request,
      package: pkg,
      items: [],
      compatibility_only: false,
    };
  }

  function buildOverrideItemGroup(): AllocationItemGroup {
    return {
      item_id: 44,
      item_code: 'WATER-044',
      item_name: 'Portable Water Container',
      request_qty: '2',
      issue_qty: '0',
      remaining_qty: '2',
      urgency_ind: 'H',
      candidates: [
        {
          batch_id: 1001,
          inventory_id: 9001,
          item_id: 44,
          usable_qty: '10',
          reserved_qty: '0',
          available_qty: '10',
          source_type: 'ON_HAND',
          can_expire_flag: true,
          issuance_order: 'FEFO',
          batch_no: 'B-1001',
        },
        {
          batch_id: 1002,
          inventory_id: 9002,
          item_id: 44,
          usable_qty: '10',
          reserved_qty: '0',
          available_qty: '10',
          source_type: 'ON_HAND',
          can_expire_flag: true,
          issuance_order: 'FEFO',
          batch_no: 'B-1002',
        },
      ],
      suggested_allocations: [],
      remaining_after_suggestion: '0',
      can_expire_flag: true,
      issuance_order: 'FEFO',
      compliance_markers: ['allocation_order_override'],
      override_required: false,
      remaining_shortfall_qty: '0',
      continuation_recommended: false,
      alternate_warehouses: [],
      warehouse_cards: [],
    };
  }

  function buildApprovalRequiredOverrideItemGroup(): AllocationItemGroup {
    return {
      ...buildOverrideItemGroup(),
      compliance_markers: ['insufficient_on_hand_stock'],
      override_required: true,
    };
  }

  beforeEach(async () => {
    operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', [
      'getPackage',
      'getAllocationOptions',
      'releasePackageLock',
      'abandonDraft',
    ]);
    operationsService.getPackage.and.returnValue(EMPTY);
    operationsService.getAllocationOptions.and.returnValue(EMPTY);
    operationsService.releasePackageLock.and.returnValue(of<PackageLockReleaseResponse>({
      released: true,
      message: 'Package lock released.',
      package_id: 77001,
      package_no: 'PKG-00001',
      previous_lock_owner_user_id: 'other.user',
      previous_lock_owner_role_code: 'LOGISTICS_MANAGER',
      released_by_user_id: 'kemar.logistics',
      released_at: '2026-04-07T15:45:00+00:00',
      lock_status: 'RELEASED',
      lock_expires_at: '2026-04-07T15:45:00+00:00',
    }));

    dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    notifications = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showError',
      'showWarning',
      'showSuccess',
    ]);

    fakeAuth = {
      load: jasmine.createSpy('load'),
      hasPermission: jasmine.createSpy('hasPermission').and.returnValue(true),
      roles: signal<readonly string[]>(['LOGISTICS_MANAGER']),
      currentUserRef: signal<string | null>('kemar.logistics'),
      permissions: signal<readonly string[]>(['replenishment.needs_list.execute']),
    };

    await TestBed.configureTestingModule({
      imports: [
        NoopAnimationsModule,
        HttpClientTestingModule,
        PackageFulfillmentWorkspaceComponent,
      ],
      providers: [
        { provide: OperationsService, useValue: operationsService },
        { provide: MatDialog, useValue: dialog },
        { provide: DmisNotificationService, useValue: notifications },
        { provide: AuthRbacService, useValue: fakeAuth },
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: of(convertToParamMap({ reliefrqstId: '0' })),
          },
        },
        {
          provide: Router,
          useValue: jasmine.createSpyObj('Router', ['navigate']),
        },
      ],
    })
      .overrideComponent(PackageFulfillmentWorkspaceComponent, {
        remove: {
          imports: [
            FulfillmentPlanStepComponent,
            FulfillmentDetailsStepComponent,
            FulfillmentReviewStepComponent,
          ],
        },
        add: {
          imports: [
            StubFulfillmentPlanStepComponent,
            StubFulfillmentDetailsStepComponent,
            StubFulfillmentReviewStepComponent,
          ],
        },
      })
      .compileComponents();

    fixture = TestBed.createComponent(PackageFulfillmentWorkspaceComponent);
    component = fixture.componentInstance;
    // With reliefrqstId=0, the constructor skips store.load() so signals stay at their defaults.
    fixture.detectChanges();
  });

  describe('onForceReleaseLock', () => {
    it('opens DmisConfirmDialogComponent with truthful wording and no reason capture', () => {
      dialog.open.and.returnValue({
        afterClosed: () => of(false),
      } as ReturnType<MatDialog['open']>);

      component.onForceReleaseLock();

      expect(dialog.open).toHaveBeenCalledTimes(1);
      const [componentType, config] = dialog.open.calls.mostRecent().args as [
        typeof DmisConfirmDialogComponent,
        { data: ConfirmDialogData },
      ];
      expect(componentType).toBe(DmisConfirmDialogComponent);
      expect(config.data.title).toBe('Take over package');
      expect(config.data.message).toContain(
        'This will release the current package lock and let you continue.',
      );
      expect(config.data.message).toContain('The current lock owner will be notified.');
      expect(config.data.confirmLabel).toBe('Take over package');
      expect(config.data.confirmColor).toBe('warn');
      // Confirm dialog emits boolean, not a reason-capture payload.
      expect((config.data as unknown as { actionLabel?: string }).actionLabel).toBeUndefined();
    });

    it('calls releasePackageLock(force=true) when the user confirms', () => {
      dialog.open.and.returnValue({
        afterClosed: () => of(true),
      } as ReturnType<MatDialog['open']>);
      // The state service is provided at the component level, so access it via component.store.
      // It needs a reliefrqstId to dispatch the HTTP call.
      component.store.reliefrqstId.set(95009);

      component.onForceReleaseLock();

      expect(operationsService.releasePackageLock).toHaveBeenCalledTimes(1);
      const [reliefrqstId, force] = operationsService.releasePackageLock.calls.mostRecent().args;
      expect(reliefrqstId).toBe(95009);
      expect(force).toBe(true);
    });

    it('does nothing when the user cancels the confirmation dialog', () => {
      dialog.open.and.returnValue({
        afterClosed: () => of(false),
      } as ReturnType<MatDialog['open']>);

      component.onForceReleaseLock();

      expect(operationsService.releasePackageLock).not.toHaveBeenCalled();
      expect(notifications.showSuccess).not.toHaveBeenCalled();
    });
  });

  describe('onReleaseOwnLock', () => {
    it('calls releasePackageLock(force=false) without opening a confirmation dialog', () => {
      component.store.reliefrqstId.set(95009);

      component.onReleaseOwnLock();

      expect(dialog.open).not.toHaveBeenCalled();
      expect(operationsService.releasePackageLock).toHaveBeenCalledTimes(1);
      const [reliefrqstId, force] = operationsService.releasePackageLock.calls.mostRecent().args;
      expect(reliefrqstId).toBe(95009);
      expect(force).toBe(false);
    });
  });

  describe('template gating under lock conflict', () => {
    function populatePackageDetail(): OperationsWorkspaceStateService {
      const store = component.store;
      store.reliefrqstId.set(95009);
      store.packageDetail.set(buildPackageDetail());
      return store;
    }

    it('renders the editable stepper and step tracker when there is no lock conflict', () => {
      const store = populatePackageDetail();
      store.lockConflict.set(null);
      fixture.detectChanges();

      const host = fixture.nativeElement as HTMLElement;
      expect(host.querySelector('mat-stepper')).not.toBeNull();
      expect(host.querySelector('dmis-step-tracker')).not.toBeNull();
      expect(host.querySelector('app-ops-package-lock-state')).toBeNull();
    });

    it('renders the lock blocker card and hides the editable stepper when a lock conflict is active', () => {
      const store = populatePackageDetail();
      store.lockConflict.set(LOCK_CONFLICT);
      fixture.detectChanges();

      const host = fixture.nativeElement as HTMLElement;
      expect(host.querySelector('app-ops-package-lock-state')).not.toBeNull();
      expect(host.querySelector('mat-stepper')).toBeNull();
      expect(host.querySelector('dmis-step-tracker')).toBeNull();
    });

    it('restores the editable stepper once the lock conflict is cleared', () => {
      const store = populatePackageDetail();
      store.lockConflict.set(LOCK_CONFLICT);
      fixture.detectChanges();
      expect((fixture.nativeElement as HTMLElement).querySelector('mat-stepper')).toBeNull();

      store.lockConflict.set(null);
      fixture.detectChanges();

      const host = fixture.nativeElement as HTMLElement;
      expect(host.querySelector('app-ops-package-lock-state')).toBeNull();
      expect(host.querySelector('mat-stepper')).not.toBeNull();
    });
  });

  describe('override workflow gating', () => {
    function populateOrderOverrideSelection(): void {
      component.store.reliefrqstId.set(95009);
      component.store.packageDetail.set(buildPackageDetail());
      component.store.options.set({
        request: { reliefrqst_id: 95009 } as unknown as RequestSummary,
        items: [buildOverrideItemGroup()],
      });
      component.store.selectedRowsByItem.set({
        44: [
          {
            item_id: 44,
            inventory_id: 9002,
            batch_id: 1002,
            quantity: '2',
            source_type: 'ON_HAND',
            source_record_id: null,
            uom_code: 'EA',
          },
        ],
      });
      component.store.patchDraft({
        override_reason_code: 'FEFO_BYPASS',
        override_note: 'Needs manager approval',
      });
    }

    function populateApprovalRequiredSelection(): void {
      component.store.reliefrqstId.set(95009);
      component.store.packageDetail.set(buildPackageDetail());
      component.store.options.set({
        request: { reliefrqst_id: 95009 } as unknown as RequestSummary,
        items: [buildApprovalRequiredOverrideItemGroup()],
      });
      component.store.selectedRowsByItem.set({
        44: [
          {
            item_id: 44,
            inventory_id: 9002,
            batch_id: 1002,
            quantity: '2',
            source_type: 'ON_HAND',
            source_record_id: null,
            uom_code: 'EA',
          },
        ],
      });
      component.store.patchDraft({
        override_reason_code: 'STOCK_EXCEPTION',
        override_note: 'Manager-authorized fulfillment override',
      });
    }

    it('lets logistics officers submit approval-required override requests', () => {
      fakeAuth.roles.set(['LOGISTICS_OFFICER']);
      populateApprovalRequiredSelection();

      expect(component.canSubmitOverrideRequest()).toBeTrue();
      expect(component.canCommitManagerOverrideDirectly()).toBeFalse();
      expect(component.commitActionDisabled()).toBeFalse();
      expect(component.commitActionLabel()).toBe('Submit Override For Approval');
    });

    it('does not require an approval note for order-only bypasses', () => {
      populateOrderOverrideSelection();
      component.store.patchDraft({ override_note: '' });

      const errors = (component as unknown as { collectDetailErrors(): string[] }).collectDetailErrors();

      expect(errors).toEqual([]);
    });

    it('lets logistics managers commit approval-required overrides directly', () => {
      fakeAuth.roles.set(['LOGISTICS_MANAGER']);
      populateApprovalRequiredSelection();

      expect(component.canSubmitOverrideRequest()).toBeFalse();
      expect(component.canCommitManagerOverrideDirectly()).toBeTrue();
      expect(component.commitActionDisabled()).toBeFalse();
      expect(component.commitActionLabel()).toBe('Commit Reservation');
      expect(component.overrideApprovalHint()).toContain('you can record the override details and commit the reservation directly');
    });

    it('lets logistics managers commit order-only bypasses without approval', () => {
      fakeAuth.roles.set(['LOGISTICS_MANAGER']);
      populateOrderOverrideSelection();

      expect(component.commitActionDisabled()).toBeFalse();
      expect(component.commitActionLabel()).toBe('Commit Reservation');
      expect(component.overrideApprovalHint()).toContain('Record the override reason before committing');
    });
  });

  describe('cancelFulfillment (non-terminal abandon)', () => {
    const RELIEFRQST_ID = 95009;
    const RELIEFPKG_ID = 77001;

    function setupAbandonable(): void {
      component.store.reliefrqstId.set(RELIEFRQST_ID);
      component.reliefrqstId.set(RELIEFRQST_ID);
      component.store.reliefpkgId.set(RELIEFPKG_ID);
      component.store.packageDetail.set(buildPackageDetail());
    }

    function setupCommittedAbandonable(): void {
      const detail: PackageDetailResponse = {
        ...buildPackageDetail(),
        package: {
          ...buildPackageDetail().package!,
          status_code: 'COMMITTED',
          status_label: 'Committed',
        },
        allocation: {
          allocation_lines: [
            {
              item_id: 44,
              inventory_id: 9001,
              batch_id: 1001,
              quantity: '10.0000',
              source_type: 'ON_HAND',
            },
          ],
          reserved_stock_summary: {
            line_count: 1,
            total_qty: '10.0000',
          },
          waybill_no: null,
        },
      };
      component.store.reliefrqstId.set(RELIEFRQST_ID);
      component.reliefrqstId.set(RELIEFRQST_ID);
      component.store.reliefpkgId.set(RELIEFPKG_ID);
      component.store.packageDetail.set(detail);
    }

    function setupReadyForDispatchPackage(): void {
      const detail: PackageDetailResponse = {
        ...buildPackageDetail(),
        package: {
          ...buildPackageDetail().package!,
          status_code: 'P',
          status_label: 'Pending',
          execution_status: 'READY_FOR_DISPATCH',
        },
        allocation: {
          allocation_lines: [
            {
              item_id: 44,
              inventory_id: 9001,
              batch_id: 1001,
              quantity: '10.0000',
              source_type: 'ON_HAND',
            },
          ],
          reserved_stock_summary: {
            line_count: 1,
            total_qty: '10.0000',
          },
          waybill_no: null,
        },
      };
      component.store.reliefrqstId.set(RELIEFRQST_ID);
      component.reliefrqstId.set(RELIEFRQST_ID);
      component.store.reliefpkgId.set(RELIEFPKG_ID);
      component.store.packageDetail.set(detail);
    }

    function successResponse(): PackageAbandonDraftResponse {
      return {
        reliefpkg_id: RELIEFPKG_ID,
        status: 'DRAFT',
        status_code: 'DRAFT',
        abandoned: true,
        request_status: 'APPROVED_FOR_FULFILLMENT',
        reason: 'Wrong warehouse pre-selection',
        previous_status_code: 'COMMITTED',
        released: { line_count: 2, total_qty: '150.0000' },
      };
    }

    it('opens DmisConfirmDialogComponent with destructive copy and a clear revert warning', () => {
      setupAbandonable();
      dialog.open.and.returnValue({
        afterClosed: () => of(false),
      } as ReturnType<MatDialog['open']>);

      component.cancelFulfillment();

      expect(dialog.open).toHaveBeenCalledTimes(1);
      const [componentType, config] = dialog.open.calls.mostRecent().args as [
        typeof DmisConfirmDialogComponent,
        { data: ConfirmDialogData },
      ];
      expect(componentType).toBe(DmisConfirmDialogComponent);
      expect(config.data.title).toBe('Cancel this fulfillment?');
      expect(config.data.message).toContain('releases all reserved stock');
      expect(config.data.message).toContain('another officer can start fresh');
      expect(config.data.confirmColor).toBe('warn');
    });

    it('does not call abandonDraft when the confirmation dialog is cancelled', () => {
      setupAbandonable();
      dialog.open.and.returnValue({
        afterClosed: () => of(false),
      } as ReturnType<MatDialog['open']>);

      component.cancelFulfillment();

      expect(operationsService.abandonDraft).not.toHaveBeenCalled();
      expect(notifications.showSuccess).not.toHaveBeenCalled();
    });

    it('disables abandon once a fulfillment is already committed for dispatch', () => {
      setupCommittedAbandonable();
      dialog.open.and.returnValue({
        afterClosed: () => of(false),
      } as ReturnType<MatDialog['open']>);

      expect(component.store.hasCommittedAllocation()).toBeTrue();
      expect(component.canCancel()).toBeFalse();

      component.cancelFulfillment();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('disables abandon for ready-for-dispatch execution states even when the legacy package code is pending', () => {
      setupReadyForDispatchPackage();

      expect(component.canCancel()).toBeFalse();
    });

    it('calls operationsService.abandonDraft with the package id when confirmed', () => {
      setupAbandonable();
      dialog.open.and.returnValue({
        afterClosed: () => of(true),
      } as ReturnType<MatDialog['open']>);
      operationsService.abandonDraft.and.returnValue(of(successResponse()));

      component.cancelFulfillment();

      expect(operationsService.abandonDraft).toHaveBeenCalledTimes(1);
      expect(operationsService.abandonDraft).toHaveBeenCalledWith(RELIEFPKG_ID);
    });

    it('shows a success toast and navigates back to the relief request on a successful abandon', () => {
      setupAbandonable();
      dialog.open.and.returnValue({
        afterClosed: () => of(true),
      } as ReturnType<MatDialog['open']>);
      operationsService.abandonDraft.and.returnValue(of(successResponse()));

      const router = TestBed.inject(Router) as jasmine.SpyObj<Router>;

      component.cancelFulfillment();

      expect(notifications.showSuccess).toHaveBeenCalledTimes(1);
      expect(notifications.showSuccess.calls.mostRecent().args[0]).toContain(
        'Fulfillment released',
      );
      expect(router.navigate).toHaveBeenCalledWith([
        '/operations/relief-requests',
        RELIEFRQST_ID,
      ]);
    });

    it('shows an error toast and does not navigate when abandonDraft fails', () => {
      setupAbandonable();
      dialog.open.and.returnValue({
        afterClosed: () => of(true),
      } as ReturnType<MatDialog['open']>);
      operationsService.abandonDraft.and.returnValue(
        throwError(
          () =>
            new HttpErrorResponse({
              status: 400,
              error: { errors: { abandon: 'This fulfillment can no longer be abandoned.' } },
            }),
        ),
      );

      const router = TestBed.inject(Router) as jasmine.SpyObj<Router>;

      component.cancelFulfillment();

      expect(notifications.showError).toHaveBeenCalledTimes(1);
      expect(router.navigate).not.toHaveBeenCalled();
    });

    it('does nothing when canCancel is false (no package loaded)', () => {
      // Intentionally leave reliefpkgId unset → canCancel() returns false.
      component.store.reliefpkgId.set(0);

      component.cancelFulfillment();

      expect(dialog.open).not.toHaveBeenCalled();
      expect(operationsService.abandonDraft).not.toHaveBeenCalled();
    });
  });
});

describe('FulfillmentPlanStepComponent source warehouse recovery', () => {
  let fixture: ComponentFixture<FulfillmentPlanStepComponent>;
  let updateSourceWarehouse: jasmine.Spy;
  let lookup: jasmine.Spy;
  let storeStub: {
    options: ReturnType<typeof signal>;
    optionsError: ReturnType<typeof signal>;
    requestAvailabilityIssue: ReturnType<typeof signal>;
    switching: ReturnType<typeof signal>;
    loading: ReturnType<typeof signal>;
    submitting: ReturnType<typeof signal>;
    sourceWarehouseId: ReturnType<typeof signal>;
    itemWarehouseOverrides: ReturnType<typeof signal>;
    updateSourceWarehouse: jasmine.Spy;
  };

  beforeEach(async () => {
    TestBed.resetTestingModule();

    updateSourceWarehouse = jasmine.createSpy('updateSourceWarehouse');
    lookup = jasmine.createSpy('lookup').and.returnValue(of([
      { value: 9001, label: 'Primary Warehouse' },
      { value: 9002, label: 'Secondary Warehouse' },
    ]));

    storeStub = {
      options: signal(null),
      optionsError: signal('source_warehouse_id is required when no needs-list compatibility bridge exists.'),
      requestAvailabilityIssue: signal({
        kind: 'missing-warehouse' as const,
        scope: 'request' as const,
        detail: 'source_warehouse_id is required when no needs-list compatibility bridge exists.',
      }),
      switching: signal(false),
      loading: signal(false),
      submitting: signal(false),
      sourceWarehouseId: signal(''),
      itemWarehouseOverrides: signal({}),
      updateSourceWarehouse,
    };

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, FulfillmentPlanStepComponent],
      providers: [
        { provide: OperationsWorkspaceStateService, useValue: storeStub },
        {
          provide: MasterDataService,
          useValue: { lookup },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(FulfillmentPlanStepComponent);
    fixture.detectChanges();
  });

  it('renders the warehouse picker when allocation loading is blocked by a missing source warehouse', () => {
    expect(lookup).toHaveBeenCalledWith('warehouses');

    const picker = fixture.debugElement.query(By.directive(OpsSourceWarehousePickerComponent));
    expect(picker).not.toBeNull();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain(
      'Warehouse setup is needed before stock can be reserved',
    );
  });

  it('forwards the selected warehouse back to the workspace state service', () => {
    const picker = fixture.debugElement.query(By.directive(OpsSourceWarehousePickerComponent));
    const pickerComponent = picker.componentInstance as OpsSourceWarehousePickerComponent;

    pickerComponent.warehouseChange.emit('9002');

    expect(updateSourceWarehouse).toHaveBeenCalledWith('9002');
  });

  it('keeps the picker hidden when the request is not blocked by the missing-warehouse state', () => {
    storeStub.optionsError.set(null);
    storeStub.requestAvailabilityIssue.set(null);
    storeStub.sourceWarehouseId.set('9001');

    fixture.detectChanges();

    expect(fixture.debugElement.query(By.directive(OpsSourceWarehousePickerComponent))).toBeNull();
  });
});
