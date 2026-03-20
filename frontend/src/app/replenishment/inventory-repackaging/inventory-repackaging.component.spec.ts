import { of, throwError } from 'rxjs';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { LookupItem } from '../../master-data/models/master-data.models';
import { MasterDataService } from '../../master-data/services/master-data.service';
import { InventoryRepackagingComponent } from './inventory-repackaging.component';
import { DmisNotificationService } from '../services/notification.service';
import { ReplenishmentService } from '../services/replenishment.service';

describe('InventoryRepackagingComponent', () => {
  function setup(options?: {
    routeParams?: Record<string, string>;
    listError?: unknown;
    createError?: unknown;
  }) {
    const masterDataService = jasmine.createSpyObj<MasterDataService>('MasterDataService', [
      'lookup',
      'get',
    ]);
    const replenishmentService = jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', [
      'getAllWarehouses',
      'listRepackagingTransactions',
      'getRepackagingTransaction',
      'createRepackagingTransaction',
    ]);
    const notifications = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showSuccess',
      'showWarning',
      'showError',
    ]);
    const router = jasmine.createSpyObj<Router>('Router', ['navigate']);

    const lookupItems: LookupItem[] = [
      {
        value: 101,
        label: 'Water purification tablet',
        item_code: 'WTAB-100',
        item_name: 'Water purification tablet',
      },
    ];

    masterDataService.lookup.and.returnValue(of(lookupItems));
    masterDataService.get.and.returnValue(of({
      record: {
        item_id: 101,
        item_code: 'WTAB-100',
        item_name: 'Water purification tablet',
        default_uom_code: 'EA',
        is_batched_flag: true,
        uom_options: [
          { uom_code: 'EA', conversion_factor: 1, is_default: true },
          { uom_code: 'PACK', conversion_factor: 10, is_default: false },
        ],
      },
      warnings: [],
    }));

    replenishmentService.getAllWarehouses.and.returnValue(of([
      { warehouse_id: 7, warehouse_name: 'S07 TEST MAIN HUB' },
    ]));
    if (options?.listError) {
      replenishmentService.listRepackagingTransactions.and.returnValue(throwError(() => options.listError));
    } else {
      replenishmentService.listRepackagingTransactions.and.returnValue(of({
        results: [],
        count: 0,
        limit: 8,
        offset: 0,
        warnings: [],
      }));
    }
    replenishmentService.getRepackagingTransaction.and.returnValue(of({
      record: {
        repackaging_id: 33,
        warehouse_id: 7,
        warehouse_name: 'S07 TEST MAIN HUB',
        item_id: 101,
        item_code: 'WTAB-100',
        item_name: 'Water purification tablet',
        batch_id: 18,
        batch_or_lot: 'LOT-18',
        expiry_date: null,
        source_uom_code: 'EA',
        source_qty: 10,
        target_uom_code: 'PACK',
        target_qty: 1,
        equivalent_default_qty: 10,
        source_conversion_factor: 1,
        target_conversion_factor: 10,
        reason_code: 'SPLIT_EACHES',
        note_text: 'Split for field kits',
        audit_metadata: {
          created_by_id: 'inventory.clerk',
          created_at: '2026-03-20T14:00:00Z',
          audit_row_count: 1,
        },
        audit_rows: [
          {
            repackaging_audit_id: 1,
            action_type: 'CREATE',
            before_state: null,
            after_state: {},
            reason_code: 'SPLIT_EACHES',
            note_text: 'Split for field kits',
            actor_id: 'inventory.clerk',
            action_dtime: '2026-03-20T14:00:00Z',
          },
        ],
      },
      warnings: [],
    }));
    if (options?.createError) {
      replenishmentService.createRepackagingTransaction.and.returnValue(throwError(() => options.createError));
    } else {
      replenishmentService.createRepackagingTransaction.and.returnValue(of({
        record: {
          repackaging_id: 33,
          warehouse_id: 7,
          warehouse_name: 'S07 TEST MAIN HUB',
          item_id: 101,
          item_code: 'WTAB-100',
          item_name: 'Water purification tablet',
          batch_id: 18,
          batch_or_lot: 'LOT-18',
          expiry_date: null,
          source_uom_code: 'EA',
          source_qty: 10,
          target_uom_code: 'PACK',
          target_qty: 1,
          equivalent_default_qty: 10,
          source_conversion_factor: 1,
          target_conversion_factor: 10,
          reason_code: 'SPLIT_EACHES',
          note_text: 'Split for field kits',
          audit_metadata: {
            created_by_id: 'inventory.clerk',
            created_at: '2026-03-20T14:00:00Z',
            audit_row_count: 1,
          },
          audit_rows: [],
        },
        warnings: [],
      }));
    }

    TestBed.configureTestingModule({
      imports: [InventoryRepackagingComponent, NoopAnimationsModule],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: of(convertToParamMap(options?.routeParams ?? {})),
          },
        },
        { provide: Router, useValue: router },
        { provide: MasterDataService, useValue: masterDataService },
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DmisNotificationService, useValue: notifications },
      ],
    });

    const fixture = TestBed.createComponent(InventoryRepackagingComponent);
    fixture.detectChanges();

    return {
      fixture,
      component: fixture.componentInstance,
      replenishmentService,
      notifications,
      router,
    };
  }

  function selectPrimaryItem(component: InventoryRepackagingComponent): void {
    component.onItemSelected({
      itemId: 101,
      itemCode: 'WTAB-100',
      itemName: 'Water purification tablet',
      label: 'WTAB-100 - Water purification tablet',
    });
  }

  it('computes the preview from the selected item UOM setup', () => {
    const { component } = setup();

    component.form.patchValue({ warehouse_id: 7 });
    selectPrimaryItem(component);
    component.form.patchValue({
      source_uom_code: 'EA',
      source_qty: 10,
      target_uom_code: 'PACK',
      reason_code: 'SPLIT_EACHES',
      batch_or_lot: 'LOT-18',
    });

    expect(component.preview()).toEqual(jasmine.objectContaining({
      equivalentDefaultQty: 10,
      targetQty: 1,
    }));
  });

  it('renders backend validation details clearly for insufficient stock', () => {
    const { component, fixture, notifications } = setup({
      createError: {
        status: 400,
        error: {
          detail: 'Source stock is insufficient for the requested repackaging quantity.',
          errors: {
            insufficient_stock: {
              available_default_qty: 8,
              required_default_qty: 999999,
            },
          },
        },
      },
    });

    component.form.patchValue({ warehouse_id: 7 });
    selectPrimaryItem(component);
    component.form.patchValue({
      source_uom_code: 'EA',
      source_qty: 999999,
      target_uom_code: 'PACK',
      reason_code: 'SPLIT_EACHES',
      batch_or_lot: 'LOT-18',
    });

    component.onSubmit();
    fixture.detectChanges();

    expect(component.submitError()?.title).toBe('Source stock is insufficient for the requested repackaging quantity.');
    expect(component.submitError()?.details).toContain(
      'Insufficient stock: available default qty 8, required default qty 999999.'
    );
    expect(fixture.nativeElement.textContent).toContain('available default qty 8');
    expect(notifications.showError).toHaveBeenCalledWith('Source stock is insufficient for the requested repackaging quantity.');
  });

  it('submits a valid create-only repackaging flow and routes to the persisted detail', () => {
    const { component, replenishmentService, router, notifications } = setup();

    component.form.patchValue({ warehouse_id: 7 });
    selectPrimaryItem(component);
    component.form.patchValue({
      source_uom_code: 'EA',
      source_qty: 10,
      target_uom_code: 'PACK',
      reason_code: 'SPLIT_EACHES',
      batch_or_lot: 'LOT-18',
      note_text: 'Split for field kits',
    });

    component.onSubmit();

    expect(replenishmentService.createRepackagingTransaction).toHaveBeenCalledWith(jasmine.objectContaining({
      warehouse_id: 7,
      item_id: 101,
      source_uom_code: 'EA',
      target_uom_code: 'PACK',
      target_qty: 1,
      equivalent_default_qty: 10,
    }));
    expect(router.navigate).toHaveBeenCalledWith(['/replenishment/inventory/repackaging', 33]);
    expect(notifications.showSuccess).toHaveBeenCalledWith('Repackaging transaction saved.');
  });

  it('shows a permission error when the backend rejects repackaging history access', () => {
    const { component, fixture } = setup({
      listError: { status: 403 },
    });

    expect(component.accessDenied()).toBe('You do not have permission to view repackaging history for this scope.');
    expect(fixture.nativeElement.textContent).toContain('Repackaging Access Blocked');
  });
});
