import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';

import { UomRepackagingComponent } from './uom-repackaging.component';
import { MasterDataService } from '../../master-data/services/master-data.service';
import { AuthRbacService } from '../services/auth-rbac.service';
import { DmisNotificationService } from '../services/notification.service';
import {
  ReplenishmentService,
  UomRepackagingMutationResponse,
  UomRepackagingPreviewResponse,
} from '../services/replenishment.service';

describe('UomRepackagingComponent', () => {
  let fixture: ComponentFixture<UomRepackagingComponent>;
  let component: UomRepackagingComponent;
  let masterDataService: jasmine.SpyObj<MasterDataService>;
  let replenishmentService: jasmine.SpyObj<ReplenishmentService>;
  let notificationService: jasmine.SpyObj<DmisNotificationService>;
  let authRbac: jasmine.SpyObj<AuthRbacService>;

  beforeEach(async () => {
    masterDataService = jasmine.createSpyObj<MasterDataService>('MasterDataService', ['list', 'get']);
    replenishmentService = jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', [
      'getAllWarehouses',
      'previewUomRepackaging',
      'createUomRepackaging',
      'listUomRepackaging',
    ]);
    notificationService = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showSuccess',
      'showWarning',
      'showError',
    ]);
    authRbac = jasmine.createSpyObj<AuthRbacService>('AuthRbacService', ['load', 'roles', 'hasPermission']);

    authRbac.roles.and.returnValue(['LOGISTICS_MANAGER']);
    authRbac.hasPermission.and.returnValue(true);

    replenishmentService.getAllWarehouses.and.returnValue(of([
      { warehouse_id: 1, warehouse_name: 'North Hub' },
    ]));
    replenishmentService.listUomRepackaging.and.returnValue(of({
      results: [],
      count: 0,
      warnings: [],
    }));
    masterDataService.list.and.returnValue(of({
      results: [
        { item_id: 7, item_name: 'Water Tabs', item_code: 'WT-01' },
      ],
      count: 1,
      limit: 250,
      offset: 0,
      warnings: [],
    }));
    masterDataService.get.and.returnValue(of({
      record: {
        item_id: 7,
        item_name: 'Water Tabs',
        uom_options: [
          { item_uom_option_id: 1, uom_code: 'EA', conversion_factor: 1, is_default: true, status_code: 'A' },
          { item_uom_option_id: 2, uom_code: 'BOX', conversion_factor: 12, is_default: false, status_code: 'A' },
        ],
      },
      warnings: [],
    }));
    replenishmentService.previewUomRepackaging.and.returnValue(of({
      warehouse_id: 1,
      warehouse_name: 'North Hub',
      item_id: 7,
      item_name: 'Water Tabs',
      source_uom_code: 'BOX',
      source_qty: 2,
      target_uom_code: 'EA',
      target_qty: 24,
      equivalent_default_qty: 24,
      warnings: [],
    } as UomRepackagingPreviewResponse));
    replenishmentService.createUomRepackaging.and.returnValue(of({
      record: {
        repackaging_id: 'RP-1',
        warehouse_id: 1,
        warehouse_name: 'North Hub',
        item_id: 7,
        item_name: 'Water Tabs',
        source_uom_code: 'BOX',
        source_qty: 2,
        target_uom_code: 'EA',
        target_qty: 24,
        equivalent_default_qty: 24,
        reason_code: 'WAREHOUSE_HANDLING',
        created_by: 'ops.user',
        created_at: '2026-03-18T10:00:00Z',
      },
      warnings: [],
    } as UomRepackagingMutationResponse));

    await TestBed.configureTestingModule({
      imports: [UomRepackagingComponent],
      providers: [
        { provide: MasterDataService, useValue: masterDataService },
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DmisNotificationService, useValue: notificationService },
        { provide: AuthRbacService, useValue: authRbac },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(UomRepackagingComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('loads allowed UOM options for the selected item and defaults the target UOM', () => {
    component.form.controls.item_id.setValue(7);
    fixture.detectChanges();

    expect(component.allowedUomOptions().map((option) => option.uom_code)).toEqual(['EA', 'BOX']);
    expect(component.form.controls.source_uom_code.value).toBe('EA');
    expect(component.form.controls.target_uom_code.value).toBe('BOX');
  });

  it('excludes inactive item UOM options from repackaging selection', () => {
    masterDataService.get.and.returnValue(of({
      record: {
        item_id: 7,
        item_name: 'Water Tabs',
        uom_options: [
          { item_uom_option_id: 1, uom_code: 'EA', conversion_factor: 1, is_default: true, status_code: 'A' },
          { item_uom_option_id: 2, uom_code: 'BOX', conversion_factor: 12, is_default: false, status_code: 'I' },
          { item_uom_option_id: 3, uom_code: 'CS', conversion_factor: 24, is_default: false, status_code: 'A' },
        ],
      },
      warnings: [],
    }));

    component.form.controls.item_id.setValue(7);
    fixture.detectChanges();

    expect(component.allowedUomOptions().map((option) => option.uom_code)).toEqual(['EA', 'CS']);
  });

  it('ignores stale item detail responses when the user switches items quickly', () => {
    const firstItem$ = new Subject<{ record: Record<string, unknown>; warnings: string[] }>();
    const secondItem$ = new Subject<{ record: Record<string, unknown>; warnings: string[] }>();

    masterDataService.get.and.returnValues(firstItem$.asObservable(), secondItem$.asObservable());

    component.form.controls.item_id.setValue(7);
    component.form.controls.item_id.setValue(8);

    secondItem$.next({
      record: {
        item_id: 8,
        item_name: 'Rice',
        uom_options: [
          { item_uom_option_id: 5, uom_code: 'BAG', conversion_factor: 1, is_default: true, status_code: 'A' },
          { item_uom_option_id: 6, uom_code: 'KG', conversion_factor: 25, is_default: false, status_code: 'A' },
        ],
      },
      warnings: [],
    });
    secondItem$.complete();

    firstItem$.next({
      record: {
        item_id: 7,
        item_name: 'Water Tabs',
        uom_options: [
          { item_uom_option_id: 1, uom_code: 'EA', conversion_factor: 1, is_default: true, status_code: 'A' },
          { item_uom_option_id: 2, uom_code: 'BOX', conversion_factor: 12, is_default: false, status_code: 'A' },
        ],
      },
      warnings: [],
    });
    firstItem$.complete();

    expect(component.selectedItem()?.['item_id']).toBe(8);
    expect(component.allowedUomOptions().map((option) => option.uom_code)).toEqual(['BAG', 'KG']);
    expect(component.form.controls.source_uom_code.value).toBe('BAG');
    expect(component.form.controls.target_uom_code.value).toBe('KG');
  });

  it('prevents preview when source and target UOM are the same', () => {
    component.form.patchValue({
      warehouse_id: 1,
      item_id: 7,
      source_uom_code: 'EA',
      target_uom_code: 'EA',
      source_qty: 2,
    });

    component.onPreview();

    expect(replenishmentService.previewUomRepackaging).not.toHaveBeenCalled();
    expect(notificationService.showWarning).toHaveBeenCalledWith('Choose different source and target UOM values.');
  });

  it('uses the backend preview response as the source of truth', () => {
    component.form.patchValue({
      warehouse_id: 1,
      item_id: 7,
      source_uom_code: 'BOX',
      target_uom_code: 'EA',
      source_qty: 2,
    });

    component.onPreview();

    expect(replenishmentService.previewUomRepackaging).toHaveBeenCalledWith({
      warehouse_id: 1,
      item_id: 7,
      batch_or_lot: null,
      source_uom_code: 'BOX',
      source_qty: 2,
      target_uom_code: 'EA',
    });
    expect(component.preview()?.target_qty).toBe(24);
  });

  it('surfaces structured submit errors back into the form', () => {
    replenishmentService.createUomRepackaging.and.returnValue(throwError(() => ({
      error: {
        detail: 'Unable to save the repackaging transaction.',
        errors: {
          reason_code: 'Reason is required.',
        },
      },
    })));

    component.preview.set({
      warehouse_id: 1,
      item_id: 7,
      source_uom_code: 'BOX',
      source_qty: 2,
      target_uom_code: 'EA',
      target_qty: 24,
      equivalent_default_qty: 24,
      warnings: [],
    });
    component.form.patchValue({
      warehouse_id: 1,
      item_id: 7,
      source_uom_code: 'BOX',
      target_uom_code: 'EA',
      source_qty: 2,
      reason_code: 'WAREHOUSE_HANDLING',
    });

    component.onSubmit();

    expect(component.submitError()?.message).toBe('Unable to save the repackaging transaction.');
    expect(component.form.controls.reason_code.errors?.['server']).toBe('Reason is required.');
  });
});
