import { of, throwError } from 'rxjs';
import { ActivatedRoute, Router } from '@angular/router';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialog } from '@angular/material/dialog';

import { MasterFormPageComponent } from './master-form-page.component';
import { MasterDataService } from '../../services/master-data.service';
import { IfrcSuggestService } from '../../services/ifrc-suggest.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { ReplenishmentService } from '../../../replenishment/services/replenishment.service';
import { IFRCSuggestion } from '../../models/ifrc-suggest.models';
import { ITEM_CONFIG } from '../../models/table-configs/item.config';
import { IFRC_FAMILY_CONFIG } from '../../models/table-configs/ifrc-family.config';
import { IFRC_ITEM_REFERENCE_CONFIG } from '../../models/table-configs/ifrc-item-reference.config';

function buildBaseItemRecord() {
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
    sequence: 1,
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
    const replenishmentService = jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', ['assignStorageLocation']);
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
      notificationService,
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

  it('keeps size, form, and material in the helper panel instead of the persisted item form', () => {
    const { component, fixture } = setup();

    expect(component.form.contains('size_weight')).toBeFalse();
    expect(component.form.contains('form')).toBeFalse();
    expect(component.form.contains('material')).toBeFalse();
    expect(component.ifrcSpecForm.contains('size_weight')).toBeTrue();
    expect(component.ifrcSpecForm.contains('form')).toBeTrue();
    expect(component.ifrcSpecForm.contains('material')).toBeTrue();
    expect(fixture.nativeElement.textContent).toContain('Find IFRC Match');
  });

  it('accepts exact resolved IFRC suggestions by filling classification fields and previewing the canonical item code', () => {
    const { component, notificationService } = setup();
    const suggestion = buildResolvedSuggestion();

    component.form.patchValue({
      item_name: 'Water Tabs',
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
    expect(notificationService.showSuccess).toHaveBeenCalled();
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
    const firstCandidate = {
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
      family: {
        value: 301,
        label: 'Water Treatment',
        family_code: 'WTR',
        group_code: 'W',
        category_id: 102,
        category_desc: 'WASH',
        category_code: 'WASH',
      },
      reference: null,
      candidates: [
        firstCandidate,
        {
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

  it('renders the item code field as readonly and backend-managed', () => {
    const { fixture } = setup();

    const itemCodeInput = fixture.nativeElement.querySelector('.managed-item-code-field input') as HTMLInputElement | null;

    expect(itemCodeInput).not.toBeNull();
    expect(itemCodeInput?.readOnly).toBeTrue();
  });

  it('shows a visible governance note beside the item classification controls', () => {
    const { fixture } = setup();

    const note = fixture.nativeElement.querySelector('#item-taxonomy-governance-note') as HTMLElement | null;

    expect(note).not.toBeNull();
    expect(note?.textContent).toContain('Category aligns to the selected IFRC Family.');
    expect(note?.textContent).toContain('UOM is the operational issue or counting unit and may differ from IFRC form.');
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
    const uomField = ITEM_CONFIG.formFields.find((field) => field.field === 'default_uom_code');

    expect(ITEM_CONFIG.formDescription).toContain('Items are governed by the selected IFRC Family and IFRC Item Reference.');
    expect(itemCodeField?.hint).toBe('Canonical code derived from the selected Level 3 IFRC reference. This is governed and not typed manually.');
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
      confirmLabel?: string;
      cancelLabel?: string;
      details?: Array<{ value?: string }>;
    };

    expect(dialogData.confirmLabel).toBe('Continue to Edit');
    expect(dialogData.cancelLabel).toBe('Cancel');
    expect(dialogData.details?.some((detail) => String(detail.value ?? '').includes('classification, search, and future item selection'))).toBeTrue();
    expect(dialogData.details?.some((detail) => String(detail.value ?? '').includes('Create Replacement'))).toBeTrue();
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

  it('blocks family suggestions until the primary prerequisite field is filled', () => {
    const { component, fixture, masterDataService, notificationService } = setup('ifrc-families');

    expect(component.canRequestCatalogSuggestion()).toBeFalse();
    expect(component.getCatalogSuggestionReadinessText()).toBe('Complete Family Label before generating suggestions.');
    expect(fixture.nativeElement.textContent).toContain('Fill these in first');

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
});

