import { of } from 'rxjs';
import { ActivatedRoute, Router } from '@angular/router';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { MasterFormPageComponent } from './master-form-page.component';
import { MasterDataService } from '../../services/master-data.service';
import { IfrcSuggestService } from '../../services/ifrc-suggest.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { ReplenishmentService } from '../../../replenishment/services/replenishment.service';

function buildBaseItemRecord() {
  return {
    item_id: 17,
    item_code: 'LOC-001',
    item_name: 'Water Tabs',
    sku_code: 'SKU-001',
    category_id: 102,
    item_desc: 'Water purification tablets',
    reorder_qty: 10,
    default_uom_code: 'EA',
    issuance_order: 'FIFO',
    criticality_level: 'NORMAL',
    status_code: 'A',
    is_batched_flag: true,
    can_expire_flag: false,
    units_size_vary_flag: false,
    ifrc_family_id: null,
    ifrc_item_ref_id: null,
    version_nbr: 2,
  };
}

describe('MasterFormPageComponent', () => {
  function setup(params: Record<string, string> = {}) {
    const masterDataService = jasmine.createSpyObj<MasterDataService>('MasterDataService', [
      'lookup',
      'lookupItemCategories',
      'lookupIfrcFamilies',
      'lookupIfrcReferences',
      'get',
      'create',
      'update',
      'clearLookupCache',
    ]);
    const ifrcSuggestService = jasmine.createSpyObj<IfrcSuggestService>('IfrcSuggestService', ['suggest']);
    const notificationService = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showSuccess',
      'showError',
      'showWarning',
    ]);
    const replenishmentService = jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', ['assignStorageLocation']);
    const router = jasmine.createSpyObj<Router>('Router', ['navigate']);

    masterDataService.lookup.and.callFake((tableKey: string) => {
      if (tableKey === 'uom') {
        return of([{ value: 'EA', label: 'Each' }]);
      }
      return of([]);
    });
    masterDataService.lookupItemCategories.and.returnValue(of([
      { value: 102, label: 'WASH', category_code: 'WASH' },
    ]));
    masterDataService.lookupIfrcFamilies.and.callFake((options?: { categoryId?: string | number | null }) => (
      options?.categoryId === 102
        ? of([{ value: 301, label: 'Water Treatment', family_code: 'WTR', group_code: 'W', category_id: 102, category_desc: 'WASH', category_code: 'WASH' }])
        : of([])
    ));
    masterDataService.lookupIfrcReferences.and.callFake((options?: { ifrcFamilyId?: string | number | null }) => (
      options?.ifrcFamilyId === 301
        ? of([{ value: 401, label: 'Water purification tablet', ifrc_code: 'WWTRTABL01', ifrc_family_id: 301 }])
        : of([])
    ));
    masterDataService.get.and.returnValue(of({ record: buildBaseItemRecord(), warnings: [] }));
    ifrcSuggestService.suggest.and.returnValue(of(null));
    replenishmentService.assignStorageLocation.and.returnValue(of({
      created: true,
      storage_table: 'item_location',
      item_id: 17,
      inventory_id: 1,
      location_id: 2,
      batch_id: null,
    }));

    TestBed.configureTestingModule({
      imports: [MasterFormPageComponent, NoopAnimationsModule],
      providers: [
        { provide: ActivatedRoute, useValue: { data: of({ routePath: 'items' }), params: of(params) } },
        { provide: Router, useValue: router },
        { provide: MasterDataService, useValue: masterDataService },
        { provide: IfrcSuggestService, useValue: ifrcSuggestService },
        { provide: DmisNotificationService, useValue: notificationService },
        { provide: ReplenishmentService, useValue: replenishmentService },
      ],
    });

    const fixture = TestBed.createComponent(MasterFormPageComponent);
    fixture.detectChanges();

    return {
      fixture,
      component: fixture.componentInstance,
      masterDataService,
      notificationService,
    };
  }

  it('requires an IFRC family for new items when the selected category has governed families', () => {
    const { component } = setup();

    component.form.get('category_id')?.setValue(102);

    expect(component.form.hasError('ifrcFamilyRequired')).toBeTrue();
  });

  it('accepts IFRC suggestions by filling classification fields without overwriting the local item code', () => {
    const { component, notificationService } = setup();

    component.form.patchValue({
      item_code: 'LOC-001',
      item_name: 'Water Tabs',
      item_desc: 'Water purification tablets',
      default_uom_code: 'EA',
      reorder_qty: 10,
      issuance_order: 'FIFO',
      status_code: 'A',
    }, { emitEvent: false });
    component.ifrcSuggestion.set({
      suggestion_id: 'suggest-1',
      ifrc_code: 'WWTRTABL01',
      ifrc_description: 'Water purification tablet',
      confidence: 0.92,
      match_type: 'generated',
      construction_rationale: 'Name and spec hints matched the IFRC catalogue.',
      group_code: 'W',
      family_code: 'WTR',
      category_code: 'WTAB',
      spec_segment: '01',
      sequence: 1,
      auto_fill_threshold: 0.7,
    });
    component.ifrcSuggestionResolution.set({
      family: {
        value: 301,
        label: 'Water Treatment',
        family_code: 'WTR',
        group_code: 'W',
        category_id: 102,
        category_desc: 'WASH',
        category_code: 'WASH',
      },
      reference: {
        value: 401,
        label: 'Water purification tablet',
        ifrc_code: 'WWTRTABL01',
        ifrc_family_id: 301,
      },
      warning: null,
    });

    component.onAcceptIfrcSuggestion();

    expect(component.form.get('item_code')?.value).toBe('LOC-001');
    expect(component.form.get('category_id')?.value).toBe(102);
    expect(component.form.get('ifrc_family_id')?.value).toBe(301);
    expect(component.form.get('ifrc_item_ref_id')?.value).toBe(401);
    expect(notificationService.showSuccess).toHaveBeenCalled();
  });

  it('rejects IFRC suggestions without clearing local user-entered fields', () => {
    const { component } = setup();

    component.form.patchValue({
      item_code: 'LOC-777',
      item_name: 'Legacy Bucket',
    }, { emitEvent: false });
    component.ifrcSuggestion.set({
      suggestion_id: 'suggest-2',
      ifrc_code: 'WSHLBUKT01',
      ifrc_description: 'Bucket',
      confidence: 0.61,
      match_type: 'fallback',
      construction_rationale: 'Best available category match.',
      group_code: 'W',
      family_code: 'WSH',
      category_code: 'BUKT',
      spec_segment: '01',
      sequence: 1,
      auto_fill_threshold: 0.7,
    });

    component.onRejectIfrcSuggestion();

    expect(component.form.get('item_code')?.value).toBe('LOC-777');
    expect(component.form.get('item_name')?.value).toBe('Legacy Bucket');
    expect(component.ifrcSuggestion()).toBeNull();
  });

  it('keeps legacy edit records with null IFRC fields editable even when the category has governed families', () => {
    const { component } = setup({ pk: '17' });

    expect(component.isEdit()).toBeTrue();
    expect(component.form.get('ifrc_family_id')?.value).toBeNull();
    expect(component.form.get('ifrc_item_ref_id')?.value).toBeNull();
    expect(component.form.hasError('ifrcFamilyRequired')).toBeFalse();
    expect(component.form.valid).toBeTrue();
  });
});
