import { of, Subject, throwError } from 'rxjs';
import { ActivatedRoute, Router } from '@angular/router';
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialog } from '@angular/material/dialog';

import { MasterFormPageComponent } from './master-form-page.component';
import { MasterEditGateDialogComponent } from '../master-edit-gate-dialog/master-edit-gate-dialog.component';
import { MasterDataService } from '../../services/master-data.service';
import { MasterEditGateService } from '../../services/master-edit-gate.service';
import { IfrcSuggestService } from '../../services/ifrc-suggest.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { ReplenishmentService } from '../../../replenishment/services/replenishment.service';
import { IFRCSuggestion } from '../../models/ifrc-suggest.models';
import { ITEM_CONFIG } from '../../models/table-configs/item.config';
import { IFRC_FAMILY_CONFIG } from '../../models/table-configs/ifrc-family.config';
import { IFRC_ITEM_REFERENCE_CONFIG } from '../../models/table-configs/ifrc-item-reference.config';

function buildBaseItemRecord(overrides: Record<string, unknown> = {}) {
  return {
    item_id: 17,
    item_code: 'LOC-001',
    legacy_item_code: 'LOC-001',
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
    ...overrides,
  };
}

function buildIfrcFamilyRecord() {
  return {
    ifrc_family_id: 301,
    category_id: 102,
    group_code: 'W',
    group_label: 'WASH',
    family_code: 'WTR',
    family_label: 'Water Treatment',
    source_version: 'IFRC-2024-v3',
    status_code: 'A',
    version_nbr: 3,
  };
}

function buildIfrcReferenceRecord() {
  return {
    ifrc_item_ref_id: 77,
    ifrc_family_id: 301,
    ifrc_code: 'WWTRTABLTB01',
    reference_desc: 'Water purification tablet',
    category_code: 'TABL',
    category_label: 'Tablet',
    spec_segment: 'TB',
    size_weight: '100 TAB',
    form: 'TABLET',
    material: 'CHLORINE',
    source_version: 'IFRC-2024-v3',
    status_code: 'A',
    version_nbr: 5,
  };
}

function buildGovernedEditGuidance(lockedFields: string[]) {
  return {
    warning_required: true,
    warning_text: 'Canonical code-bearing fields stay locked; use replacement flow for corrections.',
    locked_fields: lockedFields,
    replacement_supported: true,
  };
}

function buildResolvedSuggestion(overrides: Partial<IFRCSuggestion> = {}): IFRCSuggestion {
  return {
    suggestion_id: 'suggest-1',
    ifrc_code: 'WWTRTABLTB01',
    ifrc_description: 'Water purification tablet',
    confidence: 0.92,
    match_type: 'generated',
    construction_rationale: 'Name and spec hints matched the IFRC catalogue.',
    group_code: 'W',
    family_code: 'WTR',
    category_code: 'TABL',
    spec_segment: 'TB',
    sequence: null,
    auto_fill_threshold: 0.85,
    resolution_status: 'resolved',
    resolution_explanation: 'Generated suggestion resolved to exactly one active governed IFRC reference.',
    ifrc_family_id: 301,
    resolved_ifrc_item_ref_id: 401,
    candidate_count: 1,
    auto_highlight_candidate_id: 401,
    direct_accept_allowed: true,
    candidates: [
      {
        ifrc_item_ref_id: 401,
        ifrc_family_id: 301,
        ifrc_code: 'WWTRTABLTB01',
        reference_desc: 'Water purification tablet',
        group_code: 'W',
        group_label: 'WASH',
        family_code: 'WTR',
        family_label: 'Water Treatment',
        category_code: 'TABL',
        category_label: 'Tablet',
        spec_segment: 'TB',
        rank: 1,
        score: 1,
        auto_highlight: true,
        match_reasons: ['exact_generated_code_match'],
      },
    ],
    ...overrides,
  };
}

function buildStorageAssignmentOptions(overrides: Partial<{
  item_id: number;
  is_batched: boolean;
  inventories: { value: number; label: string; detail?: string }[];
  locations: { value: number; inventory_id: number; label: string; detail?: string }[];
  batches: { value: number; inventory_id: number; label: string; detail?: string }[];
}> = {}) {
  return {
    item_id: 17,
    is_batched: true,
    inventories: [
      { value: 1, label: 'Kingston Central Depot', detail: 'Internal inventory ID 1' },
      { value: 2, label: 'Montego Bay Hub', detail: 'Internal inventory ID 2' },
    ],
    locations: [
      { value: 11, inventory_id: 1, label: 'Rack A-01', detail: 'Internal location ID 11' },
      { value: 22, inventory_id: 2, label: 'Cold Room B-02', detail: 'Internal location ID 22' },
    ],
    batches: [
      { value: 101, inventory_id: 1, label: 'LOT-101 · Expires 2026-04-01', detail: 'Internal batch ID 101' },
      { value: 202, inventory_id: 2, label: 'LOT-202 · Expires 2026-05-15', detail: 'Internal batch ID 202' },
    ],
    ...overrides,
  };
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type MasterFormPageComponentTestAccess = Record<string, any>;

describe('MasterFormPageComponent', () => {
  function setup(routePath = 'items', params: Record<string, string> = {}) {
    const masterDataService = jasmine.createSpyObj<MasterDataService>('MasterDataService', [
      'lookup',
      'lookupItemCategories',
      'lookupIfrcFamilies',
      'lookupIfrcReferences',
      'get',
      'create',
      'update',
      'clearLookupCache',
      'suggestIfrcFamilyValues',
      'suggestIfrcReferenceValues',
      'createCatalogReplacement',
    ]);
    const ifrcSuggestService = jasmine.createSpyObj<IfrcSuggestService>('IfrcSuggestService', ['suggest']);
    const notificationService = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showSuccess',
      'showError',
      'showWarning',
    ]);
    const replenishmentService = jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', [
      'assignStorageLocation',
      'getStorageAssignmentOptions',
    ]);
    const router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);

    masterDataService.lookup.and.callFake((tableKey: string) => {
      if (tableKey === 'uom') {
        return of([{ value: 'EA', label: 'Each' }]);
      }
      if (tableKey === 'item_categories') {
        return of([
          { value: 102, label: 'WASH' },
          { value: 103, label: 'Medical & Health' },
        ]);
      }
      if (tableKey === 'ifrc_families') {
        return of([
          { value: 301, label: 'Water Treatment' },
        ]);
      }
      return of([]);
    });
    masterDataService.lookupItemCategories.and.returnValue(of([
      { value: 102, label: 'WASH', category_code: 'WASH' },
    ]));
    masterDataService.lookupIfrcFamilies.and.callFake((options?: { categoryId?: string | number | null; search?: string }) => {
      if (options?.categoryId === 102 || options?.search === 'WTR') {
        return of([
          {
            value: 301,
            label: 'Water Treatment',
            family_code: 'WTR',
            group_code: 'W',
            category_id: 102,
            category_desc: 'WASH',
            category_code: 'WASH',
          },
        ]);
      }
      return of([]);
    });
    masterDataService.lookupIfrcReferences.and.callFake((options?: { ifrcFamilyId?: string | number | null }) => (
      options?.ifrcFamilyId === 301
        ? of([
            {
              value: 401,
              label: 'Water purification tablet',
              ifrc_code: 'WWTRTABLTB01',
              ifrc_family_id: 301,
              family_code: 'WTR',
              family_label: 'Water Treatment',
              category_code: 'TABL',
              category_label: 'Tablet',
              spec_segment: 'TB',
            },
            {
              value: 402,
              label: 'Water purification powder',
              ifrc_code: 'WWTRTABLPW01',
              ifrc_family_id: 301,
              family_code: 'WTR',
              family_label: 'Water Treatment',
              category_code: 'TABL',
              category_label: 'Tablet',
              spec_segment: 'PW',
            },
          ])
        : of([])
    ));
    masterDataService.get.and.callFake((tableKey: string) => {
      if (tableKey === 'ifrc_families') {
        return of({
          record: buildIfrcFamilyRecord(),
          warnings: [],
          edit_guidance: buildGovernedEditGuidance(['group_code', 'family_code']),
        });
      }
      if (tableKey === 'ifrc_item_references') {
        return of({
          record: buildIfrcReferenceRecord(),
          warnings: [],
          edit_guidance: buildGovernedEditGuidance(['ifrc_family_id', 'ifrc_code', 'category_code', 'spec_segment']),
        });
      }
      return of({ record: buildBaseItemRecord(), warnings: [] });
    });
    masterDataService.create.and.returnValue(of({ record: { item_id: 99 }, warnings: [] }));
    masterDataService.update.and.returnValue(of({ record: { item_id: 17 }, warnings: [] }));
    masterDataService.suggestIfrcFamilyValues.and.returnValue(of({
      source: 'deterministic',
      normalized: {
        category_id: 102,
        group_code: 'W',
        group_label: 'WASH',
        family_code: 'WTR',
        family_label: 'Water Treatment',
      },
      conflicts: { exact_code_match: null, exact_label_match: null, near_matches: [] },
      warnings: [],
    }));
    masterDataService.suggestIfrcReferenceValues.and.returnValue(of({
      source: 'deterministic',
      normalized: {
        ifrc_family_id: 301,
        ifrc_code: 'WWTRTABLTB02',
        reference_desc: 'Water purification tablet plus',
        category_code: 'TABL',
        category_label: 'Tablet',
        spec_segment: 'TB2',
        size_weight: '120 TAB',
        form: 'TABLET',
        material: 'CHLORINE',
      },
      conflicts: { exact_code_match: null, exact_desc_match: null, near_matches: [] },
      warnings: [],
    }));
    masterDataService.createCatalogReplacement.and.returnValue(of({
      record: { ifrc_item_ref_id: 91 },
      replacement_for_pk: 77,
      warnings: [],
    }));
    ifrcSuggestService.suggest.and.returnValue(of(null));
    replenishmentService.assignStorageLocation.and.returnValue(of({
      created: true,
      storage_table: 'item_location',
      item_id: 17,
      inventory_id: 1,
      location_id: 2,
      batch_id: null,
    }));
    replenishmentService.getStorageAssignmentOptions.and.returnValue(of(buildStorageAssignmentOptions()));
    dialog.open.and.returnValue({ afterClosed: () => of(true) } as never);

    TestBed.configureTestingModule({
      imports: [MasterFormPageComponent, NoopAnimationsModule],
      providers: [
        { provide: ActivatedRoute, useValue: { data: of({ routePath }), params: of(params) } },
        { provide: Router, useValue: router },
        { provide: MatDialog, useValue: dialog },
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
      ifrcSuggestService,
      notificationService,
      replenishmentService,
      router,
      dialog,
    };
  }

  function populateRequiredCreateFields(component: MasterFormPageComponent): void {
    component.form.patchValue({
      item_name: 'Water Tabs',
      item_desc: 'Water purification tablets',
      default_uom_code: 'EA',
      reorder_qty: 10,
      issuance_order: 'FIFO',
      status_code: 'A',
      category_id: 102,
      ifrc_family_id: 301,
    }, { emitEvent: false });
    component.onSelectIfrcReference({
      value: 401,
      label: 'Water purification tablet',
      ifrc_code: 'WWTRTABLTB01',
      ifrc_family_id: 301,
      family_code: 'WTR',
      family_label: 'Water Treatment',
      category_code: 'TABL',
      category_label: 'Tablet',
      spec_segment: 'TB',
    });
  }

  function seedSubmitFailure(component: MasterFormPageComponent): void {
    component.submissionError.set('Save failed.');
    component.form.setErrors({
      ...(component.form.errors || {}),
      submitFailure: true,
    });
  }

  it('requires an IFRC family for new items when a category is selected', () => {
    const { component } = setup();

    component.form.get('category_id')?.setValue(102);

    expect(component.form.hasError('ifrcFamilyRequired')).toBeTrue();
  });

  it('requires an IFRC reference for new items once a family is selected', () => {
    const { component } = setup();

    component.form.patchValue({
      category_id: 102,
      ifrc_family_id: 301,
    }, { emitEvent: false });
    component.form.updateValueAndValidity({ emitEvent: false });

    expect(component.form.hasError('ifrcReferenceRequired')).toBeTrue();
  });

  it('preserves inactive saved family and reference values when opening an existing item', () => {
    const { component, fixture, masterDataService } = setup();
    const inactiveFamilyId = 991;
    const inactiveReferenceId = 992;

    masterDataService.get.and.returnValue(of({
      record: buildBaseItemRecord({
        item_code: 'WWTRTABLTB99',
        legacy_item_code: 'LOC-001',
        category_id: 102,
        ifrc_family_id: inactiveFamilyId,
        ifrc_item_ref_id: inactiveReferenceId,
        ifrc_group_code: 'W',
        ifrc_group_label: 'WASH',
        ifrc_family_code: 'WTRX',
        ifrc_family_label: 'Water Treatment Legacy',
        ifrc_reference_code: 'WWTRTABLTB99',
        ifrc_reference_desc: 'Water purification tablet legacy',
        ifrc_reference_category_code: 'TABL',
        ifrc_reference_category_label: 'Tablet',
        ifrc_reference_spec_segment: 'TB99',
      }),
      warnings: [],
    }));
    masterDataService.lookupIfrcFamilies.and.returnValue(of([]));
    masterDataService.lookupIfrcReferences.and.returnValue(of([]));

    component.pk.set('17');
    component.isEdit.set(true);
    (component as unknown as { loadRecord: () => void }).loadRecord();
    fixture.detectChanges();

    expect(masterDataService.lookupIfrcFamilies).toHaveBeenCalledWith(jasmine.objectContaining({
      categoryId: 102,
      includeValue: inactiveFamilyId,
    }));
    expect(masterDataService.lookupIfrcReferences).toHaveBeenCalledWith(jasmine.objectContaining({
      ifrcFamilyId: inactiveFamilyId,
      includeValue: inactiveReferenceId,
    }));
    expect(component.form.get('ifrc_family_id')?.value).toBe(inactiveFamilyId);
    expect(component.form.get('ifrc_item_ref_id')?.value).toBe(inactiveReferenceId);
    expect(component.itemIfrcFamilyOptions().map((item) => item.value)).toContain(inactiveFamilyId);
    expect(component.itemIfrcReferenceOptions().map((item) => item.value)).toContain(inactiveReferenceId);
    expect(component.form.get('item_code')?.value).toBe('WWTRTABLTB99');
  });

  it('ignores stale IFRC family lookup responses that arrive after a newer request', () => {
    const { component, masterDataService } = setup();
    const firstResponse$ = new Subject<{
      value: number;
      label: string;
      family_code: string;
      group_code: string;
      category_id: number;
      category_desc: string;
      category_code: string;
    }[]>();
    const secondResponse$ = new Subject<{
      value: number;
      label: string;
      family_code: string;
      group_code: string;
      category_id: number;
      category_desc: string;
      category_code: string;
    }[]>();
    masterDataService.lookupIfrcFamilies.and.returnValues(
      firstResponse$.asObservable(),
      secondResponse$.asObservable(),
    );

    component.form.get('ifrc_family_id')?.patchValue(302, { emitEvent: false });
    (component as unknown as {
      loadItemFamilyOptions: (
        categoryId: string | number | null | undefined,
        preserveValue?: string | number | null,
      ) => void;
    }).loadItemFamilyOptions(102);
    (component as unknown as {
      loadItemFamilyOptions: (
        categoryId: string | number | null | undefined,
        preserveValue?: string | number | null,
      ) => void;
    }).loadItemFamilyOptions(103);

    secondResponse$.next([
      {
        value: 302,
        label: 'Emergency Shelter',
        family_code: 'SHEL',
        group_code: 'S',
        category_id: 103,
        category_desc: 'Shelter',
        category_code: 'SHELTER',
      },
    ]);

    expect(component.itemIfrcFamilyOptions().map((item) => item.value)).toEqual([302]);
    expect(component.form.get('ifrc_family_id')?.value).toBe(302);

    firstResponse$.next([
      {
        value: 301,
        label: 'Water Treatment',
        family_code: 'WTR',
        group_code: 'W',
        category_id: 102,
        category_desc: 'WASH',
        category_code: 'WASH',
      },
    ]);

    expect(component.itemIfrcFamilyOptions().map((item) => item.value)).toEqual([302]);
    expect(component.form.get('ifrc_family_id')?.value).toBe(302);
  });

  it('ignores stale IFRC reference lookup responses that arrive after a newer request', () => {
    const { component, masterDataService } = setup();
    const firstResponse$ = new Subject<{
      value: number;
      label: string;
      ifrc_code: string;
      ifrc_family_id: number;
      family_code: string;
      family_label: string;
      category_code: string;
      category_label: string;
      spec_segment: string;
    }[]>();
    const secondResponse$ = new Subject<{
      value: number;
      label: string;
      ifrc_code: string;
      ifrc_family_id: number;
      family_code: string;
      family_label: string;
      category_code: string;
      category_label: string;
      spec_segment: string;
    }[]>();
    masterDataService.lookupIfrcReferences.and.returnValues(
      firstResponse$.asObservable(),
      secondResponse$.asObservable(),
    );

    component.form.get('ifrc_item_ref_id')?.patchValue(402, { emitEvent: false });
    (component as unknown as {
      loadItemReferenceOptions: (
        familyId: string | number | null | undefined,
        search?: string,
        preserveValue?: string | number | null,
      ) => void;
    }).loadItemReferenceOptions(301, 'tablet');
    (component as unknown as {
      loadItemReferenceOptions: (
        familyId: string | number | null | undefined,
        search?: string,
        preserveValue?: string | number | null,
      ) => void;
    }).loadItemReferenceOptions(301, 'powder');

    secondResponse$.next([
      {
        value: 402,
        label: 'Water purification powder',
        ifrc_code: 'WWTRTABLPW01',
        ifrc_family_id: 301,
        family_code: 'WTR',
        family_label: 'Water Treatment',
        category_code: 'TABL',
        category_label: 'Tablet',
        spec_segment: 'PW',
      },
    ]);

    expect(component.itemIfrcReferenceOptions().map((item) => item.value)).toEqual([402]);
    expect(component.form.get('ifrc_item_ref_id')?.value).toBe(402);

    firstResponse$.next([
      {
        value: 401,
        label: 'Water purification tablet',
        ifrc_code: 'WWTRTABLTB01',
        ifrc_family_id: 301,
        family_code: 'WTR',
        family_label: 'Water Treatment',
        category_code: 'TABL',
        category_label: 'Tablet',
        spec_segment: 'TB',
      },
    ]);

    expect(component.itemIfrcReferenceOptions().map((item) => item.value)).toEqual([402]);
    expect(component.form.get('ifrc_item_ref_id')?.value).toBe(402);
    expect(component.form.get('item_code')?.value).toBe('WWTRTABLPW01');
  });

  it('renders the Find IFRC Match helper panel without deprecated helper input fields', () => {
    const { component, fixture } = setup();

    expect(component.form.contains('size_weight')).toBeFalse();
    expect(component.form.contains('form')).toBeFalse();
    expect(component.form.contains('material')).toBeFalse();

    component.currentStep.set(1);
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Find IFRC Match');
    expect(fixture.nativeElement.textContent).toContain('Find Match');
    expect(fixture.nativeElement.textContent).not.toContain('IFRC Size or Weight Hint');
    expect(fixture.nativeElement.textContent).not.toContain('IFRC Form Hint');
    expect(fixture.nativeElement.textContent).not.toContain('IFRC Material Hint');
  });

  it('ignores stale IFRC suggestion resolution lookups that arrive after a newer suggestion', () => {
    const { component, ifrcSuggestService, masterDataService } = setup();
    const firstFamilyResponse$ = new Subject<{
      value: number;
      label: string;
      family_code: string;
      group_code: string;
      category_id: number;
      category_desc: string;
      category_code: string;
    }[]>();
    const secondFamilyResponse$ = new Subject<{
      value: number;
      label: string;
      family_code: string;
      group_code: string;
      category_id: number;
      category_desc: string;
      category_code: string;
    }[]>();
    const firstSuggestion = buildResolvedSuggestion();
    const secondSuggestion = buildResolvedSuggestion({
      suggestion_id: 'suggest-2',
      ifrc_code: 'SSHELTENTA01',
      ifrc_description: 'Emergency shelter tent',
      group_code: 'S',
      family_code: 'SHEL',
      ifrc_family_id: 302,
      resolved_ifrc_item_ref_id: 402,
      auto_highlight_candidate_id: 402,
      candidates: [
        {
          ifrc_item_ref_id: 402,
          ifrc_family_id: 302,
          ifrc_code: 'SSHELTENTA01',
          reference_desc: 'Emergency shelter tent',
          group_code: 'S',
          group_label: 'Shelter',
          family_code: 'SHEL',
          family_label: 'Emergency Shelter',
          category_code: 'TENT',
          category_label: 'Tent',
          spec_segment: 'A',
          rank: 1,
          score: 1,
          auto_highlight: true,
          match_reasons: ['exact_generated_code_match'],
        },
      ],
    });
    ifrcSuggestService.suggest.and.returnValues(
      of(firstSuggestion),
      of(secondSuggestion),
    );
    masterDataService.lookupIfrcFamilies.and.returnValues(
      firstFamilyResponse$.asObservable(),
      secondFamilyResponse$.asObservable(),
    );

    component.form.patchValue({ item_name: 'Water purification tablet' }, { emitEvent: false });
    component.onRequestIfrcSuggestion();

    component.form.patchValue({ item_name: 'Emergency shelter tent' }, { emitEvent: false });
    component.onRequestIfrcSuggestion();

    secondFamilyResponse$.next([
      {
        value: 302,
        label: 'Emergency Shelter',
        family_code: 'SHEL',
        group_code: 'S',
        category_id: 103,
        category_desc: 'Shelter',
        category_code: 'SHELTER',
      },
    ]);

    expect(component.ifrcSuggestion()?.suggestion_id).toBe('suggest-2');
    expect(component.ifrcSuggestionResolution()?.family?.value).toBe(302);
    expect(component.ifrcSuggestionResolution()?.reference?.value).toBe(402);

    firstFamilyResponse$.next([
      {
        value: 301,
        label: 'Water Treatment',
        family_code: 'WTR',
        group_code: 'W',
        category_id: 102,
        category_desc: 'WASH',
        category_code: 'WASH',
      },
    ]);

    expect(component.ifrcSuggestion()?.suggestion_id).toBe('suggest-2');
    expect(component.ifrcSuggestionResolution()?.family?.value).toBe(302);
    expect(component.ifrcSuggestionResolution()?.reference?.value).toBe(402);
  });

  it('only requests IFRC helper suggestions when Find Match is used', fakeAsync(() => {
    const { component, ifrcSuggestService } = setup();

    component.form.get('item_name')?.setValue('Water Tabs, 500 g');
    tick();

    expect(ifrcSuggestService.suggest).not.toHaveBeenCalled();

    component.onRequestIfrcSuggestion();
    tick();

    expect(ifrcSuggestService.suggest).toHaveBeenCalledWith('Water Tabs, 500 g');
  }));

  it('enables the approved local-draft path for new unmapped items', () => {
    const { component, fixture } = setup();

    component.onSaveAsLocalDraft();
    fixture.detectChanges();

    expect(component.localDraftMode()).toBeTrue();
    expect(component.shouldShowLocalItemCodeField()).toBeTrue();
    expect(component.form.get('ifrc_family_id')?.value).toBeNull();
    expect(component.form.get('ifrc_item_ref_id')?.value).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Local Item Code');

    component.currentStep.set(1);
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Local draft mode is active');
  });

  it('shows storage assignment on the review step instead of earlier wizard steps', () => {
    const { component, fixture } = setup('items', { pk: '17' });

    component.currentStep.set(0);
    fixture.detectChanges();

    expect(component.canAssignLocation()).toBeTrue();
    expect(component.isOnReviewStep()).toBeFalse();
    expect(fixture.nativeElement.querySelector('.location-assignment-section')).toBeNull();

    component.currentStep.set(component.renderableFieldGroups().length);
    fixture.detectChanges();

    const assignmentSection = fixture.nativeElement.querySelector('.location-assignment-section') as HTMLElement | null;

    expect(component.isOnReviewStep()).toBeTrue();
    expect(assignmentSection).not.toBeNull();
    expect(assignmentSection?.textContent).toContain('Storage Location Assignment');
    expect(assignmentSection?.textContent).toContain('Warehouse');
    expect(assignmentSection?.textContent).toContain('Storage Location');
    expect(assignmentSection?.textContent).not.toContain('Inventory ID');
  });

  it('keeps Can Expire in the same wizard step as Issuance Order', () => {
    const inventoryRulesGroup = ITEM_CONFIG.formFields.filter((field) => field.group === 'Inventory Rules');
    const trackingGroup = ITEM_CONFIG.formFields.filter((field) => field.group === 'Tracking & Behaviour');

    expect(inventoryRulesGroup.map((field) => field.field)).toContain('issuance_order');
    expect(inventoryRulesGroup.map((field) => field.field)).toContain('can_expire_flag');
    expect(trackingGroup.map((field) => field.field)).not.toContain('can_expire_flag');
  });

  it('filters storage locations and batches to the selected inventory_id', () => {
    const { component } = setup('items', { pk: '17' });

    component.locationForm.controls.inventory_id.setValue(2);

    expect(component.locationAssignmentOptions().map((option) => option.label)).toEqual(['Cold Room B-02']);
    expect(component.batchAssignmentOptions().map((option) => option.label)).toEqual(['LOT-202 · Expires 2026-05-15']);
  });

  it('uses persisted storage-assignment batching instead of the dirty form toggle', () => {
    const { component, fixture, replenishmentService } = setup('items', { pk: '17' });

    component.currentStep.set(component.renderableFieldGroups().length);
    component.storageAssignmentOptions.set(buildStorageAssignmentOptions({
      is_batched: false,
      batches: [],
    }));
    component.form.get('is_batched_flag')?.setValue(true);
    component.locationForm.patchValue({
      inventory_id: 1,
      location_id: 11,
      batch_id: null,
    });
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).not.toContain('Batch / Lot');

    component.onAssignStorageLocation();

    expect(replenishmentService.assignStorageLocation).toHaveBeenCalledWith(jasmine.objectContaining({
      item_id: 17,
      inventory_id: 1,
      location_id: 11,
    }));
  });

  it('ignores stale storage-assignment option responses after a newer item load starts', () => {
    const { component, replenishmentService } = setup('items', { pk: '17' });
    const testAccess = component as unknown as MasterFormPageComponentTestAccess;
    const firstResponse$ = new Subject<ReturnType<typeof buildStorageAssignmentOptions>>();
    const secondResponse$ = new Subject<ReturnType<typeof buildStorageAssignmentOptions>>();

    replenishmentService.getStorageAssignmentOptions.and.returnValues(
      firstResponse$.asObservable(),
      secondResponse$.asObservable(),
    );

    component.pk.set('17');
    testAccess['loadStorageAssignmentOptionsForCurrentItem']();
    component.pk.set('18');
    testAccess['loadStorageAssignmentOptionsForCurrentItem']();

    secondResponse$.next(buildStorageAssignmentOptions({
      item_id: 18,
      inventories: [{ value: 18, label: 'Shelter Warehouse', detail: 'Internal inventory ID 18' }],
      locations: [{ value: 181, inventory_id: 18, label: 'Zone S-01', detail: 'Internal location ID 181' }],
      batches: [{ value: 1801, inventory_id: 18, label: 'LOT-1801 · Expires 2026-06-01', detail: 'Internal batch ID 1801' }],
    }));

    expect(component.storageAssignmentOptions()?.item_id).toBe(18);
    expect(component.inventoryAssignmentOptions().map((option) => option.label)).toEqual(['Shelter Warehouse']);
    expect(component.storageAssignmentLoading()).toBeFalse();

    firstResponse$.next(buildStorageAssignmentOptions({
      item_id: 17,
      inventories: [{ value: 17, label: 'Stale Warehouse', detail: 'Internal inventory ID 17' }],
      locations: [{ value: 171, inventory_id: 17, label: 'Stale Location', detail: 'Internal location ID 171' }],
      batches: [{ value: 1701, inventory_id: 17, label: 'LOT-1701 · Expires 2026-05-01', detail: 'Internal batch ID 1701' }],
    }));

    expect(component.storageAssignmentOptions()?.item_id).toBe(18);
    expect(component.inventoryAssignmentOptions().map((option) => option.label)).toEqual(['Shelter Warehouse']);
    expect(component.storageAssignmentLoading()).toBeFalse();
  });

  it('disables Next and returns to the first invalid earlier step when wizard prerequisites change later', () => {
    const { component, fixture } = setup('items', { pk: '17' });
    const testAccess = component as unknown as MasterFormPageComponentTestAccess;

    testAccess['setLocalDraftMode'](true);
    component.currentStep.set(1);
    fixture.detectChanges();

    expect(component.canGoNext()).toBeTrue();

    component.form.get('legacy_item_code')?.setValue('');
    component.form.get('legacy_item_code')?.markAsTouched();
    fixture.detectChanges();

    const nextButton = fixture.nativeElement.querySelector('.wizard-footer__next') as HTMLButtonElement | null;

    expect(component.canGoNext()).toBeFalse();
    expect(nextButton?.disabled).toBeTrue();

    component.goNext();

    expect(component.currentStep()).toBe(0);
  });

  it('treats form-level FEFO validation errors as invalid for the affected wizard step', () => {
    const { component } = setup('items', { pk: '17' });
    const testAccess = component as unknown as MasterFormPageComponentTestAccess;
    const stepIndex = component.renderableFieldGroups().findIndex((group) => (
      group.fields.some((field) => field.field === 'issuance_order')
    ));

    component.form.patchValue({
      issuance_order: 'FEFO',
      can_expire_flag: false,
    }, { emitEvent: false });
    component.form.updateValueAndValidity({ emitEvent: false });

    expect(stepIndex).toBeGreaterThanOrEqual(0);
    expect(component.form.hasError('fefoRequiresExpiry')).toBeTrue();
    expect(testAccess['isStepValid'](stepIndex)).toBeFalse();
  });

  it('includes the governed taxonomy in the review step summary', () => {
    const { component } = setup();
    const expectedLabels = ITEM_CONFIG.formFields
      .filter((field) => ['category_id', 'ifrc_family_id', 'ifrc_item_ref_id'].includes(field.field))
      .map((field) => field.label);

    component.form.patchValue({
      category_id: 102,
      ifrc_family_id: 301,
      ifrc_item_ref_id: 401,
    }, { emitEvent: false });
    component.form.updateValueAndValidity({ emitEvent: false });

    const classificationReview = component.reviewData().find((group) => group.groupLabel === 'Classification');

    expect(classificationReview).toBeDefined();
    expect(classificationReview?.fields.map((field) => field.label)).toEqual(jasmine.arrayContaining(expectedLabels));
  });

  it('resets wizard-only UI state before loading a different record', () => {
    const { component } = setup('items', { pk: '17' });
    const testAccess = component as unknown as MasterFormPageComponentTestAccess;

    component.currentStep.set(3);
    component.ifrcAppliedConfirmation.set({
      ifrcCode: 'WWTRTABLTB01',
      referenceLabel: 'Water purification tablet',
      familyLabel: 'Water Treatment',
    });
    component.ifrcCodeUpdatedOnStep1.set(true);
    component.expandedCandidateIds.set(new Set([401]));

    testAccess['resetWizardUiState']();

    expect(component.currentStep()).toBe(0);
    expect(component.ifrcAppliedConfirmation()).toBeNull();
    expect(component.ifrcCodeUpdatedOnStep1()).toBeFalse();
    expect(component.expandedCandidateIds().size).toBe(0);
  });

  it('keeps wizard step buttons labeled even when the visual label is hidden on mobile', () => {
    const { component, fixture } = setup();

    fixture.detectChanges();

    const firstStepButton = fixture.nativeElement.querySelector('.tracker__pill') as HTMLButtonElement | null;

    expect(firstStepButton?.getAttribute('aria-label')).toBe(`Step 1: ${component.wizardSteps()[0].label}`);
  });

  it('saves a create-time local draft through legacy_item_code instead of canonical item_code', () => {
    const { component, masterDataService } = setup();

    component.onSaveAsLocalDraft();
    component.form.patchValue({
      item_name: 'Water Tabs, local pack',
      item_desc: 'Water purification tablets',
      default_uom_code: 'EA',
      reorder_qty: 10,
      issuance_order: 'FIFO',
      status_code: 'A',
      category_id: 102,
      legacy_item_code: 'LOC-WASH-001',
      item_code: 'USER-TYPED',
    }, { emitEvent: false });
    component.form.updateValueAndValidity({ emitEvent: false });

    component.onSave();

    expect(masterDataService.create).toHaveBeenCalledWith('items', jasmine.objectContaining({
      category_id: 102,
      ifrc_family_id: null,
      ifrc_item_ref_id: null,
      legacy_item_code: 'LOC-WASH-001',
    }));
    const payload = masterDataService.create.calls.mostRecent().args[1] as Record<string, unknown>;
    expect(payload['item_code']).toBeUndefined();
  });

  it('accepts exact resolved IFRC suggestions by filling classification fields and previewing the canonical item code', () => {
    const { component, notificationService } = setup();
    const suggestion = buildResolvedSuggestion();

    component.form.patchValue({
      item_name: 'Water Tabs, local pack',
      item_desc: 'Water purification tablets',
      default_uom_code: 'EA',
      reorder_qty: 10,
      issuance_order: 'FIFO',
      status_code: 'A',
    }, { emitEvent: false });
    component.ifrcSuggestion.set(suggestion);
    component.ifrcSuggestionResolution.set({
      status: 'resolved',
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
        ifrc_code: 'WWTRTABLTB01',
        ifrc_family_id: 301,
        family_code: 'WTR',
        family_label: 'Water Treatment',
        category_code: 'TABL',
        category_label: 'Tablet',
        spec_segment: 'TB',
      },
      candidates: [
        {
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
            ifrc_code: 'WWTRTABLTB01',
            ifrc_family_id: 301,
            family_code: 'WTR',
            family_label: 'Water Treatment',
            category_code: 'TABL',
            category_label: 'Tablet',
            spec_segment: 'TB',
          },
          rank: 1,
          score: 1,
          autoHighlight: true,
          matchReasons: ['exact_generated_code_match'],
        },
      ],
      warning: null,
      explanation: suggestion.resolution_explanation ?? null,
      directAcceptAllowed: true,
      autoHighlightCandidateId: 401,
    });

    component.onAcceptIfrcSuggestion();

    expect(component.form.get('item_code')?.value).toBe('WWTRTABLTB01');
    expect(component.form.get('category_id')?.value).toBe(102);
    expect(component.form.get('ifrc_family_id')?.value).toBe(301);
    expect(component.form.get('ifrc_item_ref_id')?.value).toBe(401);
    expect(component.form.get('item_name')?.value).toBe('Water Tabs, local pack');
    expect(notificationService.showSuccess).toHaveBeenCalled();
  });

  it('accepts resolved IFRC suggestions from backend identifiers even without candidate rows', fakeAsync(() => {
    const { component, ifrcSuggestService, notificationService } = setup();
    const suggestion = buildResolvedSuggestion({
      direct_accept_allowed: false,
      candidates: [],
    });
    ifrcSuggestService.suggest.and.returnValue(of(suggestion));

    component.form.patchValue({
      item_name: 'Water purification tablet',
    }, { emitEvent: false });

    component.onRequestIfrcSuggestion();
    tick();

    expect(component.canAcceptResolvedIfrcSuggestion()).toBeTrue();
    expect(component.getIfrcSuggestionPrimaryActionLabel()).toBe('Accept Suggested Match');

    component.onAcceptIfrcSuggestion();

    expect(component.form.get('category_id')?.value).toBe(102);
    expect(component.form.get('ifrc_family_id')?.value).toBe(301);
    expect(component.form.get('ifrc_item_ref_id')?.value).toBe(401);
    expect(component.form.get('item_code')?.value).toBe('WWTRTABLTB01');
    expect(notificationService.showSuccess).toHaveBeenCalled();
  }));

  it('clears submit failure state after programmatic taxonomy updates', () => {
    const { component } = setup();
    const suggestion = buildResolvedSuggestion();
    const reference = {
      value: 401,
      label: 'Water purification tablet',
      ifrc_code: 'WWTRTABLTB01',
      ifrc_family_id: 301,
      family_code: 'WTR',
      family_label: 'Water Treatment',
      category_code: 'TABL',
      category_label: 'Tablet',
      spec_segment: 'TB',
    };

    component.ifrcSuggestion.set(suggestion);
    component.ifrcSuggestionResolution.set({
      status: 'resolved',
      family: {
        value: 301,
        label: 'Water Treatment',
        family_code: 'WTR',
        group_code: 'W',
        category_id: 102,
        category_desc: 'WASH',
        category_code: 'WASH',
      },
      reference,
      candidates: [
        {
          family: {
            value: 301,
            label: 'Water Treatment',
            family_code: 'WTR',
            group_code: 'W',
            category_id: 102,
            category_desc: 'WASH',
            category_code: 'WASH',
          },
          reference,
          rank: 1,
          score: 1,
          autoHighlight: true,
          matchReasons: ['exact_generated_code_match'],
        },
      ],
      warning: null,
      explanation: suggestion.resolution_explanation ?? null,
      directAcceptAllowed: true,
      autoHighlightCandidateId: 401,
    });

    seedSubmitFailure(component);
    component.onAcceptIfrcSuggestion();

    expect(component.submissionError()).toBeNull();
    expect(component.form.hasError('submitFailure')).toBeFalse();

    seedSubmitFailure(component);
    component.onSelectIfrcReference(reference);

    expect(component.submissionError()).toBeNull();
    expect(component.form.hasError('submitFailure')).toBeFalse();

    seedSubmitFailure(component);
    component.onClearIfrcReference();

    expect(component.submissionError()).toBeNull();
    expect(component.form.hasError('submitFailure')).toBeFalse();
    expect(component.form.hasError('ifrcReferenceRequired')).toBeTrue();
  });

  it('requires explicit candidate selection before accepting an ambiguous IFRC suggestion', () => {
    const { component, notificationService } = setup();
    const suggestion = buildResolvedSuggestion({
      ifrc_code: 'WWTRTABLXX01',
      resolution_status: 'ambiguous',
      resolution_explanation: 'Multiple active governed IFRC references are plausible; explicit user selection is required.',
      resolved_ifrc_item_ref_id: null,
      candidate_count: 2,
      auto_highlight_candidate_id: 401,
      direct_accept_allowed: false,
      candidates: [
        {
          ifrc_item_ref_id: 401,
          ifrc_family_id: 301,
          ifrc_code: 'WWTRTABLTB01',
          reference_desc: 'Water purification tablet',
          group_code: 'W',
          group_label: 'WASH',
          family_code: 'WTR',
          family_label: 'Water Treatment',
          category_code: 'TABL',
          category_label: 'Tablet',
          spec_segment: 'TB',
          rank: 1,
          score: 0.91,
          auto_highlight: true,
          match_reasons: ['exact_spec_match'],
        },
        {
          ifrc_item_ref_id: 402,
          ifrc_family_id: 301,
          ifrc_code: 'WWTRTABLPW01',
          reference_desc: 'Water purification powder',
          group_code: 'W',
          group_label: 'WASH',
          family_code: 'WTR',
          family_label: 'Water Treatment',
          category_code: 'TABL',
          category_label: 'Tablet',
          spec_segment: 'PW',
          rank: 2,
          score: 0.74,
          auto_highlight: false,
          match_reasons: ['desc_overlap:WATER,PURIFICATION'],
        },
      ],
    });

    component.form.patchValue({
      item_name: 'Water Tabs, 500 mg local blister',
    }, { emitEvent: false });
    const firstCandidate = {
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
        ifrc_code: 'WWTRTABLTB01',
        ifrc_family_id: 301,
        family_code: 'WTR',
        family_label: 'Water Treatment',
        category_code: 'TABL',
        category_label: 'Tablet',
        spec_segment: 'TB',
      },
      rank: 1,
      score: 0.91,
      autoHighlight: true,
      matchReasons: ['exact_spec_match'],
    };

    component.ifrcSuggestion.set(suggestion);
    component.ifrcSuggestionResolution.set({
      status: 'ambiguous',
      family: null,
      reference: null,
      candidates: [
        firstCandidate,
        {
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
            value: 402,
            label: 'Water purification powder',
            ifrc_code: 'WWTRTABLPW01',
            ifrc_family_id: 301,
            family_code: 'WTR',
            family_label: 'Water Treatment',
            category_code: 'TABL',
            category_label: 'Tablet',
            spec_segment: 'PW',
          },
          rank: 2,
          score: 0.74,
          autoHighlight: false,
          matchReasons: ['desc_overlap:WATER,PURIFICATION'],
        },
      ],
      warning: null,
      explanation: suggestion.resolution_explanation ?? null,
      directAcceptAllowed: false,
      autoHighlightCandidateId: 401,
    });

    expect(component.canAcceptResolvedIfrcSuggestion()).toBeFalse();

    component.onSelectSuggestionCandidate(firstCandidate);

    expect(component.canAcceptResolvedIfrcSuggestion()).toBeTrue();
    component.onAcceptIfrcSuggestion();

    expect(component.form.get('ifrc_item_ref_id')?.value).toBe(401);
    expect(component.form.get('item_code')?.value).toBe('WWTRTABLTB01');
    expect(component.form.get('item_name')?.value).toBe('Water Tabs, 500 mg local blister');
    expect(notificationService.showSuccess).toHaveBeenCalled();
  });

  it('shows the Find IFRC Match helper panel with candidate review details for ambiguous suggestions', () => {
    const { component, fixture } = setup();
    const suggestion = buildResolvedSuggestion({
      ifrc_code: 'FFODBEEF50001',
      ifrc_description: 'Corned beef, canned',
      resolution_status: 'ambiguous',
      resolution_explanation: 'Multiple official corned beef variants matched the entered size and packaging.',
      ifrc_family_id: 401,
      resolved_ifrc_item_ref_id: null,
      candidate_count: 2,
      auto_highlight_candidate_id: 502,
      direct_accept_allowed: false,
      candidates: [],
    });

    component.form.patchValue({
      item_name: 'Corned beef, canned, 500 g local label',
    }, { emitEvent: false });
    component.ifrcSuggestion.set(suggestion);
    component.ifrcSuggestionResolution.set({
      status: 'ambiguous',
      family: null,
      reference: null,
      candidates: [
        {
          family: {
            value: 401,
            label: 'Food Rations',
            family_code: 'FOD',
            group_code: 'F',
            category_id: 101,
            category_desc: 'Food & Nutrition',
            category_code: 'FOOD',
          },
          reference: {
            value: 501,
            label: 'Corned beef, canned',
            ifrc_code: 'FFODBEEF20001',
            ifrc_family_id: 401,
            family_code: 'FOD',
            family_label: 'Food Rations',
            category_code: 'BEEF',
            category_label: 'Corned Beef',
            spec_segment: '200',
            size_weight: '200 G',
            form: 'CANNED',
            material: '',
          },
          rank: 1,
          score: 0.77,
          autoHighlight: false,
          matchReasons: ['desc_overlap:CORNED,BEEF', 'size_weight_mismatch'],
        },
        {
          family: {
            value: 401,
            label: 'Food Rations',
            family_code: 'FOD',
            group_code: 'F',
            category_id: 101,
            category_desc: 'Food & Nutrition',
            category_code: 'FOOD',
          },
          reference: {
            value: 502,
            label: 'Corned beef, canned',
            ifrc_code: 'FFODBEEF50001',
            ifrc_family_id: 401,
            family_code: 'FOD',
            family_label: 'Food Rations',
            category_code: 'BEEF',
            category_label: 'Corned Beef',
            spec_segment: '500',
            size_weight: '500 G',
            form: 'CANNED',
            material: '',
          },
          rank: 2,
          score: 0.91,
          autoHighlight: true,
          matchReasons: ['exact_size_weight_match', 'desc_overlap:CORNED,BEEF'],
        },
      ],
      warning: null,
      explanation: suggestion.resolution_explanation ?? null,
      directAcceptAllowed: false,
      autoHighlightCandidateId: 502,
    } as never);

    component.currentStep.set(1);
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Find IFRC Match');
    expect(fixture.nativeElement.textContent).toContain('Corned beef, canned');

    // Variant details are now behind progressive disclosure — expand to verify
    const toggle = fixture.nativeElement.querySelector(
      '[aria-controls="ifrc-candidate-details-502"]',
    ) as HTMLButtonElement | null;

    expect(toggle).not.toBeNull();
    toggle?.click();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('500 G');
  });

  it('keeps candidate families distinct for multi-family ambiguous suggestions and applies the selected family', () => {
    const { component, notificationService, masterDataService } = setup();
    const suggestion = buildResolvedSuggestion({
      ifrc_family_id: null,
      resolved_ifrc_item_ref_id: null,
      resolution_status: 'ambiguous',
      direct_accept_allowed: false,
      candidate_count: 2,
      auto_highlight_candidate_id: 402,
      candidates: [
        {
          ifrc_item_ref_id: 401,
          ifrc_family_id: 301,
          ifrc_code: 'WWTRTABLTB01',
          reference_desc: 'Water purification tablet',
          group_code: 'W',
          group_label: 'WASH',
          family_code: 'WTR',
          family_label: 'Water Treatment',
          category_code: 'TABL',
          category_label: 'Tablet',
          spec_segment: 'TB',
          rank: 1,
          score: 0.82,
          auto_highlight: false,
          match_reasons: ['exact_spec_match'],
        },
        {
          ifrc_item_ref_id: 402,
          ifrc_family_id: 302,
          ifrc_code: 'SMEDGAUZE01',
          reference_desc: 'Sterile gauze pads',
          group_code: 'M',
          group_label: 'Medical',
          family_code: 'MED',
          family_label: 'Medical Consumables',
          category_code: 'GAUZ',
          category_label: 'Gauze',
          spec_segment: '01',
          rank: 2,
          score: 0.79,
          auto_highlight: true,
          match_reasons: ['desc_overlap:GAUZE,PADS'],
        },
      ],
    });
    const families = [
      {
        value: 301,
        label: 'Water Treatment',
        family_code: 'WTR',
        group_code: 'W',
        category_id: 102,
        category_desc: 'WASH',
        category_code: 'WASH',
      },
      {
        value: 302,
        label: 'Medical Consumables',
        family_code: 'MED',
        group_code: 'M',
        category_id: 103,
        category_desc: 'Medical & Health',
        category_code: 'HEALTH',
      },
    ];
    masterDataService.lookupIfrcFamilies.and.callFake((options?: { categoryId?: string | number | null; search?: string }) => {
      if (options?.categoryId === 103 || options?.search === 'MED') {
        return of([families[1]]);
      }
      if (options?.categoryId === 102 || options?.search === 'WTR') {
        return of([families[0]]);
      }
      return of(families);
    });
    masterDataService.lookupIfrcReferences.and.callFake((options?: { ifrcFamilyId?: string | number | null }) => (
      options?.ifrcFamilyId === 302
        ? of([
            {
              value: 402,
              label: 'Sterile gauze pads',
              ifrc_code: 'SMEDGAUZE01',
              ifrc_family_id: 302,
              family_code: 'MED',
              family_label: 'Medical Consumables',
              category_code: 'GAUZ',
              category_label: 'Gauze',
              spec_segment: '01',
            },
          ])
        : of([
            {
              value: 401,
              label: 'Water purification tablet',
              ifrc_code: 'WWTRTABLTB01',
              ifrc_family_id: 301,
              family_code: 'WTR',
              family_label: 'Water Treatment',
              category_code: 'TABL',
              category_label: 'Tablet',
              spec_segment: 'TB',
            },
          ])
    ));

    const resolution = (component as unknown as {
      buildSuggestionResolutionState: (
        currentSuggestion: IFRCSuggestion,
        currentFamilies: {
          value: number;
          label: string;
          family_code: string;
          group_code: string;
          category_id: number;
          category_desc: string;
          category_code: string;
        }[],
      ) => {
        family: {
          value: number;
        } | null;
        candidates: {
          family: {
            value: number;
            category_id: number;
          } | null;
          reference: {
            value: number;
            ifrc_code: string;
          };
        }[];
      };
    }).buildSuggestionResolutionState(suggestion, families);

    expect(resolution.family).toBeNull();
    expect(resolution.candidates.map((candidate) => candidate.family?.value ?? null)).toEqual([301, 302]);

    component.form.patchValue({
      item_name: 'Sterile gauze pads, local 10 x 10',
    }, { emitEvent: false });
    component.ifrcSuggestion.set(suggestion);
    component.ifrcSuggestionResolution.set(resolution as never);
    component.onSelectSuggestionCandidate(resolution.candidates[1] as never);

    expect(component.canAcceptResolvedIfrcSuggestion()).toBeTrue();

    component.onAcceptIfrcSuggestion();

    expect(component.form.get('category_id')?.value).toBe(103);
    expect(component.form.get('ifrc_family_id')?.value).toBe(302);
    expect(component.form.get('ifrc_item_ref_id')?.value).toBe(402);
    expect(component.form.get('item_code')?.value).toBe('SMEDGAUZE01');
    expect(component.form.get('item_name')?.value).toBe('Sterile gauze pads, local 10 x 10');
    expect(notificationService.showSuccess).toHaveBeenCalled();
  });

  it('blocks unresolved suggestions from acceptance', () => {
    const { component, notificationService } = setup();
    const suggestion = buildResolvedSuggestion({
      resolution_status: 'unresolved',
      resolution_explanation: 'Generated suggestion did not resolve to an active governed IFRC reference.',
      ifrc_family_id: null,
      resolved_ifrc_item_ref_id: null,
      candidate_count: 0,
      auto_highlight_candidate_id: null,
      direct_accept_allowed: false,
      candidates: [],
    });

    component.ifrcSuggestion.set(suggestion);
    component.ifrcSuggestionResolution.set({
      status: 'unresolved',
      family: null,
      reference: null,
      candidates: [],
      warning: suggestion.resolution_explanation ?? null,
      explanation: suggestion.resolution_explanation ?? null,
      directAcceptAllowed: false,
      autoHighlightCandidateId: null,
    });

    expect(component.canAcceptResolvedIfrcSuggestion()).toBeFalse();

    component.onAcceptIfrcSuggestion();

    expect(notificationService.showError).toHaveBeenCalledWith(
      'No governed IFRC reference is available to apply from this suggestion.',
    );
  });

  it('keeps the Find IFRC Match helper visible when no governed match is resolved', () => {
    const { component, fixture } = setup();
    const suggestion = buildResolvedSuggestion({
      ifrc_code: 'FMEDAMOX350PX01',
      ifrc_description: 'Amoxicillin, unsupported pouch',
      resolution_status: 'unresolved',
      resolution_explanation: '',
      ifrc_family_id: null,
      resolved_ifrc_item_ref_id: null,
      candidate_count: 0,
      auto_highlight_candidate_id: null,
      direct_accept_allowed: false,
      candidates: [],
    });

    component.form.patchValue({
      item_name: 'Amoxicillin 350 mg pouch',
    }, { emitEvent: false });
    component.ifrcSuggestion.set(suggestion);
    component.ifrcSuggestionResolution.set({
      status: 'unresolved',
      family: null,
      reference: null,
      candidates: [],
      warning: null,
      explanation: null,
      directAcceptAllowed: false,
      autoHighlightCandidateId: null,
    });

    component.currentStep.set(1);
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('Find IFRC Match');
    expect(fixture.nativeElement.textContent).toContain('No governed exact match found');
    expect(fixture.nativeElement.textContent).toContain('No governed exact IFRC reference matched the entered item.');
  });

  it('renders the item code field as readonly and backend-managed', () => {
    const { fixture } = setup();

    const itemCodeInput = fixture.nativeElement.querySelector('.managed-item-code-field input') as HTMLInputElement | null;

    expect(itemCodeInput).not.toBeNull();
    expect(itemCodeInput?.readOnly).toBeTrue();
  });

  it('shows a visible governance note beside the item classification controls', () => {
    const { component, fixture } = setup();

    component.currentStep.set(1);
    fixture.detectChanges();

    const note = fixture.nativeElement.querySelector('#item-taxonomy-governance-note') as HTMLElement | null;

    expect(note).not.toBeNull();
    expect(note?.textContent).toContain('Choose the IFRC Family and IFRC Item Reference to set the official code.');
    expect(note?.textContent).toContain('UOM is how stock is counted or issued');
  });

  it('shows the approved Item Categories governance panel on the page form', () => {
    const { fixture } = setup('item-categories');

    const governancePanel = fixture.nativeElement.querySelector('.governance-note-section') as HTMLElement | null;

    expect(governancePanel).not.toBeNull();
    expect(governancePanel?.textContent).toContain('Why this matters');
    expect(governancePanel?.textContent).toContain('This category is used for reporting and stock-planning rules.');
  });

  it('uses the approved Item Master governance copy in the config', () => {
    const itemCodeField = ITEM_CONFIG.formFields.find((field) => field.field === 'item_code');
    const localItemCodeField = ITEM_CONFIG.formFields.find((field) => field.field === 'legacy_item_code');
    const uomField = ITEM_CONFIG.formFields.find((field) => field.field === 'default_uom_code');

    expect(ITEM_CONFIG.formDescription).toContain('Use this page to set up an item.');
    expect(itemCodeField?.hint).toBe('Canonical code derived from the selected Level 3 IFRC reference. This is governed and not typed manually.');
    expect(localItemCodeField?.hint).toContain('saving a local draft without an IFRC match yet');
    expect(itemCodeField?.tooltip).toContain('the canonical item code changes with it');
    expect(uomField?.tooltip).toContain('UOM is not always the same as IFRC form.');
  });

  it('uses the approved governed catalog copy in the IFRC family and reference configs', () => {
    const familyCategoryField = IFRC_FAMILY_CONFIG.formFields.find((field) => field.field === 'category_id');
    const referenceFormField = IFRC_ITEM_REFERENCE_CONFIG.formFields.find((field) => field.field === 'form');
    const referenceCodeField = IFRC_ITEM_REFERENCE_CONFIG.formFields.find((field) => field.field === 'ifrc_code');

    expect(IFRC_FAMILY_CONFIG.formDescription).toContain('under a governed Level 1 category');
    expect(familyCategoryField?.tooltip).toContain('Group label alone does not determine the Level 1 category.');
    expect(IFRC_ITEM_REFERENCE_CONFIG.formDescription).toContain("they do not define the item's operational UOM");
    expect(referenceFormField?.tooltip).toContain('it is not the same as the item master UOM.');
    expect(referenceCodeField?.hint).toContain("used as the mapped item's canonical code");
  });

  it('keeps legacy edit records with null IFRC fields editable and preserves the existing item code display', () => {
    const { component } = setup('items', { pk: '17' });

    expect(component.isEdit()).toBeTrue();
    expect(component.form.get('item_code')?.value).toBe('LOC-001');
    expect(component.form.get('ifrc_family_id')?.value).toBeNull();
    expect(component.form.get('ifrc_item_ref_id')?.value).toBeNull();
    expect(component.form.hasError('ifrcFamilyRequired')).toBeFalse();
    expect(component.form.hasError('ifrcReferenceRequired')).toBeFalse();
    expect(component.form.valid).toBeTrue();
  });

  it('omits managed item_code from create payloads', () => {
    const { component, masterDataService } = setup();

    populateRequiredCreateFields(component);
    component.form.patchValue({
      item_code: 'USER-TYPED',
    }, { emitEvent: false });

    component.onSave();

    expect(masterDataService.create).toHaveBeenCalled();
    expect(masterDataService.create.calls.mostRecent().args[1]).not.toEqual(jasmine.objectContaining({
      item_code: 'USER-TYPED',
    }));
  });

  it('clears isSaving after a successful save completes', () => {
    const { component, masterDataService } = setup();
    const response$ = new Subject<{ record: { item_id: number }; warnings: string[] }>();

    masterDataService.create.and.returnValue(response$.asObservable());
    populateRequiredCreateFields(component);

    component.onSave();
    expect(component.isSaving()).toBeTrue();

    response$.next({ record: { item_id: 99 }, warnings: [] });
    response$.complete();

    expect(component.isSaving()).toBeFalse();
  });

  it('keeps 400 item validation handling unchanged', () => {
    const { component, masterDataService, notificationService } = setup();

    masterDataService.create.and.returnValue(throwError(() => ({
      status: 400,
      error: {
        errors: {
          item_name: 'Enter a unique item name.',
        },
      },
    })));

    populateRequiredCreateFields(component);
    component.onSave();

    expect(component.form.get('item_name')?.errors?.['server']).toBe('Enter a unique item name.');
    expect(component.form.get('item_name')?.touched).toBeTrue();
    expect(component.submissionError()).toBeNull();
    expect(notificationService.showWarning).toHaveBeenCalledWith('Please fix the validation errors.');
  });

  it('shows backend diagnostic details for non-validation item save failures', () => {
    const { component, masterDataService, notificationService } = setup();

    masterDataService.create.and.returnValue(throwError(() => ({
      status: 500,
      error: {
        detail: 'Item save failed in the catalog service.',
        diagnostic: 'item_uom_option mirror insert failed',
        warnings: ['Legacy code was preserved.', 'Retry after catalog sync.'],
      },
    })));

    populateRequiredCreateFields(component);
    component.onSave();

    expect(component.submissionError()).toBe('Item save failed in the catalog service.');
    expect(component.submissionErrorDetails()).toEqual([
      'Diagnostic: item_uom_option mirror insert failed',
      'Legacy code was preserved.',
      'Retry after catalog sync.',
    ]);
    expect(notificationService.showError).toHaveBeenCalledWith('Item save failed in the catalog service.');
  });

  it('uses temporary-unavailable wording for 503 item save failures', () => {
    const { component, masterDataService, notificationService } = setup();

    masterDataService.create.and.returnValue(throwError(() => ({
      status: 503,
      error: {
        diagnostic: 'taxonomy resolver unavailable',
      },
    })));

    populateRequiredCreateFields(component);
    component.onSave();

    expect(component.submissionError()).toBe('The item save service is temporarily unavailable. Please try again.');
    expect(component.submissionErrorDetails()).toEqual(['Diagnostic: taxonomy resolver unavailable']);
    expect(notificationService.showError).toHaveBeenCalledWith('The item save service is temporarily unavailable. Please try again.');
  });


  it('handles duplicate canonical item-code conflicts as a blocking flow', () => {
    const { component, masterDataService, router } = setup();

    masterDataService.create.and.returnValue(throwError(() => ({
      status: 409,
      error: {
        detail: 'That IFRC reference is already mapped to an existing item.',
        errors: {
          duplicate_canonical_item_code: {
            code: 'duplicate_canonical_item_code',
            ifrc_item_ref_id: 401,
            item_code: 'WWTRTABLTB01',
            existing_item: {
              item_id: 25,
              item_name: 'Water purification tablet',
              item_code: 'WWTRTABLTB01',
            },
          },
        },
      },
    })));

    populateRequiredCreateFields(component);
    component.onSave();

    expect(component.duplicateCanonicalConflict()?.existing_item?.item_id).toBe(25);
    expect(component.submissionError()).toContain('already mapped');

    component.onOpenDuplicateExistingItem();

    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'items', 25]);
  });

  it('loads governed edit warning state and locks canonical IFRC reference fields on edit', () => {
    const { component } = setup('ifrc-item-references', { pk: '77' });

    expect(component.getCatalogWarningText()).toContain('Canonical code-bearing fields stay locked');
    expect(component.getCatalogLockedFieldLabels()).toEqual(jasmine.arrayContaining([
      'IFRC Family',
      'IFRC Code',
      'Category Code',
      'Spec Segment',
    ]));
    expect(component.form.get('ifrc_family_id')?.disabled).toBeTrue();
    expect(component.form.get('ifrc_code')?.disabled).toBeTrue();
    expect(component.form.get('category_code')?.disabled).toBeTrue();
    expect(component.form.get('spec_segment')?.disabled).toBeTrue();
    expect(component.form.get('reference_desc')?.disabled).toBeFalse();
  });

  it('opens the governed edit warning dialog with the required actions and impact guidance', () => {
    const { component } = setup('ifrc-item-references', { pk: '77' });
    const dialogOpen = jasmine.createSpy('open').and.returnValue({ afterClosed: () => of(true) } as never);
    const internalComponent = component as unknown as {
      dialog: { open: typeof dialogOpen };
      promptedGovernedEditWarning: boolean;
      maybePromptGovernedEditWarning: () => void;
    };

    internalComponent.dialog = { open: dialogOpen };
    component.isEdit.set(true);
    component.catalogEditGuidance.set(
      buildGovernedEditGuidance(['ifrc_family_id', 'ifrc_code', 'category_code', 'spec_segment']),
    );
    internalComponent.promptedGovernedEditWarning = false;
    internalComponent.maybePromptGovernedEditWarning();

    expect(dialogOpen).toHaveBeenCalled();

    const openArgs = dialogOpen.calls.mostRecent().args;
    const dialogData = openArgs[1]?.data as {
      warningText?: string;
      lockedFields?: string[];
      impactModules?: string[];
    };

    expect(openArgs[0]).toBe(MasterEditGateDialogComponent);
    expect(openArgs[1]?.ariaLabelledBy).toBe('gate-dialog-title');
    expect(dialogData.warningText).toContain('Canonical code-bearing fields stay locked');
    expect(dialogData.lockedFields).toEqual(jasmine.arrayContaining([
      'IFRC Family',
      'IFRC Code',
      'Category Code',
      'Spec Segment',
    ]));
    expect(dialogData.impactModules?.length).toBeGreaterThan(0);
  });

  it('navigates to the list view when the governed edit warning dialog is cancelled', () => {
    const { component, router } = setup('ifrc-item-references', { pk: '77' });
    const dialogOpen = jasmine.createSpy('open').and.returnValue({ afterClosed: () => of(false) } as never);
    const internalComponent = component as unknown as {
      dialog: { open: typeof dialogOpen };
      promptedGovernedEditWarning: boolean;
      maybePromptGovernedEditWarning: () => void;
    };

    internalComponent.dialog = { open: dialogOpen };
    component.isEdit.set(true);
    component.catalogEditGuidance.set(
      buildGovernedEditGuidance(['ifrc_family_id', 'ifrc_code', 'category_code', 'spec_segment']),
    );
    internalComponent.promptedGovernedEditWarning = false;

    internalComponent.maybePromptGovernedEditWarning();

    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'ifrc-item-references']);
  });

  it('skips the governed edit warning dialog once after the detail-page gate is confirmed', () => {
    const { component } = setup('ifrc-item-references', { pk: '77' });
    const dialogOpen = jasmine.createSpy('open');
    const editGate = TestBed.inject(MasterEditGateService);
    const internalComponent = component as unknown as {
      dialog: { open: typeof dialogOpen };
      promptedGovernedEditWarning: boolean;
      maybePromptGovernedEditWarning: () => void;
    };

    editGate.markDetailEditGatePassed();
    internalComponent.dialog = { open: dialogOpen };
    component.isEdit.set(true);
    component.catalogEditGuidance.set(
      buildGovernedEditGuidance(['ifrc_family_id', 'ifrc_code', 'category_code', 'spec_segment']),
    );
    internalComponent.promptedGovernedEditWarning = false;

    internalComponent.maybePromptGovernedEditWarning();

    expect(dialogOpen).not.toHaveBeenCalled();
  });

  it('applies suggested IFRC family values during governed family creation', () => {
    const { component, masterDataService, notificationService } = setup('ifrc-families');

    component.form.patchValue({
      family_label: 'Water Treatment',
      status_code: 'A',
    }, { emitEvent: false });

    component.onSuggestCatalogValues();

    expect(masterDataService.suggestIfrcFamilyValues).toHaveBeenCalled();
    expect(component.catalogSuggestion()?.normalized['family_code']).toBe('WTR');

    component.onApplyCatalogSuggestion();

    expect(component.form.get('category_id')?.value).toBe(102);
    expect(component.form.get('group_code')?.value).toBe('W');
    expect(component.form.get('family_code')?.value).toBe('WTR');
    expect(notificationService.showSuccess).toHaveBeenCalledWith('Suggested values applied to the form.');
  });

  it('clears governed catalog suggestions when the source form values change', () => {
    const { component } = setup('ifrc-families');

    component.form.patchValue({
      family_label: 'Water Treatment',
      status_code: 'A',
    }, { emitEvent: false });

    component.onSuggestCatalogValues();

    expect(component.catalogSuggestion()).not.toBeNull();

    component.form.get('family_label')?.setValue('Water Treatment Plus');

    expect(component.catalogSuggestion()).toBeNull();
    expect(component.catalogAssistError()).toBe(
      'Catalog suggestions were cleared because the form changed. Request fresh suggestions before applying them.',
    );
  });

  it('keeps locked canonical fields unchanged when applying suggestions during normal IFRC reference edits', () => {
    const { component, notificationService } = setup('ifrc-item-references', { pk: '77' });
    const internalComponent = component as unknown as {
      applyGovernedCatalogFieldState: () => void;
    };

    component.isEdit.set(true);
    component.pk.set('77');
    component.catalogEditGuidance.set(
      buildGovernedEditGuidance(['ifrc_family_id', 'ifrc_code', 'category_code', 'spec_segment']),
    );
    component.form.patchValue(buildIfrcReferenceRecord(), { emitEvent: false });
    internalComponent.applyGovernedCatalogFieldState();

    component.onSuggestCatalogValues();
    component.onApplyCatalogSuggestion();

    expect(component.form.get('ifrc_code')?.value).toBe('WWTRTABLTB01');
    expect(component.form.get('reference_desc')?.value).toBe('Water purification tablet plus');
    expect(component.catalogAssistError()).toContain('Locked canonical fields were not applied');
    expect(notificationService.showWarning).toHaveBeenCalledWith('Suggested values were applied to editable fields only.');
  });

  it('does not invalidate governed catalog suggestions while applying them', () => {
    const { component } = setup('ifrc-families');

    component.form.patchValue({
      family_label: 'Water Treatment',
      status_code: 'A',
    }, { emitEvent: false });

    component.onSuggestCatalogValues();
    component.onApplyCatalogSuggestion();

    expect(component.catalogSuggestion()).not.toBeNull();
    expect(component.catalogAssistError()).toBeNull();
  });

  it('blocks family suggestions until the primary prerequisite field is filled', () => {
    const { component, fixture, masterDataService, notificationService } = setup('ifrc-families');

    expect(component.canRequestCatalogSuggestion()).toBeFalse();
    expect(component.getCatalogSuggestionReadinessText()).toBe('Complete Family Label before generating suggestions.');
    expect(fixture.nativeElement.textContent).toContain('Complete Family Label before generating suggestions.');

    component.onSuggestCatalogValues();

    expect(masterDataService.suggestIfrcFamilyValues).not.toHaveBeenCalled();
    expect(notificationService.showWarning).toHaveBeenCalledWith('Complete Family Label before requesting suggestions.');

    component.form.patchValue({ family_label: 'Water Treatment' }, { emitEvent: false });

    expect(component.canRequestCatalogSuggestion()).toBeTrue();
  });

  it('requires family and description before reference suggestions can run', () => {
    const { component, masterDataService, notificationService } = setup('ifrc-item-references');

    expect(component.canRequestCatalogSuggestion()).toBeFalse();
    expect(component.getCatalogSuggestionReadinessText()).toBe('Complete IFRC Family and Reference Description before generating suggestions.');

    component.form.patchValue({ ifrc_family_id: 301 }, { emitEvent: false });
    expect(component.canRequestCatalogSuggestion()).toBeFalse();

    component.onSuggestCatalogValues();

    expect(masterDataService.suggestIfrcReferenceValues).not.toHaveBeenCalled();
    expect(notificationService.showWarning).toHaveBeenCalledWith('Complete Reference Description before requesting suggestions.');

    component.form.patchValue({ reference_desc: 'Water purification tablet' }, { emitEvent: false });
    expect(component.canRequestCatalogSuggestion()).toBeTrue();
  });

  it('marks required governed fields clearly and provides tooltip help text', () => {
    const { component } = setup('ifrc-item-references');

    const requiredField = component.config()?.formFields.find((field) => field.field === 'reference_desc');
    expect(requiredField).toBeDefined();
    expect(requiredField?.required).toBeTrue();
    expect(component.getRenderedFieldLabel(requiredField!)).toBe('Reference Description');
    expect(component.getFieldTooltip(requiredField!)).toContain('description to propose codes');
  });

  it('uses stable slug ids for section headings and fieldset labels', () => {
    const { fixture } = setup('items');
    const compiled = fixture.nativeElement as HTMLElement;
    const identityHeading = Array.from(compiled.querySelectorAll<HTMLHeadingElement>('h3.section-title'))
      .find((heading) => heading.textContent?.includes('Item Identity'));

    expect(identityHeading).toBeTruthy();
    expect(identityHeading?.id).toBe('section-heading-item-identity');

    const identityFieldset = identityHeading?.closest('section')?.querySelector('fieldset.form-grid');
    expect(identityFieldset?.getAttribute('aria-labelledby')).toBe('section-heading-item-identity');
  });

  it('creates a governed replacement record for IFRC references instead of patching the original record', () => {
    const { component, masterDataService, router } = setup('ifrc-item-references', { pk: '77' });
    const internalComponent = component as unknown as {
      applyGovernedCatalogFieldState: () => void;
    };

    component.isEdit.set(true);
    component.pk.set('77');
    component.catalogEditGuidance.set(
      buildGovernedEditGuidance(['ifrc_family_id', 'ifrc_code', 'category_code', 'spec_segment']),
    );
    component.form.patchValue(buildIfrcReferenceRecord(), { emitEvent: false });
    internalComponent.applyGovernedCatalogFieldState();

    component.onStartReplacementDraft();
    component.form.patchValue({
      ifrc_code: 'WWTRTABLTB02',
      spec_segment: 'TB2',
      reference_desc: 'Water purification tablet plus',
    }, { emitEvent: false });
    component.form.markAsDirty();
    component.onRetireOriginalReplacementChange(true);

    component.onSave();

    expect(masterDataService.createCatalogReplacement).toHaveBeenCalledWith(
      'ifrc_item_references',
      '77',
      jasmine.objectContaining({
        ifrc_code: 'WWTRTABLTB02',
        spec_segment: 'TB2',
      }),
      true,
    );
    expect(masterDataService.update).not.toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'ifrc-item-references', 91]);
  });

  // ── Item UOM Conversion Tests ──

  it('starts with empty itemUomConversions on create', () => {
    const { component } = setup('items');
    expect(component.itemUomConversions()).toEqual([]);
  });

  it('addUomConversion adds a row with the next available alternate UOM and factor 1', () => {
    const { component } = setup('items');
    component['writeLookup']('uom', [
      { value: 'EA', label: 'Each' },
      { value: 'BX', label: 'Box' },
    ]);
    component.form.get('default_uom_code')?.setValue('EA', { emitEvent: false });

    component.addUomConversion();

    expect(component.itemUomConversions().length).toBe(1);
    expect(component.itemUomConversions()[0]).toEqual({ uom_code: 'BX', conversion_factor: 1 });
  });

  it('removeUomConversion removes the row at the given index', () => {
    const { component } = setup('items');
    component['writeLookup']('uom', [
      { value: 'EA', label: 'Each' },
      { value: 'BX', label: 'Box' },
      { value: 'CS', label: 'Case' },
    ]);
    component.form.get('default_uom_code')?.setValue('EA', { emitEvent: false });
    component.addUomConversion();
    component.addUomConversion();
    component.updateUomConversionUom(0, 'BX');
    component.updateUomConversionUom(1, 'CS');
    expect(component.itemUomConversions().length).toBe(2);

    component.removeUomConversion(0);
    expect(component.itemUomConversions().length).toBe(1);
    expect(component.itemUomConversions()[0].uom_code).toBe('CS');
  });

  it('availableAlternateUoms excludes default UOM and already-used alternates', () => {
    const { component } = setup('items');
    // Set up multiple UOM lookup options
    component['writeLookup']('uom', [
      { value: 'EA', label: 'Each' },
      { value: 'BX', label: 'Box' },
      { value: 'CS', label: 'Case' },
      { value: 'PK', label: 'Pack' },
    ]);
    component.form.get('default_uom_code')?.setValue('EA', { emitEvent: false });

    // EA is default, should be excluded
    const available1 = component.availableAlternateUoms();
    expect(available1.length).toBe(3);
    expect(available1.find(u => u.value === 'EA')).toBeUndefined();

    // Add BX as alternate
    component.addUomConversion();
    component.updateUomConversionUom(0, 'BX');

    const available2 = component.availableAlternateUoms();
    expect(available2.length).toBe(2);
    expect(available2.find(u => u.value === 'BX')).toBeUndefined();
    expect(available2.find(u => u.value === 'EA')).toBeUndefined();
  });

  it('loadRecord populates itemUomConversions from uom_options (non-default only)', () => {
    const recordWithUomOptions = buildBaseItemRecord({
      uom_options: [
        { item_uom_option_id: 1, uom_code: 'EA', conversion_factor: 1, is_default: true, sort_order: 0, status_code: 'A' },
        { item_uom_option_id: 2, uom_code: 'BX', conversion_factor: 24, is_default: false, sort_order: 1, status_code: 'A' },
        { item_uom_option_id: 3, uom_code: 'CS', conversion_factor: 144, is_default: false, sort_order: 2, status_code: 'A' },
      ],
    });

    // Override get before setup to return uom_options in the record
    const masterDataServicePre = jasmine.createSpyObj<MasterDataService>('MasterDataService', [
      'lookup', 'lookupItemCategories', 'lookupIfrcFamilies', 'lookupIfrcReferences',
      'get', 'create', 'update', 'clearLookupCache',
      'suggestIfrcFamilyValues', 'suggestIfrcReferenceValues', 'createCatalogReplacement',
    ]);
    masterDataServicePre.lookup.and.callFake((tableKey: string) => {
      if (tableKey === 'uom') return of([{ value: 'EA', label: 'Each' }]);
      if (tableKey === 'item_categories') return of([{ value: 102, label: 'WASH' }]);
      if (tableKey === 'ifrc_families') return of([{ value: 301, label: 'Water Treatment' }]);
      return of([]);
    });
    masterDataServicePre.lookupItemCategories.and.returnValue(of([{ value: 102, label: 'WASH', category_code: 'WASH' }]));
    masterDataServicePre.lookupIfrcFamilies.and.returnValue(of([]));
    masterDataServicePre.lookupIfrcReferences.and.returnValue(of([]));
    masterDataServicePre.get.and.returnValue(of({ record: recordWithUomOptions, warnings: [] }));
    masterDataServicePre.create.and.returnValue(of({ record: { item_id: 99 }, warnings: [] }));
    masterDataServicePre.update.and.returnValue(of({ record: { item_id: 17 }, warnings: [] }));

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [MasterFormPageComponent, NoopAnimationsModule],
      providers: [
        { provide: ActivatedRoute, useValue: { data: of({ routePath: 'items' }), params: of({ pk: '17' }) } },
        { provide: Router, useValue: jasmine.createSpyObj<Router>('Router', ['navigate']) },
        { provide: MatDialog, useValue: jasmine.createSpyObj<MatDialog>('MatDialog', ['open']) },
        { provide: MasterDataService, useValue: masterDataServicePre },
        { provide: IfrcSuggestService, useValue: jasmine.createSpyObj<IfrcSuggestService>('IfrcSuggestService', ['suggest']) },
        { provide: DmisNotificationService, useValue: jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', ['showSuccess', 'showError', 'showWarning']) },
        { provide: ReplenishmentService, useValue: jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', ['assignStorageLocation']) },
      ],
    });

    const fixture = TestBed.createComponent(MasterFormPageComponent);
    fixture.detectChanges();
    const component = fixture.componentInstance;

    expect(component.itemUomConversions().length).toBe(2);
    expect(component.itemUomConversions()[0]).toEqual({ uom_code: 'BX', conversion_factor: 24 });
    expect(component.itemUomConversions()[1]).toEqual({ uom_code: 'CS', conversion_factor: 144 });
  });

  it('buildPreparedFormPayload includes uom_options from itemUomConversions', () => {
    const { component } = setup('items');
    populateRequiredCreateFields(component);
    component['writeLookup']('uom', [
      { value: 'EA', label: 'Each' },
      { value: 'BX', label: 'Box' },
    ]);
    component.form.get('default_uom_code')?.setValue('EA', { emitEvent: false });
    component.addUomConversion();
    component.updateUomConversionUom(0, 'BX');
    component.updateUomConversionFactor(0, 24);

    const payload = component['buildPreparedFormPayload'](ITEM_CONFIG);
    expect(payload['uom_options']).toEqual([
      { uom_code: 'BX', conversion_factor: 24 },
    ]);
  });

  it('buildPreparedFormPayload rejects invalid rendered item UOM conversions', () => {
    const { component } = setup('items');
    populateRequiredCreateFields(component);
    component['writeLookup']('uom', [
      { value: 'EA', label: 'Each' },
      { value: 'BX', label: 'Box' },
    ]);
    component.form.get('default_uom_code')?.setValue('EA', { emitEvent: false });

    component.addUomConversion();
    component.updateUomConversionFactor(0, Number.NaN);

    expect(component.form.hasError('invalidItemUomConversions')).toBeTrue();
    expect(() => component['buildPreparedFormPayload'](ITEM_CONFIG)).toThrowError(
      'Item UOM conversions contain invalid rows.',
    );
  });

  it('changing default_uom_code with existing alternates clears on confirm', () => {
    const { component } = setup('items');
    component['writeLookup']('uom', [
      { value: 'EA', label: 'Each' },
      { value: 'BX', label: 'Box' },
    ]);
    component.form.get('default_uom_code')?.setValue('EA', { emitEvent: false });
    (component as any).previousDefaultUom = 'EA';

    component.addUomConversion();
    component.updateUomConversionUom(0, 'BX');
    expect(component.itemUomConversions().length).toBe(1);

    spyOn(window, 'confirm').and.returnValue(true);
    component.form.get('default_uom_code')?.setValue('KG');

    expect(window.confirm).toHaveBeenCalled();
    expect(component.itemUomConversions().length).toBe(0);
  });

  it('changing default_uom_code with existing alternates reverts on cancel', () => {
    const { component } = setup('items');
    component['writeLookup']('uom', [
      { value: 'EA', label: 'Each' },
      { value: 'BX', label: 'Box' },
    ]);
    component.form.get('default_uom_code')?.setValue('EA', { emitEvent: false });
    (component as any).previousDefaultUom = 'EA';

    component.addUomConversion();
    component.updateUomConversionUom(0, 'BX');
    expect(component.itemUomConversions().length).toBe(1);

    spyOn(window, 'confirm').and.returnValue(false);
    component.form.get('default_uom_code')?.setValue('KG');

    expect(window.confirm).toHaveBeenCalled();
    expect(component.itemUomConversions().length).toBe(1);
    expect(component.form.get('default_uom_code')?.value).toBe('EA');
  });

  it('cannot add conversion when no available UOMs', () => {
    const { component } = setup('items');
    // Only one UOM available (EA) which is the default
    component['writeLookup']('uom', [{ value: 'EA', label: 'Each' }]);
    component.form.get('default_uom_code')?.setValue('EA', { emitEvent: false });

    expect(component.availableAlternateUoms().length).toBe(0);
    component.addUomConversion();
    expect(component.itemUomConversions().length).toBe(0);
  });
});

