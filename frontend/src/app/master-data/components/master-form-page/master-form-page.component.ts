import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  ElementRef, Injector, afterNextRender, inject, signal, computed, effect, viewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  AbstractControl,
  ReactiveFormsModule,
  FormGroup,
  FormControl,
  ValidatorFn,
  Validators,
  ValidationErrors,
} from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { of, Subject } from 'rxjs';
import {
  catchError, debounceTime, distinctUntilChanged, finalize, map, pairwise, startWith, switchMap,
} from 'rxjs/operators';
import { TextFieldModule } from '@angular/cdk/text-field';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatNativeDateModule } from '@angular/material/core';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatCardModule } from '@angular/material/card';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';

import {
  CatalogAuthoringSuggestionResponse,
  CatalogEditGuidance,
  LookupItem,
  MasterFieldConfig,
  MasterRecord,
  MasterSaveFailureResponse,
  MasterTableConfig,
} from '../../models/master-data.models';
import {
  IfrcFamilyLookup,
  IfrcReferenceLookup,
  ItemCategoryLookup,
} from '../../models/item-taxonomy.models';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import { MasterDataService } from '../../services/master-data.service';
import { MasterEditGateService } from '../../services/master-edit-gate.service';
import { IfrcSuggestService } from '../../services/ifrc-suggest.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import {
  ReplenishmentService,
  StorageAssignmentOption,
  StorageAssignmentOptionsResponse,
} from '../../../replenishment/services/replenishment.service';
import { validateFefoRequiresExpiry } from '../../models/table-configs/item.config';
import { MasterEditGateDialogComponent } from '../master-edit-gate-dialog/master-edit-gate-dialog.component';
import { DmisStepTrackerComponent, StepDefinition } from '../../../shared/dmis-step-tracker/dmis-step-tracker.component';
import {
  IFRCSuggestion,
  IFRCSuggestionCandidate,
  IFRCSuggestionResolutionStatus,
} from '../../models/ifrc-suggest.models';

interface InactiveItemForwardWriteGuard {
  table: string;
  workflow_state: string;
  item_ids: number[];
}

interface SuggestedIfrcCandidate {
  family: IfrcFamilyLookup | null;
  reference: IfrcReferenceLookup;
  rank: number;
  score: number;
  autoHighlight: boolean;
  matchReasons: string[];
}

interface ResolvedIfrcSuggestion {
  status: IFRCSuggestionResolutionStatus;
  family: IfrcFamilyLookup | null;
  reference: IfrcReferenceLookup | null;
  candidates: SuggestedIfrcCandidate[];
  warning: string | null;
  explanation: string | null;
  directAcceptAllowed: boolean;
  autoHighlightCandidateId: string | number | null;
}

interface DuplicateCanonicalItemConflict {
  code: string;
  ifrc_item_ref_id: string | number | null;
  item_code: string;
  existing_item: {
    item_id: string | number | null;
    item_name: string;
    item_code: string;
  } | null;
}

interface CatalogSuggestionRequirement {
  field: string;
  label: string;
  required: boolean;
  detail: string;
  ready: boolean;
}

interface FormFieldGroup {
  key: string;
  label: string;
  fields: MasterFieldConfig[];
}

interface ErrorSummaryLink {
  id: string;
  label: string;
}

interface ItemUomConversionRow {
  uom_code: string;
  conversion_factor: number | null;
}

class ItemUomConversionValidationError extends Error {
  constructor(readonly details: string[]) {
    super('Item UOM conversions contain invalid rows.');
    this.name = 'ItemUomConversionValidationError';
  }
}

@Component({
  selector: 'dmis-master-form-page',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, RouterModule,
    TextFieldModule,
    MatAutocompleteModule,
    MatFormFieldModule, MatInputModule, MatSelectModule, MatButtonModule,
    MatIconModule, MatSlideToggleModule, MatDatepickerModule, MatNativeDateModule,
    MatProgressBarModule, MatCardModule, MatTooltipModule, MatDialogModule,
    DmisStepTrackerComponent,
  ],
  templateUrl: './master-form-page.component.html',
  styleUrl: './master-form-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterFormPageComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(MasterDataService);
  private editGate = inject(MasterEditGateService);
  private dialog = inject(MatDialog);
  private ifrcSuggestService = inject(IfrcSuggestService);
  private replenishmentService = inject(ReplenishmentService);
  private notify = inject(DmisNotificationService);
  private destroyRef = inject(DestroyRef);
  private injector = inject(Injector);

  config = signal<MasterTableConfig | null>(null);
  form = new FormGroup<Record<string, FormControl>>({});
  readonly errorSummary = viewChild<ElementRef<HTMLElement>>('errorSummary');
  isEdit = signal(false);
  isLoading = signal(false);
  isSaving = signal(false);
  assigningLocation = signal(false);
  storageAssignmentLoading = signal(false);
  storageAssignmentError = signal<string | null>(null);
  storageAssignmentOptions = signal<StorageAssignmentOptionsResponse | null>(null);
  lookups = signal<Record<string, LookupItem[]>>({});
  lookupLoading = signal<Record<string, boolean>>({});
  lookupErrors = signal<Record<string, string>>({});
  private readonly formStateVersion = signal(0);
  private readonly locationFormVersion = signal(0);
  catalogEditGuidance = signal<CatalogEditGuidance | null>(null);
  catalogSuggestion = signal<CatalogAuthoringSuggestionResponse | null>(null);
  catalogSuggestionLoading = signal(false);
  catalogAssistError = signal<string | null>(null);
  catalogToolsExpanded = signal(true);
  guidedBannerDismissed = signal(false);
  replacementMode = signal(false);
  retireOriginalOnReplacement = signal(false);
  ifrcLoading = signal(false);
  ifrcSuggestion = signal<IFRCSuggestion | null>(null);
  ifrcSuggestionResolution = signal<ResolvedIfrcSuggestion | null>(null);
  selectedSuggestionCandidateId = signal<string | number | null>(null);
  ifrcError = signal<string | null>(null);
  ifrcAppliedConfirmation = signal<{
    ifrcCode: string;
    referenceLabel: string;
    familyLabel: string;
  } | null>(null);
  ifrcCodeUpdatedOnStep1 = signal(false);
  expandedCandidateIds = signal<Set<string | number>>(new Set());
  submissionError = signal<string | null>(null);
  submissionErrorDetails = signal<string[]>([]);
  duplicateCanonicalConflict = signal<DuplicateCanonicalItemConflict | null>(null);
  localDraftMode = signal(false);
  ifrcRejectedState = signal<'create' | 'edit' | null>(null);
  pk = signal<string | number | null>(null);
  referenceSearchControl = new FormControl<string>('', { nonNullable: true });

  readonly formPageTitle = computed(() => {
    const cfg = this.config();
    return cfg ? `${this.isEdit() ? 'Edit' : 'Create'} ${cfg.displayName}` : '';
  });

  readonly formPageSubtitle = computed(() => (
    this.isEdit()
      ? 'Update the fields below and save your changes'
      : 'Fill in the details below to create a new record'
  ));

  readonly showErrorSummary = computed(() => {
    this.formStateVersion();
    return this.form.invalid && this.form.touched;
  });

  readonly invalidControlLinks = computed<ErrorSummaryLink[]>(() => {
    this.formStateVersion();
    const cfg = this.config();
    if (!cfg || !this.form.touched) {
      return [];
    }

    const links: ErrorSummaryLink[] = [];
    const seenIds = new Set<string>();
    for (const field of cfg.formFields) {
      if (!this.isFieldVisibleForMode(field)) {
        continue;
      }
      const control = this.form.get(field.field);
      const id = this.getFieldDomId(field);
      if (control?.invalid && !seenIds.has(id)) {
        links.push({ id, label: field.label });
        seenIds.add(id);
      }
    }
    return links;
  });

  // ── Item UOM Conversion state ──
  itemUomConversions = signal<ItemUomConversionRow[]>([]);
  private previousDefaultUom: string | null = null;

  availableAlternateUoms = computed(() => {
    this.formStateVersion();
    const allUoms = this.lookups()['uom'] || [];
    const defaultUom = this.form.get('default_uom_code')?.value;
    const usedUoms = new Set(this.itemUomConversions().map(c => c.uom_code));
    if (defaultUom) usedUoms.add(defaultUom as string);
    return allUoms.filter(u => !usedUoms.has(u.value as string));
  });

  // ── Wizard state ──
  currentStep = signal(0);

  isWizardMode = computed(() => this.renderableFieldGroups().length >= 4);

  wizardSteps = computed<{ label: string; icon: string; key: string; isReview: boolean }[]>(() => {
    const groups = this.renderableFieldGroups();
    const steps = groups.map((g) => ({
      label: g.label,
      icon: this.getSectionIcon(g.label),
      key: g.key,
      isReview: false,
    }));
    steps.push({ label: 'Review & Submit', icon: 'checklist', key: 'review', isReview: true });
    return steps;
  });

  totalSteps = computed(() => this.wizardSteps().length);

  readonly trackerSteps = computed<StepDefinition[]>(() =>
    this.wizardSteps().map(step => ({ label: step.label }))
  );

  onTrackerStepClick(index: number): void {
    this.goToStep(index);
  }

  currentStepGroup = computed<FormFieldGroup | null>(() => {
    const groups = this.renderableFieldGroups();
    const step = this.currentStep();
    return step < groups.length ? groups[step] : null;
  });

  isOnReviewStep = computed(() => this.currentStep() >= this.renderableFieldGroups().length);

  canGoNext = computed(() => {
    this.formStateVersion();
    if (this.isOnReviewStep()) return false;
    const group = this.currentStepGroup();
    if (!group) return false;
    return this.areStepsValidThrough(this.currentStep());
  });

  reviewData = computed<{ groupLabel: string; groupKey: string; fields: { label: string; value: string }[] }[]>(() => {
    this.formStateVersion();
    const groups = this.renderableFieldGroups();
    return groups.map((group) => ({
      groupLabel: group.label,
      groupKey: group.key,
      fields: this.getReviewFields(group).map((field) => ({
        label: field.label,
        value: this.getReviewDisplayValue(field),
      })),
    }));
  });

  private readonly ifrcTrigger$ = new Subject<string>();
  readonly formErrorMessages: Record<string, string> = {
    fefoRequiresExpiry: 'Can Expire must be enabled when Issuance Order is FEFO.',
    expiryRequiresFefo: 'Issuance Order must be FEFO when Can Expire is enabled.',
  };

  private versionNbr: number | null = null;
  private acceptedIfrcSuggestLogId: string | null = null;
  private applyingTaxonomyPatch = false;
  private currentIfrcResolveToken = 0;
  private selectedReferenceOption: IfrcReferenceLookup | null = null;
  private itemCodeFallbackValue: string | null = null;
  private legacyItemCodeValue: string | null = null;
  private itemHadMappedClassificationOnLoad = false;
  private loadedRecordSnapshot: MasterRecord | null = null;
  private promptedGovernedEditWarning = false;
  private _ifrcBadgeTimeout: ReturnType<typeof setTimeout> | null = null;
  private readonly duplicateCanonicalItemCodeError = 'duplicate_canonical_item_code';
  private readonly inactiveItemForwardWriteCode = 'inactive_item_forward_write_blocked';
  readonly lookupNoneValue = '__DMIS_LOOKUP_NONE__';
  private readonly lookupRequestIds: Record<string, number> = {};
  private latestStorageAssignmentRequestId = 0;
  locationForm = new FormGroup({
    inventory_id: new FormControl<number | null>(null, [
      Validators.required,
      Validators.min(1),
    ]),
    location_id: new FormControl<number | null>(null, [
      Validators.required,
      Validators.min(1),
    ]),
    batch_id: new FormControl<number | null>(null, [Validators.min(1)]),
  });

  private readonly locationFormDisableEffect = effect(() => {
    const loading = this.storageAssignmentLoading();
    const noInventory = this.selectedAssignmentInventoryId() === null;
    const opts = { emitEvent: false } as const;

    if (loading) {
      this.locationForm.controls.inventory_id.disable(opts);
    } else {
      this.locationForm.controls.inventory_id.enable(opts);
    }

    const dependentBlocked = loading || noInventory;
    if (dependentBlocked) {
      this.locationForm.controls.location_id.disable(opts);
      this.locationForm.controls.batch_id.disable(opts);
    } else {
      this.locationForm.controls.location_id.enable(opts);
      this.locationForm.controls.batch_id.enable(opts);
    }
  });

  /** Group form fields by their group property */
  fieldGroups = computed<FormFieldGroup[]>(() => {
    const cfg = this.config();
    if (!cfg) return [];
    const groups: FormFieldGroup[] = [];
    const seen = new Map<string, FormFieldGroup>();
    const usedKeys = new Map<string, number>();

    for (const f of cfg.formFields) {
      if (!this.isFieldVisibleForMode(f)) {
        continue;
      }

      const groupLabel = f.group || 'General';
      let group = seen.get(groupLabel);

      if (!group) {
        const groupKey = this.buildFieldGroupKey(groupLabel, usedKeys);
        group = { key: groupKey, label: groupLabel, fields: [] };
        seen.set(groupLabel, group);
        groups.push(group);
      }

      group.fields.push(f);
    }
    return groups;
  });

  /** True when the last field group is a single Status select — collapse into action bar */
  lastGroupIsSingleStatus = computed(() => {
    const groups = this.fieldGroups();
    if (groups.length === 0) return false;
    const last = groups[groups.length - 1];
    return last.label === 'Status' && last.fields.length === 1 && last.fields[0].type === 'select';
  });

  /** Returns the groups to render as section cards (excludes collapsed status group) */
  renderableFieldGroups = computed(() => {
    const groups = this.fieldGroups();
    if (this.lastGroupIsSingleStatus()) {
      return groups.slice(0, -1);
    }
    return groups;
  });

  isItemRecord = computed(() => this.config()?.tableKey === 'items');
  isBatchedItem = computed(() => {
    this.formStateVersion();
    return Boolean(this.form.get('is_batched_flag')?.value);
  });
  canAssignLocation = computed(() => this.isItemRecord() && this.isEdit() && this.toPositiveInt(this.pk()) != null);
  itemCategoryOptions = computed(() => this.readLookup<ItemCategoryLookup>('item_categories'));
  itemIfrcFamilyOptions = computed(() => this.readLookup<IfrcFamilyLookup>('ifrc_families'));
  itemIfrcReferenceOptions = computed(() => this.readLookup<IfrcReferenceLookup>('ifrc_references'));
  inventoryAssignmentOptions = computed<StorageAssignmentOption[]>(() => (
    this.storageAssignmentOptions()?.inventories ?? []
  ));
  selectedAssignmentInventoryId = computed<number | null>(() => {
    this.locationFormVersion();
    return this.toPositiveInt(this.locationForm.controls.inventory_id.value);
  });
  locationAssignmentOptions = computed<StorageAssignmentOption[]>(() => {
    const inventoryId = this.selectedAssignmentInventoryId();
    const options = this.storageAssignmentOptions()?.locations ?? [];
    if (inventoryId == null) {
      return [];
    }
    return options.filter((option) => this.toPositiveInt(option.inventory_id) === inventoryId);
  });
  batchAssignmentOptions = computed<StorageAssignmentOption[]>(() => {
    const inventoryId = this.selectedAssignmentInventoryId();
    const options = this.storageAssignmentOptions()?.batches ?? [];
    if (inventoryId == null) {
      return [];
    }
    return options.filter((option) => this.toPositiveInt(option.inventory_id) === inventoryId);
  });
  assignmentIsBatched = computed(() => Boolean(this.storageAssignmentOptions()?.is_batched));

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => {
      if (this._ifrcBadgeTimeout) {
        clearTimeout(this._ifrcBadgeTimeout);
      }
    });

    this.locationForm.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.locationFormVersion.update((version) => version + 1);
    });

    this.locationForm.controls.inventory_id.valueChanges.pipe(
      startWith(this.locationForm.controls.inventory_id.value),
      pairwise(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(([previousValue, currentValue]) => {
      if (!this.sameValue(previousValue, currentValue)) {
        this.locationForm.controls.location_id.setValue(null, { emitEvent: false });
        this.locationForm.controls.batch_id.setValue(null, { emitEvent: false });
        this.locationFormVersion.update((version) => version + 1);
      }
    });

    this.route.data.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(data => {
      this.resetWizardUiState();
      const routePath = data['routePath'] as string;
      const cfg = ALL_TABLE_CONFIGS[routePath];
      if (cfg) {
        this.config.set(cfg);
        this.buildForm(cfg);
        this.setupItemTaxonomyState(cfg);
        this.setupItemIfrcSuggestion(cfg);
        this.loadLookups(cfg);
        if (cfg.tableKey !== 'items') {
          this.resetStorageAssignmentState();
        }
        if (this.pk()) {
          this.primeGovernedEditState();
          this.loadRecord();
        }
      }
    });

    this.route.params.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(params => {
      this.resetWizardUiState();
      const pkParam = params['pk'];
      if (pkParam && pkParam !== 'new') {
        this.pk.set(pkParam);
        this.isEdit.set(true);
        this.refreshFormModeValidators();
        this.primeGovernedEditState();
        this.loadRecord();
        return;
      }

      this.resetStorageAssignmentState();
      this.pk.set(null);
      this.isEdit.set(false);
      this.refreshFormModeValidators();
    });
  }

  private buildForm(cfg: MasterTableConfig): void {
    for (const field of cfg.formFields) {
      this.form.addControl(
        field.field,
        new FormControl(
          this.toLookupControlValue(field, field.defaultValue ?? null),
          this.getFieldValidators(field),
        ),
      );
    }

    if (cfg.tableKey === 'items') {
      this.form.setValidators([
        validateFefoRequiresExpiry,
        (control) => this.validateItemClassification(control),
        () => this.validateItemUomConversions(),
      ]);
      this.updateLocalDraftFieldValidators();
      this.form.updateValueAndValidity({ emitEvent: false });
    }

    this.form.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.formStateVersion.update((version) => version + 1);
      if (this.submissionError()) {
        this.clearSubmissionError();
      }

      if (this.isGovernedCatalogAuthoringTable() && this.catalogSuggestion()) {
        this.catalogSuggestion.set(null);
        this.catalogAssistError.set(
          'Catalog suggestions were cleared because the form changed. Request fresh suggestions before applying them.',
        );
      }
    });

    this.form.statusChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.formStateVersion.update((version) => version + 1);
    });

    this.setupUserWarehouseTenantFilter(cfg);
  }

  private getFieldValidators(field: MasterFieldConfig): ValidatorFn[] {
    const validators: ValidatorFn[] = [];
    if (field.required && this.isFieldVisibleForMode(field)) validators.push(Validators.required);
    if (field.maxLength) validators.push(Validators.maxLength(field.maxLength));
    if (field.pattern) validators.push(Validators.pattern(field.pattern));
    if (field.type === 'email') {
      validators.push(Validators.email);
    }
    return validators;
  }

  private refreshFormModeValidators(): void {
    const cfg = this.config();
    if (!cfg) return;
    for (const field of cfg.formFields) {
      const control = this.form.get(field.field);
      if (!control) continue;
      control.setValidators(this.getFieldValidators(field));
      control.updateValueAndValidity({ emitEvent: false });
    }
    this.formStateVersion.update((version) => version + 1);
  }

  private isFieldVisibleForMode(field: MasterFieldConfig): boolean {
    if (field.editOnly && !this.isEdit()) return false;
    if (field.createOnly && this.isEdit()) return false;
    return true;
  }

  private setupItemTaxonomyState(cfg: MasterTableConfig): void {
    if (cfg.tableKey !== 'items') return;

    const categoryControl = this.form.get('category_id');
    const familyControl = this.form.get('ifrc_family_id');
    const referenceControl = this.form.get('ifrc_item_ref_id');
    if (!categoryControl || !familyControl || !referenceControl) {
      return;
    }

    this.updateItemTaxonomyControlState();

    categoryControl.valueChanges.pipe(
      startWith(categoryControl.value),
      pairwise(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(([previousValue, currentValue]) => {
      if (this.sameValue(previousValue, currentValue)) {
        return;
      }

      if (!this.applyingTaxonomyPatch) {
        familyControl.patchValue(null, { emitEvent: false });
        referenceControl.patchValue(null, { emitEvent: false });
        this.selectedReferenceOption = null;
        this.referenceSearchControl.setValue('', { emitEvent: false });
        this.clearAcceptedSuggestion();
        this.clearIfrcSuggestionState();
        this.syncDisplayedItemCode();
      }

      this.writeLookup('ifrc_families', []);
      this.writeLookup('ifrc_references', []);
      this.updateItemTaxonomyControlState();
      this.form.updateValueAndValidity({ emitEvent: false });
      this.loadItemFamilyOptions(currentValue);
    });

    familyControl.valueChanges.pipe(
      startWith(familyControl.value),
      pairwise(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(([previousValue, currentValue]) => {
      if (this.sameValue(previousValue, currentValue)) {
        return;
      }

      if (!this.applyingTaxonomyPatch) {
        referenceControl.patchValue(null, { emitEvent: false });
        this.selectedReferenceOption = null;
        this.referenceSearchControl.setValue('', { emitEvent: false });
        this.clearAcceptedSuggestion();
        this.clearIfrcSuggestionState();
        this.syncDisplayedItemCode();
      }

      this.writeLookup('ifrc_references', []);
      this.updateItemTaxonomyControlState();
      this.form.updateValueAndValidity({ emitEvent: false });
      this.loadItemReferenceOptions(currentValue);
    });

    referenceControl.valueChanges.pipe(
      startWith(referenceControl.value),
      pairwise(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(([previousValue, currentValue]) => {
      if (this.sameValue(previousValue, currentValue)) {
        return;
      }

      if (!this.applyingTaxonomyPatch) {
        if (currentValue == null || currentValue === '') {
          this.selectedReferenceOption = null;
          this.referenceSearchControl.setValue('', { emitEvent: false });
        }
        this.clearAcceptedSuggestion();
        this.clearIfrcSuggestionState();
      }

      this.syncDisplayedItemCode();
      this.updateItemTaxonomyControlState();
      this.form.updateValueAndValidity({ emitEvent: false });
    });

    this.referenceSearchControl.valueChanges.pipe(
      map((value) => value.trim()),
      debounceTime(250),
      distinctUntilChanged(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((search) => {
      const selectedFamilyId = familyControl.value;
      if (!selectedFamilyId) {
        this.writeLookup('ifrc_references', []);
        return;
      }

      if (!this.applyingTaxonomyPatch) {
        const selectedReferenceLabel = this.selectedReferenceOption
          ? this.getItemReferenceLabel(this.selectedReferenceOption)
          : '';
        if (selectedReferenceLabel && search !== selectedReferenceLabel) {
          referenceControl.patchValue(null, { emitEvent: false });
          this.selectedReferenceOption = null;
          this.clearAcceptedSuggestion();
          this.clearIfrcSuggestionState();
          this.syncDisplayedItemCode();
          this.form.updateValueAndValidity({ emitEvent: false });
        }
      }

      this.updateItemTaxonomyControlState();
      this.loadItemReferenceOptions(selectedFamilyId, search);
    });

    this.setupItemUomConversionWatcher();
  }

  private setupItemUomConversionWatcher(): void {
    const defaultUomControl = this.form.get('default_uom_code');
    if (!defaultUomControl) return;

    this.previousDefaultUom = defaultUomControl.value ?? null;

    defaultUomControl.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((newValue) => {
      const previousValue = this.previousDefaultUom;
      if (this.sameValue(previousValue, newValue)) return;

      if (this.itemUomConversions().length > 0) {
        const confirmed = window.confirm(
          'Changing the default UOM will remove all alternate UOM conversions. Continue?',
        );
        if (confirmed) {
          this.itemUomConversions.set([]);
          this.syncItemUomConversionState();
          this.previousDefaultUom = newValue ?? null;
        } else {
          defaultUomControl.setValue(previousValue, { emitEvent: false });
          this.formStateVersion.update(v => v + 1);
        }
      } else {
        this.previousDefaultUom = newValue ?? null;
        this.form.updateValueAndValidity({ emitEvent: false });
      }
    });
  }

  private validateItemClassification(control: AbstractControl): ValidationErrors | null {
    if (!this.isItemRecord()) {
      return null;
    }

    const categoryId = control.get('category_id')?.value;
    const familyId = control.get('ifrc_family_id')?.value;
    const referenceId = control.get('ifrc_item_ref_id')?.value;
    const errors: ValidationErrors = {};
    const requiresMappedClassification = this.itemHadMappedClassificationOnLoad
      || (!this.isEdit() && !this.localDraftMode());

    if (categoryId && requiresMappedClassification && !familyId) {
      errors['ifrcFamilyRequired'] = true;
    }

    const selectedFamily = this.findLookupByValue(this.itemIfrcFamilyOptions(), familyId);
    if (selectedFamily && categoryId && !this.sameValue(selectedFamily.category_id, categoryId)) {
      errors['ifrcFamilyOutsideCategory'] = true;
    }

    const selectedReference = this.selectedReferenceOption
      ?? this.findLookupByValue(this.itemIfrcReferenceOptions(), referenceId);
    if (referenceId && !familyId) {
      errors['ifrcFamilyForReferenceRequired'] = true;
    }
    if (familyId && !referenceId) {
      errors['ifrcReferenceRequired'] = true;
    }
    if (
      selectedReference
      && familyId
      && !this.sameValue(selectedReference.ifrc_family_id, familyId)
    ) {
      errors['ifrcReferenceOutsideFamily'] = true;
    }

    return Object.keys(errors).length ? errors : null;
  }

  private setupItemIfrcSuggestion(cfg: MasterTableConfig): void {
    this.clearIfrcSuggestionState();
    this.clearAcceptedSuggestion();

    if (cfg.tableKey !== 'items') return;

    const itemNameControl = this.form.get('item_name');
    if (!itemNameControl) return;

    itemNameControl.valueChanges.pipe(
      map((v) => (typeof v === 'string' ? v.trim() : '')),
      distinctUntilChanged(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.clearAcceptedSuggestion();
      this.clearIfrcSuggestionState();
    });

    this.ifrcTrigger$.pipe(
      switchMap((itemName) => {
        if (itemName.length < 3) {
          this.ifrcSuggestion.set(null);
          this.ifrcSuggestionResolution.set(null);
          this.ifrcError.set(null);
          this.ifrcRejectedState.set(null);
          return of(null);
        }
        this.ifrcLoading.set(true);
        return this.ifrcSuggestService.suggest(itemName).pipe(
          catchError((error) => {
            this.ifrcError.set(this.getIfrcErrorMessage(error));
            return of(null);
          }),
          finalize(() => this.ifrcLoading.set(false)),
        );
      }),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((suggestion) => {
      if (!suggestion) {
        this.ifrcSuggestion.set(null);
        this.ifrcSuggestionResolution.set(null);
        const currentName = String(itemNameControl.value ?? '').trim();
        if (currentName.length < 3) {
          this.ifrcError.set(null);
        }
        return;
      }

      this.ifrcSuggestion.set(suggestion);
      this.ifrcSuggestionResolution.set(null);
      this.ifrcError.set(null);
      this.ifrcRejectedState.set(null);
      this.resolveIfrcSuggestion(suggestion);
    });
  }

  onRequestIfrcSuggestion(): void {
    const itemName = String(this.form.get('item_name')?.value ?? '').trim();
    if (itemName.length < 3) {
      this.form.get('item_name')?.markAsTouched();
      this.notify.showWarning('Enter at least 3 characters in Item Name before using Find IFRC Match.');
      return;
    }

    this.clearAcceptedSuggestion();
    this.invalidateIfrcResolveToken();
    this.ifrcRejectedState.set(null);
    this.ifrcError.set(null);
    this.ifrcTrigger$.next(itemName);
  }

  onAcceptIfrcSuggestion(): void {
    const suggestion = this.ifrcSuggestion();
    const resolved = this.ifrcSuggestionResolution();
    const family = this.getAcceptedSuggestionFamily();
    const reference = this.getAcceptedSuggestionReference();
    if (!suggestion || !family || !reference) {
      const status = resolved?.status;
      const message = reference && !family
        ? 'Resolve the suggested IFRC family before applying the classification.'
        : status === 'ambiguous'
        ? 'Select one suggested IFRC candidate before applying the classification.'
        : status === 'unresolved'
          ? 'No governed IFRC reference is available to apply from this suggestion.'
          : 'Resolve the suggested IFRC reference before applying it.';
      this.notify.showError(message);
      return;
    }

    const categoryControl = this.form.get('category_id');
    const familyControl = this.form.get('ifrc_family_id');
    const referenceControl = this.form.get('ifrc_item_ref_id');
    if (!categoryControl || !familyControl || !referenceControl) {
      return;
    }

    this.applyingTaxonomyPatch = true;

    categoryControl.patchValue(family.category_id ?? null, { emitEvent: false });
    familyControl.patchValue(family.value, { emitEvent: false });
    referenceControl.patchValue(reference.value, { emitEvent: false });
    this.selectedReferenceOption = reference;
    this.referenceSearchControl.setValue(this.getItemReferenceLabel(reference), {
      emitEvent: false,
    });

    this.writeLookup(
      'item_categories',
      this.ensureLookupItem(this.itemCategoryOptions(), {
        value: family.category_id ?? '',
        label: String(family.category_desc ?? ''),
        category_code: family.category_code,
      }),
    );
    this.writeLookup('ifrc_families', this.ensureLookupItem(this.itemIfrcFamilyOptions(), family));
    this.writeLookup(
      'ifrc_references',
      this.ensureLookupItem(this.itemIfrcReferenceOptions(), reference),
    );

    this.applyingTaxonomyPatch = false;
    this.acceptedIfrcSuggestLogId = suggestion.suggestion_id ?? null;
    this.setLocalDraftMode(false);
    this.ifrcRejectedState.set(null);
    this.syncDisplayedItemCode(reference);
    this.loadItemFamilyOptions(family.category_id, family.value);
    this.loadItemReferenceOptions(
      family.value,
      String(reference.ifrc_code ?? reference.label ?? ''),
      reference.value,
    );
    this.updateItemTaxonomyControlState();
    this.form.updateValueAndValidity({ emitEvent: false });
    this.clearSubmissionError();
    this.notify.showSuccess('Suggested IFRC classification applied.');

    this.ifrcAppliedConfirmation.set({
      ifrcCode: String(reference.ifrc_code ?? '').toUpperCase(),
      referenceLabel: String(reference.label ?? ''),
      familyLabel: String(family.label ?? family['family_label'] ?? ''),
    });

    if (this.isWizardMode() && this.currentStep() > 0) {
      this.ifrcCodeUpdatedOnStep1.set(true);
      if (this._ifrcBadgeTimeout) {
        clearTimeout(this._ifrcBadgeTimeout);
      }
      this._ifrcBadgeTimeout = setTimeout(() => this.ifrcCodeUpdatedOnStep1.set(false), 4000);
    }
  }

  onSelectSuggestionCandidate(candidate: SuggestedIfrcCandidate): void {
    this.selectedSuggestionCandidateId.set(this.toRecordIdentifier(candidate.reference.value));
  }

  onRejectIfrcSuggestion(): void {
    this.clearAcceptedSuggestion();
    this.clearIfrcSuggestionState();
    this.ifrcRejectedState.set(this.isEdit() ? 'edit' : 'create');
  }

  getWizardContextIdentity(): { name: string; code: string } | null {
    const name = String(this.form.get('item_name')?.value ?? '').trim();
    if (!name) return null;
    const code = String(this.form.get('item_code')?.value ?? '').trim();
    return { name, code };
  }

  onChangeIfrcApplied(): void {
    this.ifrcAppliedConfirmation.set(null);
  }

  toggleCandidateExpanded(id: string | number): void {
    const current = new Set(this.expandedCandidateIds());
    if (current.has(id)) {
      current.delete(id);
    } else {
      current.add(id);
    }
    this.expandedCandidateIds.set(current);
  }

  isCandidateExpanded(id: string | number): boolean {
    return this.expandedCandidateIds().has(id);
  }

  getPreviewItemCode(candidate: SuggestedIfrcCandidate): string {
    return String(candidate.reference.ifrc_code ?? '').toUpperCase();
  }

  getScoreIndicatorLevel(candidate: SuggestedIfrcCandidate): 'high' | 'medium' | 'low' {
    if (candidate.score >= 0.8) return 'high';
    if (candidate.score >= 0.5) return 'medium';
    return 'low';
  }

  onChooseIfrcReferenceManually(): void {
    this.setLocalDraftMode(false);
    this.ifrcRejectedState.set(null);
    this.form.get('ifrc_family_id')?.markAsTouched();
    this.form.get('ifrc_item_ref_id')?.markAsTouched();
  }

  onKeepEditingAndTryAgain(): void {
    this.ifrcRejectedState.set(null);
  }

  onSaveAsLocalDraft(): void {
    if (!this.isItemRecord() || this.isEdit()) {
      return;
    }

    const familyControl = this.form.get('ifrc_family_id');
    const referenceControl = this.form.get('ifrc_item_ref_id');

    this.applyingTaxonomyPatch = true;
    familyControl?.patchValue(null, { emitEvent: false });
    referenceControl?.patchValue(null, { emitEvent: false });
    this.referenceSearchControl.setValue('', { emitEvent: false });
    this.selectedReferenceOption = null;
    this.applyingTaxonomyPatch = false;

    this.clearAcceptedSuggestion();
    this.clearIfrcSuggestionState();
    this.setLocalDraftMode(true);
    this.syncDisplayedItemCode();
    this.updateItemTaxonomyControlState();
    this.form.updateValueAndValidity({ emitEvent: false });
    this.clearSubmissionError();
    this.notify.showWarning('Local draft mode enabled. Choose a Level 1 category and enter a Local Item Code before saving.');
  }

  onKeepCurrentClassification(): void {
    this.ifrcRejectedState.set(null);
  }

  onChooseAnotherIfrcReference(): void {
    this.ifrcRejectedState.set(null);
    this.setLocalDraftMode(false);
    this.onClearIfrcReference();
    this.form.get('ifrc_item_ref_id')?.markAsTouched();
    this.notify.showWarning('Search and choose a different IFRC reference to continue.');
  }

  onSelectIfrcReference(reference: IfrcReferenceLookup): void {
    const control = this.form.get('ifrc_item_ref_id');
    if (!control) {
      return;
    }

    this.applyingTaxonomyPatch = true;
    control.patchValue(reference.value, { emitEvent: false });
    this.selectedReferenceOption = reference;
    this.referenceSearchControl.setValue(this.getItemReferenceLabel(reference), {
      emitEvent: false,
    });
    this.writeLookup('ifrc_references', this.ensureLookupItem(this.itemIfrcReferenceOptions(), reference));
    this.applyingTaxonomyPatch = false;
    this.setLocalDraftMode(false);
    this.ifrcRejectedState.set(null);
    this.clearAcceptedSuggestion();
    this.clearIfrcSuggestionState();
    this.syncDisplayedItemCode(reference);
    this.updateItemTaxonomyControlState();
    this.form.updateValueAndValidity({ emitEvent: false });
    this.clearSubmissionError();
  }

  onClearIfrcReference(): void {
    const control = this.form.get('ifrc_item_ref_id');
    if (!control) {
      return;
    }

    this.applyingTaxonomyPatch = true;
    control.patchValue(null, { emitEvent: false });
    this.referenceSearchControl.setValue('', { emitEvent: false });
    this.selectedReferenceOption = null;
    this.applyingTaxonomyPatch = false;
    this.clearAcceptedSuggestion();
    this.clearIfrcSuggestionState();
    this.syncDisplayedItemCode();
    this.updateItemTaxonomyControlState();
    this.form.updateValueAndValidity({ emitEvent: false });
    this.clearSubmissionError();
  }

  private getIfrcErrorMessage(error: unknown): string {
    if (typeof error === 'string' && error.trim()) {
      return error.trim();
    }

    const errObj = error as {
      message?: unknown;
      status?: unknown;
      error?: unknown;
    };
    const payload = errObj?.error;
    if (payload && typeof payload === 'object') {
      const payloadObj = payload as Record<string, unknown>;
      const detail = payloadObj['detail'];
      if (typeof detail === 'string' && detail.trim()) {
        return detail.trim();
      }
      const payloadError = payloadObj['error'];
      if (typeof payloadError === 'string' && payloadError.trim()) {
        return payloadError.trim();
      }
      const payloadMessage = payloadObj['message'];
      if (typeof payloadMessage === 'string' && payloadMessage.trim()) {
        return payloadMessage.trim();
      }
    }

    if (typeof errObj?.message === 'string' && errObj.message.trim()) {
      return errObj.message.trim();
    }
    if (typeof errObj?.status === 'number') {
      return `IFRC suggestion request failed (${errObj.status}).`;
    }
    return 'Failed to load IFRC suggestion.';
  }

  private readLookup<T extends LookupItem>(lookupKey: string): T[] {
    return (this.lookups()[lookupKey] ?? []) as T[];
  }

  private beginLookupRequest(lookupKey: string): number {
    const nextRequestId = (this.lookupRequestIds[lookupKey] ?? 0) + 1;
    this.lookupRequestIds[lookupKey] = nextRequestId;
    return nextRequestId;
  }

  private isCurrentLookupRequest(lookupKey: string, requestId?: number): boolean {
    return requestId == null || this.lookupRequestIds[lookupKey] === requestId;
  }

  private writeLookup(lookupKey: string, items: LookupItem[], requestId?: number): void {
    if (!this.isCurrentLookupRequest(lookupKey, requestId)) {
      return;
    }
    this.lookups.set({
      ...this.lookups(),
      [lookupKey]: items,
    });
  }

  private setLookupLoading(lookupKey: string, isLoading: boolean, requestId?: number): void {
    if (!this.isCurrentLookupRequest(lookupKey, requestId)) {
      return;
    }
    this.lookupLoading.set({
      ...this.lookupLoading(),
      [lookupKey]: isLoading,
    });
  }

  private setLookupError(lookupKey: string, message: string | null, requestId?: number): void {
    if (!this.isCurrentLookupRequest(lookupKey, requestId)) {
      return;
    }
    const nextErrors = { ...this.lookupErrors() };
    if (message) {
      nextErrors[lookupKey] = message;
    } else {
      delete nextErrors[lookupKey];
    }
    this.lookupErrors.set(nextErrors);
  }

  private sameValue(left: unknown, right: unknown): boolean {
    if ((left == null || left === '') && (right == null || right === '')) {
      return true;
    }
    return String(left) === String(right);
  }

  private findLookupByValue<T extends LookupItem>(
    items: T[],
    value: unknown,
    lookupKey?: string,
    requestId?: number,
  ): T | null {
    if (lookupKey && !this.isCurrentLookupRequest(lookupKey, requestId)) {
      return null;
    }
    if (value == null || value === '') {
      return null;
    }
    return items.find((item) => this.sameValue(item.value, value)) ?? null;
  }

  private ensureLookupItem<T extends LookupItem>(items: T[], item: T): T[] {
    const existing = this.findLookupByValue(items, item.value);
    if (existing) {
      return items;
    }
    return [item, ...items];
  }

  private shouldPreserveInactiveItemTaxonomy(
    preserveValue: string | number | null,
  ): boolean {
    return this.isEdit() && preserveValue !== null && preserveValue !== undefined && preserveValue !== '';
  }

  private readLoadedRecordText(field: string): string | undefined {
    const rawValue = this.loadedRecordSnapshot?.[field];
    const text = String(rawValue ?? '').trim();
    return text || undefined;
  }

  private buildPreservedItemFamilyOption(
    preserveValue: string | number | null,
  ): IfrcFamilyLookup | null {
    const savedValue = this.loadedRecordSnapshot?.['ifrc_family_id'];
    if (!this.sameValue(savedValue, preserveValue)) {
      return null;
    }

    const label = this.readLoadedRecordText('ifrc_family_label');
    if (!label) {
      return null;
    }

    return {
      value: savedValue as string | number,
      label,
      family_code: this.readLoadedRecordText('ifrc_family_code'),
      group_code: this.readLoadedRecordText('ifrc_group_code'),
      group_label: this.readLoadedRecordText('ifrc_group_label'),
      category_id: this.loadedRecordSnapshot?.['category_id'] as string | number | undefined,
      category_code: this.readLoadedRecordText('category_code'),
      category_desc: this.readLoadedRecordText('category_desc'),
    };
  }

  private buildPreservedItemReferenceOption(
    preserveValue: string | number | null,
  ): IfrcReferenceLookup | null {
    const savedValue = this.loadedRecordSnapshot?.['ifrc_item_ref_id'];
    if (!this.sameValue(savedValue, preserveValue)) {
      return null;
    }

    const label = this.readLoadedRecordText('ifrc_reference_desc')
      ?? this.readLoadedRecordText('ifrc_reference_code');
    if (!label) {
      return null;
    }

    return {
      value: savedValue as string | number,
      label,
      ifrc_code: this.readLoadedRecordText('ifrc_reference_code'),
      ifrc_family_id: this.loadedRecordSnapshot?.['ifrc_family_id'] as string | number | undefined,
      family_code: this.readLoadedRecordText('ifrc_family_code'),
      family_label: this.readLoadedRecordText('ifrc_family_label'),
      category_code: this.readLoadedRecordText('ifrc_reference_category_code'),
      category_label: this.readLoadedRecordText('ifrc_reference_category_label'),
      spec_segment: this.readLoadedRecordText('ifrc_reference_spec_segment'),
    };
  }

  private syncDisplayedItemCode(reference: IfrcReferenceLookup | null = this.selectedReferenceOption): void {
    const referenceCode = String(reference?.ifrc_code ?? '').trim().toUpperCase();
    if (referenceCode) {
      this.setDisplayedItemCode(referenceCode);
      return;
    }

    if (this.isEdit() && this.itemCodeFallbackValue) {
      this.setDisplayedItemCode(this.itemCodeFallbackValue);
      return;
    }

    this.setDisplayedItemCode(null);
  }

  private setDisplayedItemCode(itemCode: string | null): void {
    const itemCodeControl = this.form.get('item_code');
    if (!itemCodeControl) {
      return;
    }

    const normalizedValue = String(itemCode ?? '').trim().toUpperCase();
    itemCodeControl.setValue(normalizedValue || null, { emitEvent: false });
  }

  private updateItemTaxonomyControlState(): void {
    const categoryControl = this.form.get('category_id');
    const familyControl = this.form.get('ifrc_family_id');
    const referenceControl = this.form.get('ifrc_item_ref_id');
    if (!categoryControl || !familyControl || !referenceControl) {
      return;
    }

    const hasCategory = categoryControl.value != null && categoryControl.value !== '';
    const hasFamily = familyControl.value != null && familyControl.value !== '';

    if (!hasCategory || this.isLookupLoading('ifrc_families')) {
      familyControl.disable({ emitEvent: false });
    } else {
      familyControl.enable({ emitEvent: false });
    }

    if (!hasFamily || this.isLookupLoading('ifrc_references')) {
      referenceControl.disable({ emitEvent: false });
      this.referenceSearchControl.disable({ emitEvent: false });
    } else {
      referenceControl.enable({ emitEvent: false });
      this.referenceSearchControl.enable({ emitEvent: false });
    }
  }

  private loadLookups(cfg: MasterTableConfig): void {
    const lookupFields = cfg.formFields.filter((field) => {
      if (field.type !== 'lookup' || !field.lookupTable) {
        return false;
      }

      if (cfg.tableKey !== 'items') {
        return true;
      }

      return !['item_categories', 'ifrc_families', 'ifrc_references'].includes(field.lookupTable);
    });
    const lookupTables = new Map<string, { label: string; field: MasterFieldConfig }>();
    for (const field of lookupFields) {
      const existing = lookupTables.get(field.lookupTable!);
      lookupTables.set(field.lookupTable!, {
        label: existing?.label ?? field.label,
        field: this.hasLookupNoneOption(field) ? field : existing?.field ?? field,
      });
    }
    if (cfg.tableKey === 'items') {
      this.loadItemCategoryOptions();
      this.writeLookup('ifrc_families', []);
      this.writeLookup('ifrc_references', []);
    }

    this.lookupErrors.set({});

    for (const [tableKey, { label, field }] of lookupTables.entries()) {
      // For the IFRC Item Reference form, load families with group context
      // so users can see which product group each family belongs to.
      if (tableKey === 'ifrc_families' && cfg.tableKey === 'ifrc_item_references') {
        this.loadIfrcFamilyLookupWithGroupContext();
        continue;
      }

      this.setLookupLoading(tableKey, true);
      this.service.lookup(tableKey).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: (items) => {
          this.writeLookup(tableKey, this.withLookupNoneOption(field, items));
          this.setLookupLoading(tableKey, false);
          this.setLookupError(tableKey, null);
        },
        error: () => {
          this.writeLookup(tableKey, []);
          this.setLookupLoading(tableKey, false);
          this.setLookupError(tableKey, `Failed to load ${label} options.`);
        },
      });
    }
  }

  private loadIfrcFamilyLookupWithGroupContext(): void {
    this.setLookupLoading('ifrc_families', true);
    this.service.lookupIfrcFamilies().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (items) => {
        const enriched: LookupItem[] = items.map((item) => ({
          ...item,
          label: `${item.label} (${item['group_code']} — ${item['group_label']})`,
        }));
        this.writeLookup('ifrc_families', enriched);
        this.setLookupLoading('ifrc_families', false);
        this.setLookupError('ifrc_families', null);
      },
      error: () => {
        this.writeLookup('ifrc_families', []);
        this.setLookupLoading('ifrc_families', false);
        this.setLookupError('ifrc_families', 'Failed to load IFRC Family options.');
      },
    });
  }

  private loadItemCategoryOptions(includeValue?: string | number | null): void {
    this.setLookupLoading('item_categories', true);
    this.service.lookupItemCategories({
      includeValue: includeValue == null || includeValue === '' ? null : includeValue,
    }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (items) => {
        this.writeLookup('item_categories', items);
        this.setLookupLoading('item_categories', false);
        this.setLookupError('item_categories', null);
        this.updateItemTaxonomyControlState();
        this.form.updateValueAndValidity({ emitEvent: false });
      },
      error: () => {
        this.writeLookup('item_categories', []);
        this.setLookupLoading('item_categories', false);
        this.setLookupError('item_categories', 'Failed to load Level 1 category options.');
        this.updateItemTaxonomyControlState();
      },
    });
  }

  private loadItemFamilyOptions(
    categoryId: string | number | null | undefined,
    preserveValue: string | number | null = null,
  ): void {
    const lookupKey = 'ifrc_families';
    const requestId = this.beginLookupRequest(lookupKey);
    if (categoryId == null || categoryId === '') {
      this.writeLookup(lookupKey, [], requestId);
      this.setLookupLoading(lookupKey, false, requestId);
      this.updateItemTaxonomyControlState();
      this.form.updateValueAndValidity({ emitEvent: false });
      return;
    }

    this.setLookupLoading(lookupKey, true, requestId);
    this.updateItemTaxonomyControlState();
    const shouldPreserveInactive = this.shouldPreserveInactiveItemTaxonomy(preserveValue);
    this.service.lookupIfrcFamilies({
      categoryId,
      includeValue: shouldPreserveInactive ? preserveValue : null,
    }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (items) => {
        if (!this.isCurrentLookupRequest(lookupKey, requestId)) {
          return;
        }
        const familyControl = this.form.get('ifrc_family_id');
        const selectedValue = preserveValue ?? familyControl?.value;
        const preservedFamily = this.buildPreservedItemFamilyOption(
          selectedValue as string | number | null,
        );
        const nextItems = preservedFamily
          ? this.ensureLookupItem(items, preservedFamily)
          : items;

        this.writeLookup(lookupKey, nextItems, requestId);
        this.setLookupLoading(lookupKey, false, requestId);
        this.setLookupError(lookupKey, null, requestId);

        if (
          familyControl
          && selectedValue
          && !this.findLookupByValue(nextItems, selectedValue, lookupKey, requestId)
        ) {
          familyControl.patchValue(null, { emitEvent: false });
        }
        this.updateItemTaxonomyControlState();
        this.form.updateValueAndValidity({ emitEvent: false });
      },
      error: () => {
        if (!this.isCurrentLookupRequest(lookupKey, requestId)) {
          return;
        }
        this.writeLookup(lookupKey, [], requestId);
        this.setLookupLoading(lookupKey, false, requestId);
        this.setLookupError(lookupKey, 'Failed to load IFRC family options.', requestId);
        this.updateItemTaxonomyControlState();
      },
    });
  }

  private loadItemReferenceOptions(
    familyId: string | number | null | undefined,
    search = '',
    preserveValue: string | number | null = null,
  ): void {
    const lookupKey = 'ifrc_references';
    const requestId = this.beginLookupRequest(lookupKey);
    if (familyId == null || familyId === '') {
      this.writeLookup(lookupKey, [], requestId);
      this.setLookupLoading(lookupKey, false, requestId);
      this.updateItemTaxonomyControlState();
      this.form.updateValueAndValidity({ emitEvent: false });
      return;
    }

    this.setLookupLoading(lookupKey, true, requestId);
    this.updateItemTaxonomyControlState();
    const shouldPreserveInactive = this.shouldPreserveInactiveItemTaxonomy(preserveValue);
    this.service.lookupIfrcReferences({
      ifrcFamilyId: familyId,
      search: search || undefined,
      includeValue: shouldPreserveInactive ? preserveValue : null,
      limit: 50,
    }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (items) => {
        if (!this.isCurrentLookupRequest(lookupKey, requestId)) {
          return;
        }
        const referenceControl = this.form.get('ifrc_item_ref_id');
        const selectedValue = preserveValue ?? referenceControl?.value;
        const preservedReference = this.buildPreservedItemReferenceOption(
          selectedValue as string | number | null,
        );
        const nextItems = preservedReference
          ? this.ensureLookupItem(items, preservedReference)
          : items;
        const selectedReference = this.findLookupByValue(
          nextItems,
          selectedValue,
          lookupKey,
          requestId,
        );

        this.writeLookup(lookupKey, nextItems, requestId);
        this.setLookupLoading(lookupKey, false, requestId);
        this.setLookupError(lookupKey, null, requestId);

        if (referenceControl && selectedValue && !selectedReference) {
          referenceControl.patchValue(null, { emitEvent: false });
          if (!this.applyingTaxonomyPatch) {
            this.selectedReferenceOption = null;
          }
        }
        if (selectedReference) {
          this.selectedReferenceOption = selectedReference;
        }
        this.syncDisplayedItemCode(selectedReference ?? this.selectedReferenceOption);
        this.updateItemTaxonomyControlState();
        this.form.updateValueAndValidity({ emitEvent: false });
      },
      error: () => {
        if (!this.isCurrentLookupRequest(lookupKey, requestId)) {
          return;
        }
        this.writeLookup(lookupKey, [], requestId);
        this.setLookupLoading(lookupKey, false, requestId);
        this.setLookupError(lookupKey, 'Failed to load IFRC reference options.', requestId);
        this.updateItemTaxonomyControlState();
      },
    });
  }

  private resolveIfrcSuggestion(suggestion: IFRCSuggestion): void {
    const resolveToken = ++this.currentIfrcResolveToken;
    const candidateRows = suggestion.candidates ?? [];
    const familySearch = String(
      suggestion.family_code
      ?? candidateRows[0]?.family_code
      ?? '',
    ).trim();
    const familyIds = [
      this.toRecordIdentifier(suggestion.ifrc_family_id),
      ...candidateRows
        .map((candidate) => this.toRecordIdentifier(candidate.ifrc_family_id)),
    ].filter((familyId): familyId is string | number => familyId != null);
    const distinctFamilyIds = [...new Set(familyIds.map((familyId) => String(familyId)))];
    const shouldLookupAllFamilies = distinctFamilyIds.length > 1 || !familySearch;
    const fallbackResolution = this.buildSuggestionResolutionState(suggestion, []);
    this.selectedSuggestionCandidateId.set(null);
    const applyResolution = (resolved: ResolvedIfrcSuggestion): void => {
      if (resolveToken !== this.currentIfrcResolveToken) {
        return;
      }
      this.ifrcSuggestionResolution.set(resolved);
    };

    if (!familySearch && distinctFamilyIds.length === 0) {
      applyResolution({
        ...fallbackResolution,
        warning: 'Suggestion did not include a resolvable IFRC family.',
      });
      return;
    }

    const familyLookup$ = shouldLookupAllFamilies
      ? this.service.lookupIfrcFamilies()
      : this.service.lookupIfrcFamilies({ search: familySearch });

    familyLookup$.pipe(
      switchMap((families) => this.resolveSuggestionAgainstLookups(suggestion, families)),
      catchError(() => of({
        ...fallbackResolution,
        warning: 'Failed to resolve the IFRC suggestion against the active taxonomy.',
      } satisfies ResolvedIfrcSuggestion)),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((resolved) => applyResolution(resolved));
  }

  private resolveSuggestionAgainstLookups(
    suggestion: IFRCSuggestion,
    families: IfrcFamilyLookup[],
  ) {
    const resolved = this.buildSuggestionResolutionState(suggestion, families);
    const hasResolvedFamily = resolved.family != null
      || resolved.candidates.some((candidate) => candidate.family != null);
    const missingFamilyWarning = hasResolvedFamily
      ? null
      : 'Suggestion could not be matched to an active IFRC family.';
    const resolvedReferenceId = this.toRecordIdentifier(suggestion.resolved_ifrc_item_ref_id);
    const needsResolvedReferenceLookup = resolved.status === 'resolved'
      && resolvedReferenceId != null
      && resolved.reference == null;

    if (!needsResolvedReferenceLookup) {
      return of(missingFamilyWarning ? {
        ...resolved,
        warning: missingFamilyWarning,
      } satisfies ResolvedIfrcSuggestion : resolved);
    }

    const resolvedFamilyId = this.toRecordIdentifier(suggestion.ifrc_family_id)
      ?? resolved.family?.value
      ?? resolved.candidates.find((candidate) => candidate.family != null)?.family?.value
      ?? null;

    if (resolvedFamilyId == null) {
      return of({
        ...resolved,
        warning: missingFamilyWarning ?? 'Suggestion could not be matched to an active IFRC family.',
      } satisfies ResolvedIfrcSuggestion);
    }

    const referenceSearch = String(suggestion.ifrc_code ?? suggestion.ifrc_description ?? '').trim();
    return this.service.lookupIfrcReferences({
      ifrcFamilyId: resolvedFamilyId,
      search: referenceSearch || undefined,
    }).pipe(
      map((references) => {
        const resolvedReference = this.findResolvedSuggestionReference(references, suggestion);
        if (!resolvedReference) {
          return {
            ...resolved,
            warning: 'Suggestion could not be matched to an active IFRC reference.',
          } satisfies ResolvedIfrcSuggestion;
        }

        const resolvedFamily = resolved.family
          ?? this.findLookupByValue(families, resolvedFamilyId)
          ?? this.findSuggestedFamily(
            families,
            resolvedFamilyId,
            suggestion.family_code,
            suggestion.group_code,
          );

        return {
          ...resolved,
          family: resolvedFamily ?? null,
          reference: resolvedReference,
          warning: missingFamilyWarning,
          directAcceptAllowed: resolvedFamily != null,
        } satisfies ResolvedIfrcSuggestion;
      }),
      catchError(() => of({
        ...resolved,
        warning: 'Failed to resolve the IFRC suggestion against the active taxonomy.',
      } satisfies ResolvedIfrcSuggestion)),
    );
  }

  private buildSuggestionResolutionState(
    suggestion: IFRCSuggestion,
    families: IfrcFamilyLookup[],
  ): ResolvedIfrcSuggestion {
    const candidates = this.mapSuggestionCandidates(suggestion.candidates ?? [], families);
    const resolutionStatus = suggestion.resolution_status
      ?? (suggestion.resolved_ifrc_item_ref_id != null
        ? 'resolved'
        : (suggestion.candidate_count ?? 0) > 0
          ? 'ambiguous'
          : 'unresolved');
    const resolvedReferenceId = this.toRecordIdentifier(suggestion.resolved_ifrc_item_ref_id);
    const resolvedCandidate = resolvedReferenceId != null
      ? candidates.find((candidate) => this.sameValue(candidate.reference.value, resolvedReferenceId)) ?? null
      : resolutionStatus === 'resolved' && candidates.length === 1
        ? candidates[0]
        : null;
    const explanation = String(suggestion.resolution_explanation ?? '').trim() || null;

    return {
      status: resolutionStatus,
      family: resolvedCandidate?.family ?? null,
      reference: resolvedCandidate?.reference ?? null,
      candidates,
      warning: null,
      explanation,
      directAcceptAllowed: resolutionStatus === 'resolved' && resolvedCandidate != null,
      autoHighlightCandidateId: this.toRecordIdentifier(suggestion.auto_highlight_candidate_id),
    };
  }

  private findResolvedSuggestionReference(
    references: IfrcReferenceLookup[],
    suggestion: IFRCSuggestion,
  ): IfrcReferenceLookup | null {
    const resolvedReferenceId = this.toRecordIdentifier(suggestion.resolved_ifrc_item_ref_id);
    if (resolvedReferenceId != null) {
      const exactIdMatch = references.find((reference) => this.sameValue(reference.value, resolvedReferenceId));
      if (exactIdMatch) {
        return exactIdMatch;
      }
    }

    const suggestedCode = String(suggestion.ifrc_code ?? '').trim().toUpperCase();
    if (suggestedCode) {
      const exactCodeMatch = references.find((reference) => (
        String(reference.ifrc_code ?? '').trim().toUpperCase() === suggestedCode
      ));
      if (exactCodeMatch) {
        return exactCodeMatch;
      }
    }

    const suggestedDescription = String(suggestion.ifrc_description ?? '').trim().toUpperCase();
    if (!suggestedDescription) {
      return null;
    }

    return references.find((reference) => (
      String(reference.label ?? '').trim().toUpperCase() === suggestedDescription
    )) ?? null;
  }

  private mapSuggestionCandidates(
    candidateRows: IFRCSuggestionCandidate[],
    families: IfrcFamilyLookup[],
  ): SuggestedIfrcCandidate[] {
    return candidateRows
      .map((candidate) => ({
        family: this.findSuggestedFamily(
          families,
          candidate.ifrc_family_id,
          candidate.family_code,
          candidate.group_code,
        ),
        reference: this.toSuggestedReferenceLookup(candidate),
        rank: Number(candidate.rank ?? 0) || 0,
        score: Number(candidate.score ?? 0) || 0,
        autoHighlight: candidate.auto_highlight === true,
        matchReasons: candidate.match_reasons ?? [],
      }))
      .sort((left, right) => left.rank - right.rank);
  }

  private toSuggestedReferenceLookup(candidate: IFRCSuggestionCandidate): IfrcReferenceLookup {
    return {
      value: candidate.ifrc_item_ref_id,
      label: candidate.reference_desc,
      ifrc_code: candidate.ifrc_code,
      ifrc_family_id: candidate.ifrc_family_id,
      family_code: candidate.family_code,
      family_label: candidate.family_label,
      category_code: candidate.category_code,
      category_label: candidate.category_label,
      spec_segment: candidate.spec_segment ?? '',
      size_weight: candidate.size_weight ?? '',
      form: candidate.form ?? '',
      material: candidate.material ?? '',
    };
  }

  private findSuggestedFamily(
    families: IfrcFamilyLookup[],
    familyId: unknown,
    familyCode: unknown,
    groupCode: unknown,
  ): IfrcFamilyLookup | null {
    const suggestionFamilyId = this.toRecordIdentifier(familyId);
    if (suggestionFamilyId != null) {
      const exactFamilyIdMatch = families.find((family) => this.sameValue(family.value, suggestionFamilyId));
      if (exactFamilyIdMatch) {
        return exactFamilyIdMatch;
      }
    }

    const normalizedFamilyCode = String(familyCode ?? '').trim().toUpperCase();
    const normalizedGroupCode = String(groupCode ?? '').trim().toUpperCase();

    return families.find((family) => {
      const sameFamilyCode = String(family.family_code ?? '').trim().toUpperCase() === normalizedFamilyCode;
      const sameGroupCode = !normalizedGroupCode
        || String(family.group_code ?? '').trim().toUpperCase() === normalizedGroupCode;
      return sameFamilyCode && sameGroupCode;
    }) ?? null;
  }

  private clearAcceptedSuggestion(): void {
    this.acceptedIfrcSuggestLogId = null;
    this.selectedSuggestionCandidateId.set(null);
    this.ifrcAppliedConfirmation.set(null);
    this.ifrcCodeUpdatedOnStep1.set(false);
    this.expandedCandidateIds.set(new Set());
  }

  private clearIfrcSuggestionState(): void {
    this.invalidateIfrcResolveToken();
    this.ifrcSuggestion.set(null);
    this.ifrcSuggestionResolution.set(null);
    this.ifrcError.set(null);
    this.ifrcRejectedState.set(null);
  }

  private invalidateIfrcResolveToken(): void {
    this.currentIfrcResolveToken += 1;
  }

  private setLocalDraftMode(isActive: boolean): void {
    this.localDraftMode.set(isActive);
    this.updateLocalDraftFieldValidators();
  }

  private updateLocalDraftFieldValidators(): void {
    const control = this.form.get('legacy_item_code');
    const field = this.config()?.formFields.find((entry) => entry.field === 'legacy_item_code');
    if (!control || !field) {
      return;
    }

    const validators = [];
    if (this.localDraftMode()) {
      validators.push(Validators.required);
    }
    if (field.maxLength) {
      validators.push(Validators.maxLength(field.maxLength));
    }
    if (field.pattern) {
      validators.push(Validators.pattern(field.pattern));
    }

    control.setValidators(validators);
    control.updateValueAndValidity({ emitEvent: false });
  }

  private loadRecord(): void {
    const cfg = this.config();
    if (!cfg || !this.pk()) return;

    this.isLoading.set(true);
    this.service.get(cfg.tableKey, this.pk()!).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: res => {
        const record = res.record;
        this.versionNbr = typeof record['version_nbr'] === 'number'
          ? record['version_nbr']
          : null;
        this.catalogEditGuidance.set(res.edit_guidance ?? this.getDefaultCatalogEditGuidance(cfg.tableKey));
        this.catalogSuggestion.set(null);
        this.catalogAssistError.set(null);
        this.replacementMode.set(false);
        this.retireOriginalOnReplacement.set(false);
        this.loadedRecordSnapshot = { ...record };
        this.itemCodeFallbackValue = String(record['item_code'] ?? '').trim() || null;
        this.legacyItemCodeValue = String(record['legacy_item_code'] ?? '').trim() || null;

        for (const field of cfg.formFields) {
          const control = this.form.get(field.field);
          if (control && record[field.field] !== undefined) {
            control.setValue(this.toLookupControlValue(field, record[field.field]), { emitEvent: false });
          }
        }

        if (cfg.tableKey === 'items') {
          const categoryId = record['category_id'] as string | number | null | undefined;
          const familyId = record['ifrc_family_id'] as string | number | null | undefined;
          const referenceId = record['ifrc_item_ref_id'] as string | number | null | undefined;
          this.itemHadMappedClassificationOnLoad = referenceId != null && referenceId !== '';
          this.setLocalDraftMode(false);
          this.ifrcRejectedState.set(null);

          this.loadItemCategoryOptions(categoryId);
          this.loadItemFamilyOptions(categoryId, familyId ?? null);
          this.loadItemReferenceOptions(
            familyId,
            String(record['ifrc_reference_code'] ?? record['ifrc_reference_desc'] ?? ''),
            referenceId ?? null,
          );

          if (referenceId) {
            this.selectedReferenceOption = {
              value: referenceId,
              label: String(record['ifrc_reference_desc'] ?? ''),
              ifrc_code: String(record['ifrc_reference_code'] ?? ''),
              ifrc_family_id: familyId ?? '',
              family_label: String(record['ifrc_family_label'] ?? ''),
              category_code: String(record['ifrc_reference_category_code'] ?? ''),
              category_label: String(record['ifrc_reference_category_label'] ?? ''),
              spec_segment: String(record['ifrc_reference_spec_segment'] ?? ''),
            };
            this.referenceSearchControl.setValue(
              this.getItemReferenceLabel(this.selectedReferenceOption!),
              { emitEvent: false },
            );
          } else {
            this.selectedReferenceOption = null;
            this.referenceSearchControl.setValue('', { emitEvent: false });
          }
          this.syncDisplayedItemCode();

          // Load UOM conversions (non-default rows only)
          const uomOptions = record['uom_options'] as
            { uom_code: string; conversion_factor: number; is_default?: boolean }[] | undefined;
          if (Array.isArray(uomOptions)) {
            this.itemUomConversions.set(
              uomOptions
                .filter(opt => !opt.is_default)
                .map(opt => ({ uom_code: opt.uom_code, conversion_factor: opt.conversion_factor })),
            );
          } else {
            this.itemUomConversions.set([]);
          }
          this.previousDefaultUom = record['default_uom_code'] as string ?? null;
        }

        this.applyGovernedCatalogFieldState();
        this.updateItemTaxonomyControlState();
        this.form.updateValueAndValidity({ emitEvent: false });
        this.form.markAsPristine();
        this.loadStorageAssignmentOptionsForCurrentItem();

        this.isLoading.set(false);
        this.maybePromptGovernedEditWarning();
      },
      error: () => {
        this.notify.showError('Failed to load record.');
        this.navigateBack();
      },
    });
  }

  onSave(): void {
    this.clearSubmissionError();
    this.form.updateValueAndValidity({ emitEvent: false });

    if (this.form.hasError('invalidItemUomConversions')) {
      this.form.markAllAsTouched();
      this.refreshFormErrorSummary();
      this.handleInvalidItemUomConversionSubmission();
      if (this.isWizardMode()) {
        this.navigateToFirstInvalidStep();
      }
      this.focusErrorSummaryAfterRender();
      return;
    }

    if (!this.form.valid) {
      this.form.markAllAsTouched();
      this.refreshFormErrorSummary();
      if (this.isWizardMode()) {
        this.navigateToFirstInvalidStep();
      }
      this.focusErrorSummaryAfterRender();
      return;
    }

    const cfg = this.config();
    if (!cfg) return;

    const replacementTableKey = this.getReplacementTableKey();
    const isReplacementSave = replacementTableKey != null
      && this.replacementMode()
      && this.isEdit()
      && this.pk() != null;

    if (isReplacementSave && !this.form.dirty) {
      this.notify.showWarning('Update the replacement fields before saving the replacement draft.');
      return;
    }

    let rawData: MasterRecord;
    try {
      rawData = this.buildPreparedFormPayload(cfg);
    } catch (error) {
      if (error instanceof ItemUomConversionValidationError) {
        this.form.markAllAsTouched();
        this.refreshFormErrorSummary();
        this.handleInvalidItemUomConversionSubmission(error.details);
        if (this.isWizardMode()) {
          this.navigateToFirstInvalidStep();
        }
        this.focusErrorSummaryAfterRender();
        return;
      }
      throw error;
    }

    this.isSaving.set(true);

    const obs$ = isReplacementSave
      ? this.service.createCatalogReplacement(
          replacementTableKey,
          this.pk()!,
          rawData,
          this.retireOriginalOnReplacement(),
        )
      : this.isEdit()
        ? this.service.update(cfg.tableKey, this.pk()!, {
            ...rawData,
            ...(this.versionNbr != null ? { version_nbr: this.versionNbr } : {}),
          })
        : this.service.create(cfg.tableKey, rawData);

    obs$.pipe(
      finalize(() => this.isSaving.set(false)),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        this.clearSubmissionError();
        this.service.clearLookupCache(cfg.tableKey);

        const newPk = res.record?.[cfg.pkField] ?? null;
        if (isReplacementSave) {
          this.replacementMode.set(false);
          this.retireOriginalOnReplacement.set(false);
          this.notify.showSuccess('Replacement record created.');
          this.showCatalogWarnings(res.warnings);
          if (newPk != null && newPk !== '') {
            this.router.navigate(['/master-data', cfg.routePath, newPk]);
          } else {
            this.notify.showWarning('Replacement saved, but no primary key was returned.');
            this.navigateBack();
          }
          return;
        }

        this.notify.showSuccess(this.isEdit() ? 'Record updated.' : 'Record created.');
        if (this.isEdit()) {
          this.navigateBack();
        } else if (newPk != null && newPk !== '') {
          this.router.navigate(['/master-data', cfg.routePath, newPk]);
        } else {
          this.notify.showWarning('Record saved, but no primary key was returned.');
          this.navigateBack();
        }
      },
      error: (err) => {
        if (err.status === 400 && err.error?.errors) {
          const errors = err.error.errors as Record<string, string>;
          this.applyServerErrors(errors);

          const classificationErrorFields = ['category_id', 'ifrc_family_id', 'ifrc_item_ref_id', 'item_code'];
          const classificationDetails = Object.entries(errors)
            .filter(([field]) => classificationErrorFields.includes(field))
            .map(([, message]) => message);
          if (classificationDetails.length > 0) {
            this.setSubmissionError(
              'Please review the item classification and canonical item code details.',
              classificationDetails,
              'submitFailure',
            );
          } else if (this.isGovernedCatalogAuthoringTable()) {
            this.setSubmissionError(
              isReplacementSave
                ? 'Please review the governed replacement draft before saving.'
                : 'Please review the governed catalog fields before saving.',
              Object.values(errors),
              'submitFailure',
            );
          }
          this.notify.showWarning('Please fix the validation errors.');
          if (this.isWizardMode()) {
            this.navigateToFirstInvalidStep();
          }
          this.refreshFormErrorSummary();
          this.focusErrorSummaryAfterRender();
          return;
        }

        const inactiveItemGuard = this.extractInactiveItemForwardWriteGuard(err);
        if (inactiveItemGuard) {
          const details = this.buildInactiveItemGuardDetails(inactiveItemGuard);
          this.setSubmissionError(
            'Save blocked because the selected item is inactive for forward-looking writes.',
            details,
            this.inactiveItemForwardWriteCode,
          );
          this.applyInactiveItemControlError(inactiveItemGuard);
          this.notify.showError('Save blocked by inactive-item forward-write guard.');
          this.refreshFormErrorSummary();
          this.focusErrorSummaryAfterRender();
          return;
        }

        const duplicateConflict = this.extractDuplicateCanonicalItemConflict(err);
        if (duplicateConflict) {
          const message = err.error?.detail || 'That IFRC reference is already mapped to an existing item.';
          this.duplicateCanonicalConflict.set(duplicateConflict);
          this.setSubmissionError(
            message,
            this.buildDuplicateCanonicalConflictDetails(duplicateConflict),
            this.duplicateCanonicalItemCodeError,
          );
          this.notify.showError('Save blocked by canonical item code conflict.');
          return;
        }

        if (err.status === 409) {
          const message = err.error?.detail || 'Record was modified by another user. Please reload.';
          this.setSubmissionError(message, [], 'versionConflict');
          this.notify.showError(message);
        } else {
          const saveFailure = this.extractSaveFailureResponse(err);
          const message = cfg.tableKey === 'items'
            ? this.getItemSaveFailureMessage(err.status, saveFailure)
            : saveFailure?.detail || 'Save failed.';
          const details = cfg.tableKey === 'items'
            ? this.buildItemSaveFailureDetails(saveFailure, message)
            : [];
          this.setSubmissionError(message, details, 'submitFailure');
          this.notify.showError(message);
        }
      },
    });
  }

  onSuggestCatalogValues(): void {
    const cfg = this.config();
    if (!cfg || !this.isGovernedCatalogAuthoringTable()) {
      return;
    }

    const missingRequirements = this.getMissingCatalogSuggestionRequirementLabels();
    if (missingRequirements.length > 0) {
      this.markCatalogSuggestionRequirementControlsTouched();
      const message = `Complete ${this.joinHumanList(missingRequirements)} before requesting suggestions.`;
      this.catalogAssistError.set(message);
      this.notify.showWarning(message);
      return;
    }

    this.catalogSuggestionLoading.set(true);
    this.catalogSuggestion.set(null);
    this.catalogAssistError.set(null);

    const request$ = cfg.tableKey === 'ifrc_families'
      ? this.service.suggestIfrcFamilyValues(this.buildPreparedFormPayload(cfg))
      : this.service.suggestIfrcReferenceValues(this.buildPreparedFormPayload(cfg));

    request$.pipe(
      finalize(() => this.catalogSuggestionLoading.set(false)),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.catalogSuggestion.set(response);
        if (response.edit_guidance) {
          this.catalogEditGuidance.set(response.edit_guidance);
        }
        this.catalogAssistError.set(null);
        this.showCatalogWarnings(response.warnings);
        this.notify.showSuccess('Suggested values are ready for review.');
      },
      error: (err) => {
        if (err.status === 400 && err.error?.errors) {
          const errors = err.error.errors as Record<string, string>;
          this.applyServerErrors(errors);
          const messages = Object.values(errors);
          this.catalogAssistError.set(messages[0] ?? 'Please fix the required fields before requesting suggestions.');
          this.notify.showWarning('Please fix the required fields before requesting suggestions.');
          return;
        }

        const message = err.error?.detail || 'Failed to load authoring suggestions.';
        this.catalogAssistError.set(message);
        this.notify.showError(message);
      },
    });
  }

  onApplyCatalogSuggestion(): void {
    const cfg = this.config();
    const suggestion = this.catalogSuggestion();
    if (!cfg || !suggestion) {
      return;
    }

    const skippedLockedFields: string[] = [];
    for (const field of cfg.formFields) {
      if (!(field.field in suggestion.normalized)) {
        continue;
      }

      const control = this.form.get(field.field);
      if (!control) {
        continue;
      }

      if (this.isGovernedLockedField(field) && !this.replacementMode()) {
        skippedLockedFields.push(field.label);
        continue;
      }

      let nextValue = suggestion.normalized[field.field];
      if (field.uppercase && typeof nextValue === 'string') {
        nextValue = nextValue.trim().toUpperCase();
      }
      control.setValue(nextValue, { emitEvent: false });
    }

    this.applyGovernedCatalogFieldState();
    this.form.updateValueAndValidity({ emitEvent: false });
    this.form.markAsDirty();

    if (skippedLockedFields.length > 0) {
      this.catalogAssistError.set(
        'Locked canonical fields were not applied: '
        + skippedLockedFields.join(', ')
        + '. Use Create Replacement to change them.',
      );
      this.notify.showWarning('Suggested values were applied to editable fields only.');
      return;
    }

    this.catalogAssistError.set(null);
    this.notify.showSuccess('Suggested values applied to the form.');
  }

  onStartReplacementDraft(): void {
    if (!this.canCreateReplacement()) {
      return;
    }

    this.replacementMode.set(true);
    this.retireOriginalOnReplacement.set(false);
    this.catalogAssistError.set(null);
    this.applyGovernedCatalogFieldState();
    this.form.markAsPristine();
    this.notify.showWarning('Replacement draft started. Saving will create a new governed record instead of overwriting the current one.');
  }

  onCancelReplacementDraft(): void {
    if (!this.replacementMode()) {
      return;
    }

    this.restoreLoadedRecordSnapshot();
    this.replacementMode.set(false);
    this.retireOriginalOnReplacement.set(false);
    this.catalogAssistError.set(null);
    this.applyGovernedCatalogFieldState();
    this.form.updateValueAndValidity({ emitEvent: false });
    this.form.markAsPristine();
  }

  isGovernedCatalogAuthoringTable(): boolean {
    return this.editGate.isGovernedCatalogTable(this.config()?.tableKey);
  }

  getGuidedStepNumber(groupIndex: number): number {
    return groupIndex + 1;
  }

  isOptionalAttributesGroup(group: FormFieldGroup): boolean {
    return group.label === 'Product Attributes';
  }

  canCreateReplacement(): boolean {
    return this.isEdit()
      && this.isGovernedCatalogAuthoringTable()
      && this.catalogEditGuidance()?.replacement_supported === true;
  }

  isGovernedLockedField(field: MasterFieldConfig): boolean {
    return this.isEdit()
      && this.isGovernedCatalogAuthoringTable()
      && !this.replacementMode()
      && this.getLockedCatalogFieldNames().has(field.field);
  }

  getGovernedFieldAssistText(field: MasterFieldConfig): string | null {
    if (!this.isGovernedCatalogAuthoringTable() || !this.getLockedCatalogFieldNames().has(field.field)) {
      return null;
    }

    if (this.replacementMode()) {
      return 'Replacement draft active. This field is editable because saving will create a new record.';
    }

    if (this.isEdit()) {
      return 'This field is locked. Use "Create Replacement" if the code needs to change.';
    }

    return null;
  }

  getCatalogWarningText(): string | null {
    return this.editGate.getEffectiveCatalogEditGuidance(this.config(), this.catalogEditGuidance())?.warning_text ?? null;
  }

  getCatalogLockedFieldLabels(): string[] {
    return this.editGate.getDisabledFieldLabels({
      config: this.config(),
      editGuidance: this.catalogEditGuidance(),
      isEdit: this.isEdit(),
      replacementMode: this.replacementMode(),
      alwaysEnabledFieldNames: this.getAlwaysEnabledFieldNames(),
    });
  }

  getCatalogSuggestActionLabel(): string {
    return this.config()?.tableKey === 'ifrc_families'
      ? 'Suggest Family Values'
      : 'Suggest Reference Values';
  }

  getCatalogSuggestionRequirements(): CatalogSuggestionRequirement[] {
    const isReady = (fieldName: string) => this.hasFormValue(fieldName);

    switch (this.config()?.tableKey) {
      case 'ifrc_families':
        return [
          {
            field: 'family_label',
            label: 'Family Label',
            required: true,
            detail: 'Primary input used to normalize the governed Level 2 family name.',
            ready: isReady('family_label'),
          },
          {
            field: 'category_id',
            label: 'Level 1 Category',
            required: false,
            detail: 'Recommended when known so the proposed family stays in the correct DMIS branch.',
            ready: isReady('category_id'),
          },
          {
            field: 'group_code',
            label: 'Group Code',
            required: false,
            detail: 'Optional starting hint if the official IFRC group code is already known.',
            ready: isReady('group_code'),
          },
          {
            field: 'group_label',
            label: 'Group Label',
            required: false,
            detail: 'Optional human-readable group context when you know the branch but not the code.',
            ready: isReady('group_label'),
          },
        ];
      case 'ifrc_item_references':
        return [
          {
            field: 'ifrc_family_id',
            label: 'IFRC Family',
            required: true,
            detail: 'Sets the governed Level 2 branch and provides the code prefix.',
            ready: isReady('ifrc_family_id'),
          },
          {
            field: 'reference_desc',
            label: 'Reference Description',
            required: true,
            detail: 'Primary input used to normalize the Level 3 reference.',
            ready: isReady('reference_desc'),
          },
          {
            field: 'size_weight',
            label: 'Size or Weight',
            required: false,
            detail: 'Recommended when pack size, weight, or volume distinguishes the variant.',
            ready: isReady('size_weight'),
          },
          {
            field: 'form',
            label: 'Form',
            required: false,
            detail: 'Recommended when presentation changes the governed variant.',
            ready: isReady('form'),
          },
          {
            field: 'material',
            label: 'Material',
            required: false,
            detail: 'Recommended when composition is part of the distinguishing specification.',
            ready: isReady('material'),
          },
        ];
      default:
        return [];
    }
  }

  canRequestCatalogSuggestion(): boolean {
    return this.getMissingCatalogSuggestionRequirementLabels().length === 0;
  }

  getCatalogSuggestionReadinessText(): string | null {
    if (!this.isGovernedCatalogAuthoringTable()) {
      return null;
    }

    const missing = this.getMissingCatalogSuggestionRequirementLabels();
    if (missing.length === 0) {
      return 'Ready to suggest. Click the button below to auto-fill the code fields.';
    }

    return `Complete ${this.joinHumanList(missing)} before generating suggestions.`;
  }

  getCatalogSuggestButtonTooltip(): string {
    if (!this.canRequestCatalogSuggestion()) {
      return this.getCatalogSuggestionReadinessText() ?? 'Complete the required fields before generating suggestions.';
    }

    return this.config()?.tableKey === 'ifrc_families'
      ? 'Auto-fill the code fields based on the family label you entered.'
      : 'Auto-fill the code fields based on the family, description, and attributes you entered.';
  }

  getRenderedFieldLabel(field: MasterFieldConfig): string {
    return field.label;
  }

  getStatusField(): MasterFieldConfig | null {
    if (!this.lastGroupIsSingleStatus()) return null;
    const groups = this.fieldGroups();
    return groups[groups.length - 1].fields[0];
  }

  getStatusOptions(): { value: string; label: string }[] {
    return this.getStatusField()?.options ?? [];
  }

  getStatusFieldHint(): string | null {
    const field = this.getStatusField();
    return field ? this.getFieldHint(field) : null;
  }

  private buildFieldGroupKey(label: string, usedKeys: Map<string, number>): string {
    const slugBase = this.slugifyFieldGroupLabel(label) || 'general';
    const duplicateCount = usedKeys.get(slugBase) ?? 0;
    usedKeys.set(slugBase, duplicateCount + 1);
    return duplicateCount === 0 ? slugBase : `${slugBase}-${duplicateCount + 1}`;
  }

  private slugifyFieldGroupLabel(value: string): string {
    return value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
  }

  getFieldTooltip(field: MasterFieldConfig): string | null {
    const tooltip = String(field.tooltip ?? '').trim();
    return tooltip || null;
  }

  getFieldDomId(field: MasterFieldConfig | string): string {
    const fieldName = typeof field === 'string' ? field : field.field;
    const safeFieldName = fieldName.replace(/[^A-Za-z0-9_-]/g, '-');
    return `master-field-${safeFieldName}`;
  }

  getFieldHint(field: MasterFieldConfig): string | null {
    const currentValue = String(this.form.get(field.field)?.value ?? '').trim().toUpperCase();
    const matched = field.valueHints?.find((hint) => hint.value.trim().toUpperCase() === currentValue);
    return matched?.hint ?? field.hint ?? null;
  }

  getPrimarySaveLabel(): string {
    if (this.replacementMode()) {
      return 'Create Replacement';
    }
    return this.isEdit() ? 'Update' : 'Create';
  }

  getPrimarySaveIcon(): string {
    return this.replacementMode() ? 'content_copy' : 'save';
  }

  getCatalogSuggestionEntries(): { label: string; value: string; locked: boolean }[] {
    const cfg = this.config();
    const suggestion = this.catalogSuggestion();
    if (!cfg || !suggestion) {
      return [];
    }

    const lockedFieldNames = this.getLockedCatalogFieldNames();
    return cfg.formFields
      .filter((field) => {
        const value = suggestion.normalized[field.field];
        return value !== undefined && value !== null && value !== '';
      })
      .map((field) => ({
        label: field.label,
        value: this.formatCatalogSuggestionValue(field, suggestion.normalized[field.field]),
        locked: lockedFieldNames.has(field.field),
      }));
  }

  getCatalogSuggestionConflictMessages(): string[] {
    const conflicts = this.catalogSuggestion()?.conflicts;
    if (!conflicts || typeof conflicts !== 'object') {
      return [];
    }

    const conflictMap = conflicts as Record<string, unknown>;
    const messages: string[] = [];
    const exactCodeMatch = conflictMap['exact_code_match'];
    const exactLabelMatch = conflictMap['exact_label_match'];
    const exactDescriptionMatch = conflictMap['exact_desc_match'];
    const nearMatches = Array.isArray(conflictMap['near_matches']) ? conflictMap['near_matches'] : [];

    if (exactCodeMatch && typeof exactCodeMatch === 'object') {
      messages.push('Exact code match already exists: ' + this.describeCatalogConflict(exactCodeMatch as Record<string, unknown>));
    }
    if (exactLabelMatch && typeof exactLabelMatch === 'object') {
      messages.push('Exact family label match already exists: ' + this.describeCatalogConflict(exactLabelMatch as Record<string, unknown>));
    }
    if (exactDescriptionMatch && typeof exactDescriptionMatch === 'object') {
      messages.push('Exact reference description match already exists: ' + this.describeCatalogConflict(exactDescriptionMatch as Record<string, unknown>));
    }
    if (nearMatches.length > 0) {
      const preview = nearMatches
        .slice(0, 3)
        .map((match) => this.describeCatalogConflict(match as Record<string, unknown>))
        .filter((value) => value.length > 0)
        .join('; ');
      if (preview) {
        messages.push('Near matches: ' + preview);
      }
    }

    return messages;
  }

  getCatalogSuggestionWarnings(): string[] {
    return this.getCatalogWarningMessages(this.catalogSuggestion()?.warnings);
  }

  onRetireOriginalReplacementChange(checked: boolean): void {
    this.retireOriginalOnReplacement.set(checked);
  }

  private buildPreparedFormPayload(cfg: MasterTableConfig): MasterRecord {
    const rawData = { ...this.form.getRawValue() } as MasterRecord;

    for (const field of cfg.formFields) {
      if (field.createOnly && this.isEdit()) {
        delete rawData[field.field];
        continue;
      }

      if (this.isLookupNoneValue(field, rawData[field.field])) {
        rawData[field.field] = null;
        continue;
      }

      if (field.uppercase && typeof rawData[field.field] === 'string') {
        const currentValue = rawData[field.field] as string;
        rawData[field.field] = currentValue.trim().toUpperCase();
      }
    }

    if (cfg.tableKey === 'items') {
      delete rawData['item_code'];

      if (this.shouldPersistLocalItemCode()) {
        const normalizedLegacyCode = String(rawData['legacy_item_code'] ?? '').trim().toUpperCase();
        rawData['legacy_item_code'] = normalizedLegacyCode || null;
      } else {
        delete rawData['legacy_item_code'];
      }
    }

    if (cfg.tableKey === 'items' && this.acceptedIfrcSuggestLogId) {
      rawData['ifrc_suggest_log_id'] = this.acceptedIfrcSuggestLogId;
    }

    if (cfg.tableKey === 'items') {
      const conversions = this.getValidatedItemUomConversions();
      rawData['uom_options'] = conversions.map(c => ({
        uom_code: c.uom_code,
        conversion_factor: c.conversion_factor,
      }));
    }

    return rawData;
  }

  private applyServerErrors(errors: Record<string, string>): void {
    for (const [field, msg] of Object.entries(errors)) {
      const control = this.form.get(field);
      if (control) {
        control.setErrors({ server: msg });
        control.markAsTouched();
      }
    }
  }

  private refreshFormErrorSummary(): void {
    this.formStateVersion.update((version) => version + 1);
  }

  private focusErrorSummaryAfterRender(): void {
    afterNextRender(() => {
      this.errorSummary()?.nativeElement.querySelector('h2')?.focus();
    }, { injector: this.injector });
  }

  private getMissingCatalogSuggestionRequirementLabels(): string[] {
    return this.getCatalogSuggestionRequirements()
      .filter((requirement) => requirement.required && !requirement.ready)
      .map((requirement) => requirement.label);
  }

  private markCatalogSuggestionRequirementControlsTouched(): void {
    for (const requirement of this.getCatalogSuggestionRequirements().filter((entry) => entry.required)) {
      this.form.get(requirement.field)?.markAsTouched();
    }
  }

  private hasFormValue(fieldName: string): boolean {
    const value = this.form.get(fieldName)?.value;
    if (typeof value === 'string') {
      return value.trim().length > 0;
    }
    return value !== null && value !== undefined && value !== '';
  }

  private joinHumanList(values: string[]): string {
    if (values.length <= 1) {
      return values[0] ?? '';
    }
    if (values.length === 2) {
      return `${values[0]} and ${values[1]}`;
    }
    return `${values.slice(0, -1).join(', ')}, and ${values[values.length - 1]}`;
  }

  private getReplacementTableKey(): 'ifrc_families' | 'ifrc_item_references' | null {
    const tableKey = this.config()?.tableKey;
    if (tableKey === 'ifrc_families' || tableKey === 'ifrc_item_references') {
      return tableKey;
    }
    return null;
  }

  private getLockedCatalogFieldNames(): Set<string> {
    return this.editGate.getLockedCatalogFieldNames(this.config(), this.catalogEditGuidance());
  }

  private applyGovernedCatalogFieldState(): void {
    const cfg = this.config();
    if (!cfg) {
      return;
    }

    for (const field of cfg.formFields) {
      if (cfg.tableKey === 'items' && ['category_id', 'ifrc_family_id', 'ifrc_item_ref_id'].includes(field.field)) {
        continue;
      }

      const control = this.form.get(field.field);
      if (!control) {
        continue;
      }

      const shouldDisable = this.shouldDisableField(field);
      if (shouldDisable) {
        control.disable({ emitEvent: false });
      } else {
        control.enable({ emitEvent: false });
      }
    }
  }

  private shouldDisableField(field: MasterFieldConfig): boolean {
    return this.editGate.shouldDisableField(field, {
      config: this.config(),
      editGuidance: this.catalogEditGuidance(),
      isEdit: this.isEdit(),
      replacementMode: this.replacementMode(),
      alwaysEnabledFieldNames: this.getAlwaysEnabledFieldNames(),
    });
  }

  private getDefaultCatalogEditGuidance(tableKey: string): CatalogEditGuidance | null {
    return this.editGate.getDefaultCatalogEditGuidance(tableKey);
  }

  private maybePromptGovernedEditWarning(): void {
    if (
      !this.isEdit()
      || !this.isGovernedCatalogAuthoringTable()
      || this.promptedGovernedEditWarning
      || this.catalogEditGuidance()?.warning_required === false
    ) {
      return;
    }

    if (this.editGate.consumeGovernedEditWarningSkip()) {
      this.promptedGovernedEditWarning = true;
      return;
    }

    const cfg = this.config();
    if (!cfg) {
      return;
    }

    this.promptedGovernedEditWarning = true;
    const dialogRef = this.dialog.open(MasterEditGateDialogComponent, {
      data: this.editGate.buildDialogData({
        config: cfg,
        recordName: this.editGate.getRecordTitle(this.loadedRecordSnapshot, cfg, this.pk()),
        editGuidance: this.catalogEditGuidance(),
        isEdit: true,
        replacementMode: this.replacementMode(),
        alwaysEnabledFieldNames: this.getAlwaysEnabledFieldNames(),
      }),
      width: '460px',
      panelClass: 'dmis-edit-gate-panel',
      autoFocus: 'first-tabbable',
      ariaLabelledBy: 'gate-dialog-title',
    });

    dialogRef.afterClosed().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((confirmed) => {
      if (!confirmed) {
        this.router.navigate(['/master-data', cfg.routePath]);
      }
    });
  }

  private getAlwaysEnabledFieldNames(): readonly string[] {
    return this.isItemRecord() ? ['item_code'] : [];
  }

  private primeGovernedEditState(): void {
    const cfg = this.config();
    if (!cfg || !this.isEdit() || !this.isGovernedCatalogAuthoringTable()) {
      return;
    }

    if (!this.catalogEditGuidance()) {
      this.catalogEditGuidance.set(this.getDefaultCatalogEditGuidance(cfg.tableKey));
    }

    this.applyGovernedCatalogFieldState();
    this.maybePromptGovernedEditWarning();
  }
  private restoreLoadedRecordSnapshot(): void {
    const cfg = this.config();
    if (!cfg || !this.loadedRecordSnapshot) {
      return;
    }

    for (const field of cfg.formFields) {
      const control = this.form.get(field.field);
      if (!control) {
        continue;
      }

      const nextValue = this.toLookupControlValue(field, this.loadedRecordSnapshot[field.field] ?? null);
      control.setValue(nextValue, { emitEvent: false });
    }
  }

  private formatCatalogSuggestionValue(field: MasterFieldConfig, value: unknown): string {
    if (field.type === 'lookup' && field.lookupTable) {
      const lookupValue = this.findLookupByValue(this.readLookup(field.lookupTable), value);
      if (lookupValue) {
        return String(lookupValue.label ?? lookupValue.value ?? value);
      }
    }

    if (typeof value === 'boolean') {
      return value ? 'Yes' : 'No';
    }

    return String(value);
  }

  private describeCatalogConflict(conflict: Record<string, unknown>): string {
    const ifrcCode = String(conflict['ifrc_code'] ?? '').trim();
    const referenceDesc = String(conflict['reference_desc'] ?? '').trim();
    if (ifrcCode) {
      return referenceDesc ? `${referenceDesc} (${ifrcCode})` : ifrcCode;
    }

    const familyLabel = String(conflict['family_label'] ?? '').trim();
    const familyCode = String(conflict['family_code'] ?? '').trim();
    const groupCode = String(conflict['group_code'] ?? '').trim();
    const familySuffix = [groupCode, familyCode].filter(Boolean).join('-');
    if (familyLabel) {
      return familySuffix ? `${familyLabel} (${familySuffix})` : familyLabel;
    }

    const categoryDesc = String(conflict['category_desc'] ?? '').trim();
    const categoryCode = String(conflict['category_code'] ?? '').trim();
    if (categoryDesc) {
      return categoryCode ? `${categoryDesc} (${categoryCode})` : categoryDesc;
    }

    return familySuffix || categoryCode || 'Existing catalog record';
  }

  private showCatalogWarnings(warnings: string[] | undefined): void {
    const warningMessages = this.getCatalogWarningMessages(warnings);
    if (warningMessages.length > 0) {
      this.notify.showWarning(warningMessages[0]);
    }
  }

  private getCatalogWarningMessages(warnings: string[] | undefined): string[] {
    return (warnings ?? [])
      .map((warning) => this.formatCatalogWarning(warning))
      .filter((warning): warning is string => warning.length > 0);
  }

  private formatCatalogWarning(warning: string): string {
    switch (warning) {
      case 'replacement_original_retire_blocked':
        return 'Replacement created, but the original record could not be retired because it is still referenced.';
      case 'reference_sequence_lookup_failed':
        return 'The suggested IFRC sequence could not be verified. Review the proposed code carefully before saving.';
      case 'db_unavailable':
        return 'Catalog authoring assistance is temporarily unavailable.';
      case 'db_error':
        return 'The catalog governance service could not complete the request.';
      case 'not_found':
        return 'The original governed record could not be found.';
      default:
        return this.humanizeToken(warning);
    }
  }

  getRenderableFields(group: FormFieldGroup): MasterFieldConfig[] {
    if (!this.isItemRecord()) {
      return group.fields;
    }

    if (group.label === 'Classification') {
      return group.fields.filter((field) => !['category_id', 'ifrc_family_id', 'ifrc_item_ref_id'].includes(field.field));
    }

    if (group.label === 'Item Identity') {
      return group.fields.filter((field) => field.field !== 'legacy_item_code' || this.shouldShowLocalItemCodeField());
    }

    return group.fields;
  }

  isItemClassificationGroup(groupLabel: string): boolean {
    return this.isItemRecord() && groupLabel === 'Classification';
  }

  isInventoryRulesGroup(label: string): boolean {
    return label === 'Inventory Rules';
  }

  isUomConversionsGroup(label: string): boolean {
    return label === 'UOM & Conversions';
  }

  getUomLabel(uomCode: string): string {
    if (!uomCode) return '';
    const allUoms = this.lookups()['uom'] || [];
    const match = allUoms.find(u => this.sameValue(u.value, uomCode));
    return match?.label ?? uomCode;
  }

  addUomConversion(): void {
    const [nextAlternateUom] = this.availableAlternateUoms();
    if (!nextAlternateUom) {
      return;
    }

    this.itemUomConversions.update(current => [
      ...current,
      { uom_code: String(nextAlternateUom.value ?? ''), conversion_factor: 1 },
    ]);
    this.syncItemUomConversionState();
  }

  removeUomConversion(index: number): void {
    this.itemUomConversions.update(current =>
      current.filter((_, i) => i !== index),
    );
    this.syncItemUomConversionState();
  }

  updateUomConversionUom(index: number, uomCode: string): void {
    this.itemUomConversions.update(current =>
      current.map((row, i) => i === index ? { ...row, uom_code: uomCode } : row),
    );
    this.syncItemUomConversionState();
  }

  updateUomConversionFactor(index: number, factor: number): void {
    const nextFactor = Number.isNaN(factor) ? null : factor;
    this.itemUomConversions.update(current =>
      current.map((row, i) => i === index ? { ...row, conversion_factor: nextFactor } : row),
    );
    this.syncItemUomConversionState();
  }

  isItemFamilyRequired(): boolean {
    return !!this.form.get('category_id')?.value
      && (this.itemHadMappedClassificationOnLoad || (!this.isEdit() && !this.localDraftMode()));
  }

  isItemReferenceRequired(): boolean {
    return !!this.form.get('ifrc_family_id')?.value;
  }

  shouldShowLocalItemCodeField(): boolean {
    return this.isItemRecord() && (this.localDraftMode() || (this.isEdit() && !this.itemHadMappedClassificationOnLoad));
  }

  private shouldPersistLocalItemCode(): boolean {
    return this.shouldShowLocalItemCodeField();
  }

  shouldShowIfrcHelperPanel(): boolean {
    return this.isItemRecord();
  }

  canRequestIfrcSuggestion(): boolean {
    const itemName = String(this.form.get('item_name')?.value ?? '').trim();
    return this.isItemRecord() && itemName.length >= 3 && !this.ifrcLoading();
  }

  getIfrcSuggestionRequestLabel(): string {
    return this.ifrcSuggestion() || this.ifrcError() || this.ifrcSuggestionResolution()
      ? 'Refresh Match'
      : 'Find Match';
  }

  hasIfrcSuggestionActivity(): boolean {
    return this.ifrcLoading() || this.ifrcSuggestion() != null || this.ifrcError() != null;
  }
  isManagedItemCodeField(fieldName: string): boolean {
    return this.isItemRecord() && fieldName === 'item_code';
  }

  canAcceptResolvedIfrcSuggestion(): boolean {
    return this.getAcceptedSuggestionFamily() != null
      && this.getAcceptedSuggestionReference() != null;
  }

  getIfrcSuggestionPrimaryActionLabel(): string {
    const resolution = this.ifrcSuggestionResolution();
    if (!resolution) {
      return 'Review Suggested Match';
    }

    if (resolution.directAcceptAllowed) {
      return 'Accept Suggested Match';
    }

    if (resolution.status === 'ambiguous') {
      return 'Use Selected Candidate';
    }

    if (resolution.status === 'unresolved') {
      return 'No Governed Match Available';
    }

    return 'Review Suggested Match';
  }

  hasSuggestionCandidates(): boolean {
    return (this.ifrcSuggestionResolution()?.candidates.length ?? 0) > 0;
  }

  shouldShowSuggestionCandidates(): boolean {
    const resolved = this.ifrcSuggestionResolution();
    return resolved?.status === 'ambiguous' && (resolved.candidates.length ?? 0) > 0;
  }

  getSuggestionCandidates(): SuggestedIfrcCandidate[] {
    return this.ifrcSuggestionResolution()?.candidates ?? [];
  }

  isSuggestionCandidateSelected(candidate: SuggestedIfrcCandidate): boolean {
    const selectedCandidateId = this.selectedSuggestionCandidateId();
    return selectedCandidateId != null && this.sameValue(selectedCandidateId, candidate.reference.value);
  }

  isSuggestionCandidateAutoHighlighted(candidate: SuggestedIfrcCandidate): boolean {
    const autoHighlightCandidateId = this.ifrcSuggestionResolution()?.autoHighlightCandidateId;
    return candidate.autoHighlight || (
      autoHighlightCandidateId != null && this.sameValue(autoHighlightCandidateId, candidate.reference.value)
    );
  }

  getSuggestionCandidateScore(candidate: SuggestedIfrcCandidate): string {
    const score = Math.max(0, Math.min(1, Number(candidate.score ?? 0)));
    return `${Math.round(score * 100)}% match`;
  }

  getSuggestionInputName(): string | null {
    const itemName = String(this.form.get('item_name')?.value ?? '').trim();
    return itemName || null;
  }

  getResolvedSuggestionVariantDetails(): { label: string; value: string }[] {
    return this.buildSuggestionVariantDetails(this.ifrcSuggestionResolution()?.reference ?? null);
  }

  getSuggestionCandidateVariantDetails(candidate: SuggestedIfrcCandidate): { label: string; value: string }[] {
    return this.buildSuggestionVariantDetails(candidate.reference);
  }

  getSuggestionCandidateFamilyLabel(candidate: SuggestedIfrcCandidate): string {
    const familyLabel = String(candidate.reference.family_label ?? candidate.family?.label ?? '').trim() || 'Unresolved family';
    const familyCode = String(candidate.reference.family_code ?? candidate.family?.family_code ?? '').trim();
    const groupCode = String(candidate.family?.group_code ?? '').trim();
    const suffix = [groupCode, familyCode].filter(Boolean).join('-');
    return suffix ? `${familyLabel} (${suffix})` : familyLabel;
  }

  getSuggestionCandidateCategoryLabel(candidate: SuggestedIfrcCandidate): string | null {
    const categoryLabel = String(candidate.reference.category_label ?? '').trim();
    const categoryCode = String(candidate.reference.category_code ?? '').trim();
    if (categoryLabel && categoryCode) {
      return `${categoryLabel} (${categoryCode})`;
    }
    return categoryLabel || categoryCode || null;
  }

  getSuggestionCandidateReasonSummary(candidate: SuggestedIfrcCandidate): string | null {
    const reasons = candidate.matchReasons
      .map((reason) => this.humanizeSuggestionMatchReason(reason))
      .filter((reason) => reason.length > 0);
    return reasons.length > 0 ? reasons.join(', ') : null;
  }

  getIfrcSuggestionStatusText(): string | null {
    const resolution = this.ifrcSuggestionResolution();
    if (!resolution) {
      return null;
    }

    switch (resolution.status) {
      case 'resolved':
        return 'Exact governed reference found';
      case 'ambiguous':
        return `${resolution.candidates.length || 0} governed variant${resolution.candidates.length === 1 ? '' : 's'} require review`;
      case 'unresolved':
        return 'No governed exact match found';
      default:
        return null;
    }
  }

  getIfrcSuggestionExplanation(): string | null {
    const resolution = this.ifrcSuggestionResolution();
    if (!resolution) {
      return null;
    }

    const explanation = String(resolution.explanation ?? '').trim();
    if (explanation) {
      return explanation;
    }

    switch (resolution.status) {
      case 'resolved':
        return 'Exactly one official governed IFRC reference matched the entered item. Review the official variant details before accepting it.';
      case 'ambiguous':
        return 'Multiple official governed IFRC variants matched the entered item. Review IFRC code, size or weight, form, and material before selecting one.';
      case 'unresolved':
        return 'No governed exact IFRC reference matched the entered item. Keep the item name for searchability, but do not treat any generated code as final.';
      default:
        return null;
    }
  }

  getSuggestedIfrcCode(): string | null {
    const ifrcCode = String(this.ifrcSuggestionResolution()?.reference?.ifrc_code ?? '').trim();
    return ifrcCode || null;
  }

  getLegacyItemCode(): string | null {
    return this.legacyItemCodeValue;
  }

  isLookupLoading(lookupKey: string): boolean {
    return this.lookupLoading()[lookupKey] === true;
  }

  private setupUserWarehouseTenantFilter(cfg: MasterTableConfig): void {
    if (cfg.tableKey !== 'user') {
      return;
    }
    const tenantControl = this.form.get('tenant_id');
    const warehouseControl = this.form.get('assigned_warehouse_id');
    if (!tenantControl || !warehouseControl) {
      return;
    }

    tenantControl.valueChanges.pipe(
      startWith(tenantControl.value),
      pairwise(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(([previousTenant, currentTenant]) => {
      if (!this.sameValue(previousTenant, currentTenant)) {
        warehouseControl.setValue(null, { emitEvent: false });
        this.formStateVersion.update((version) => version + 1);
      }
    });
  }

  hasLookupNoneOption(field: MasterFieldConfig): boolean {
    return field.type === 'lookup'
      && !field.required
      && (!!field.noneOptionLabel || field.field === 'parent_tenant_id');
  }

  getLookupOptions(field: MasterFieldConfig): LookupItem[] {
    this.formStateVersion();
    let items = field.lookupTable ? this.readLookup(field.lookupTable) : [];
    if (this.shouldFilterUserWarehouseLookup(field)) {
      const tenantId = this.form.get(field.lookupDependsOn!)?.value;
      items = tenantId == null || tenantId === ''
        ? []
        : items.filter((item) => this.sameValue(item['tenant_id'], tenantId));
    }
    return this.withLookupNoneOption(field, items);
  }

  getLookupHint(field: MasterFieldConfig): string | null {
    this.formStateVersion();
    if (this.shouldFilterUserWarehouseLookup(field)) {
      const tenantId = this.form.get(field.lookupDependsOn!)?.value;
      if (tenantId == null || tenantId === '') {
        return field.lookupBlockedHint ?? null;
      }
      if (this.getLookupOptions(field).length === 0) {
        return field.lookupEmptyHint ?? 'No options available.';
      }
    }
    return field.hint ?? null;
  }

  getLookupEmptyHint(field: MasterFieldConfig): string {
    return this.getLookupHint(field) ?? 'No options available.';
  }

  private shouldFilterUserWarehouseLookup(field: MasterFieldConfig): boolean {
    return this.config()?.tableKey === 'user'
      && !this.isEdit()
      && field.field === 'assigned_warehouse_id'
      && field.lookupTable === 'warehouses'
      && field.lookupDependsOn === 'tenant_id';
  }

  getLookupOptionTrackValue(item: LookupItem): string | number {
    return item.value;
  }

  private toLookupControlValue(field: MasterFieldConfig, value: unknown): unknown {
    if (this.hasLookupNoneOption(field) && (value === null || value === undefined || value === '')) {
      return this.lookupNoneValue;
    }
    return value;
  }

  private isLookupNoneValue(field: MasterFieldConfig, value: unknown): boolean {
    return this.hasLookupNoneOption(field) && value === this.lookupNoneValue;
  }

  getLookupNoneLabel(field: MasterFieldConfig): string {
    return field.noneOptionLabel ?? 'None';
  }

  private withLookupNoneOption(field: MasterFieldConfig, items: LookupItem[]): LookupItem[] {
    if (!this.hasLookupNoneOption(field)) {
      return items;
    }

    return [
      { value: this.lookupNoneValue, label: this.getLookupNoneLabel(field) },
      ...items.filter((item) => item.value !== this.lookupNoneValue),
    ];
  }

  getItemTaxonomyFieldError(fieldName: 'category_id' | 'ifrc_family_id' | 'ifrc_item_ref_id'): string | null {
    const control = this.form.get(fieldName);
    if (!control) {
      return null;
    }

    const isVisible = control.touched || this.form.touched || this.submissionError() != null;
    if (!isVisible) {
      return null;
    }

    if (control.hasError('required')) {
      if (fieldName === 'category_id') {
        return 'Level 1 category is required.';
      }
    }

    if (control.hasError('server')) {
      return String(control.getError('server'));
    }

    if (fieldName === 'ifrc_family_id') {
      if (this.form.hasError('ifrcFamilyRequired')) {
        return this.itemHadMappedClassificationOnLoad
          ? 'Mapped items must keep an IFRC Family.'
          : 'IFRC Family is required for new items.';
      }
      if (this.form.hasError('ifrcFamilyOutsideCategory')) {
        return 'Selected IFRC Family does not belong to the chosen Level 1 category.';
      }
      if (this.form.hasError('ifrcFamilyForReferenceRequired')) {
        return 'Select an IFRC Family before choosing an IFRC reference.';
      }
    }

    if (fieldName === 'ifrc_item_ref_id') {
      if (this.form.hasError('ifrcReferenceRequired')) {
        if (this.itemHadMappedClassificationOnLoad) {
          return 'Mapped items must keep an IFRC item reference.';
        }
        return this.isEdit()
          ? 'Select an IFRC item reference to complete the mapping.'
          : 'IFRC Item Reference is required for new items.';
      }
      if (this.form.hasError('ifrcReferenceOutsideFamily')) {
        return 'Selected IFRC reference does not belong to the chosen IFRC Family.';
      }
    }

    return null;
  }

  getItemFamilyLabel(family: IfrcFamilyLookup): string {
    const familyCode = String(family.family_code ?? '').trim();
    const groupCode = String(family.group_code ?? '').trim();
    const suffix = [groupCode, familyCode].filter(Boolean).join('-');
    return suffix ? `${family.label} (${suffix})` : family.label;
  }

  getItemReferenceLabel(reference: IfrcReferenceLookup): string {
    const ifrcCode = String(reference.ifrc_code ?? '').trim();
    return ifrcCode ? `${reference.label} (${ifrcCode})` : reference.label;
  }

  getResolvedSuggestionFamilyLabel(): string {
    const resolved = this.ifrcSuggestionResolution();
    const suggestion = this.ifrcSuggestion();
    if (resolved?.family) {
      return this.getItemFamilyLabel(resolved.family);
    }

    const familyCode = String(suggestion?.family_code ?? '').trim();
    const groupCode = String(suggestion?.group_code ?? '').trim();
    const suffix = [groupCode, familyCode].filter(Boolean).join('-');
    return suffix || 'Unresolved family';
  }

  getResolvedSuggestionReferenceLabel(): string | null {
    const resolved = this.ifrcSuggestionResolution();
    if (resolved?.reference) {
      return this.getItemReferenceLabel(resolved.reference);
    }

    return null;
  }

  getIfrcSuggestionConfidence(): string | null {
    const suggestion = this.ifrcSuggestion();
    if (!suggestion) {
      return null;
    }

    const confidence = Number(suggestion.confidence ?? 0);
    if (!Number.isFinite(confidence)) {
      return null;
    }

    return `${Math.round(confidence * 100)}% confidence`;
  }

  private getSelectedSuggestionCandidate(): SuggestedIfrcCandidate | null {
    const selectedCandidateId = this.selectedSuggestionCandidateId();
    if (selectedCandidateId == null) {
      return null;
    }

    return this.getSuggestionCandidates().find((candidate) => (
      this.sameValue(candidate.reference.value, selectedCandidateId)
    )) ?? null;
  }

  private getAcceptedSuggestionFamily(): IfrcFamilyLookup | null {
    const resolved = this.ifrcSuggestionResolution();
    if (!resolved) {
      return null;
    }

    if (resolved.directAcceptAllowed && resolved.reference) {
      return resolved.family;
    }

    return this.getSelectedSuggestionCandidate()?.family ?? null;
  }

  private getAcceptedSuggestionReference(): IfrcReferenceLookup | null {
    const resolved = this.ifrcSuggestionResolution();
    if (!resolved) {
      return null;
    }

    if (resolved.directAcceptAllowed && resolved.reference) {
      return resolved.reference;
    }

    return this.getSelectedSuggestionCandidate()?.reference ?? null;
  }

  private humanizeSuggestionMatchReason(reason: string): string {
    const normalizedReason = String(reason ?? '').trim();
    if (!normalizedReason) {
      return '';
    }

    switch (normalizedReason) {
      case 'exact_generated_code_match':
        return 'Exact governed IFRC code match';
      case 'exact_spec_match':
        return 'Exact governed variant match';
      case 'exact_size_weight_match':
      case 'size_weight_match':
        return 'Exact size or weight match';
      case 'size_weight_mismatch':
        return 'Size or weight differs from the entered spec';
      case 'size_weight_missing':
        return 'Candidate is missing official size or weight metadata';
      case 'exact_form_match':
      case 'form_match':
        return 'Exact form match';
      case 'form_mismatch':
        return 'Form differs from the entered spec';
      case 'exact_material_match':
      case 'material_match':
        return 'Exact material match';
      case 'material_mismatch':
        return 'Material differs from the entered spec';
      default:
        break;
    }

    if (normalizedReason.startsWith('desc_overlap:')) {
      const terms = normalizedReason.slice('desc_overlap:'.length).split(',').filter(Boolean).join(', ');
      return terms ? `Description overlap: ${terms}` : 'Description overlap';
    }

    const words = normalizedReason.split('_').filter(Boolean);
    if (words.length === 0) {
      return normalizedReason;
    }

    return words
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }

  private buildSuggestionVariantDetails(
    reference: Pick<IfrcReferenceLookup, 'size_weight' | 'form' | 'material'> | null | undefined,
  ): { label: string; value: string }[] {
    const details: { label: string; value: string }[] = [];
    const sizeWeight = String(reference?.size_weight ?? '').trim();
    const form = String(reference?.form ?? '').trim();
    const material = String(reference?.material ?? '').trim();

    if (sizeWeight) {
      details.push({ label: 'Size / Weight', value: sizeWeight });
    }
    if (form) {
      details.push({ label: 'Form', value: form });
    }
    if (material) {
      details.push({ label: 'Material', value: material });
    }

    return details;
  }

  onAssignStorageLocation(): void {
    if (!this.canAssignLocation()) return;

    const itemId = this.toPositiveInt(this.pk());
    if (!itemId) {
      this.notify.showError('Cannot assign location: invalid item ID.');
      return;
    }

    this.clearLocationServerErrors();

    if (this.locationForm.invalid) {
      this.locationForm.markAllAsTouched();
      return;
    }

    const inventoryId = this.toPositiveInt(this.locationForm.controls.inventory_id.value);
    const locationId = this.toPositiveInt(this.locationForm.controls.location_id.value);
    const batchId = this.toPositiveInt(this.locationForm.controls.batch_id.value);
    const assignmentIsBatched = this.assignmentIsBatched();

    if (!inventoryId || !locationId) {
      this.locationForm.markAllAsTouched();
      return;
    }

    if (assignmentIsBatched && !batchId) {
      this.locationForm.controls.batch_id.setErrors({ required: true });
      this.locationForm.controls.batch_id.markAsTouched();
      this.notify.showWarning('Select a batch or lot for batched items.');
      return;
    }

    if (!assignmentIsBatched && batchId) {
      this.notify.showWarning('Batch or lot must stay empty for non-batched items.');
      this.locationForm.controls.batch_id.setErrors({ server: 'Must stay empty for non-batched items.' });
      this.locationForm.controls.batch_id.markAsTouched();
      return;
    }

    const payload: {
      item_id: number;
      inventory_id: number;
      location_id: number;
      batch_id?: number;
    } = {
      item_id: itemId,
      inventory_id: inventoryId,
      location_id: locationId,
    };
    if (batchId) {
      payload.batch_id = batchId;
    }

    this.assigningLocation.set(true);
    this.replenishmentService.assignStorageLocation(payload).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.assigningLocation.set(false);
        const action = response.created ? 'saved' : 'already exists';
        this.notify.showSuccess(
          `Location assignment ${action} in ${response.storage_table}.`
        );
      },
      error: (err) => {
        this.assigningLocation.set(false);
        this.applyLocationAssignmentErrors(err?.error?.errors);
      },
    });
  }

  /** Map section group labels to Material icons */
  getSectionIcon(groupLabel: string): string {
    const iconMap: Record<string, string> = {
      'Basic Information': 'info',
      'General': 'info',
      'Details': 'description',
      'Contact': 'contact_phone',
      'Contact Information': 'contact_phone',
      'Address': 'location_on',
      'Location': 'location_on',
      'Status': 'toggle_on',
      'Inventory Settings': 'inventory_2',
      'Procurement': 'shopping_cart',
      'Financial': 'payments',
      'Item Identity': 'label',
      'Classification': 'category',
      'Hierarchy': 'account_tree',
      'Canonical Identity': 'lock',
      'Metadata': 'tune',
      'Start Here': 'play_arrow',
      'Codes': 'key',
      'Generated Codes': 'auto_awesome',
      'Product Attributes': 'straighten',
      'Inventory Rules': 'inventory_2',
      'UOM & Conversions': 'swap_horiz',
      'Tracking & Behaviour': 'track_changes',
      'Notes & Storage': 'notes',
      'Notes': 'notes',
      'Category Details': 'folder_open',
    };
    return iconMap[groupLabel] || 'folder';
  }

  onOpenDuplicateExistingItem(): void {
    const cfg = this.config();
    const existingItemId = this.duplicateCanonicalConflict()?.existing_item?.item_id;
    if (!cfg || existingItemId == null || existingItemId === '') {
      return;
    }

    this.router.navigate(['/master-data', cfg.routePath, existingItemId]);
  }

  onChooseDifferentReference(): void {
    this.clearSubmissionError();
    this.onClearIfrcReference();
    this.form.get('ifrc_item_ref_id')?.markAsTouched();
  }

  onCancel(): void {
    this.navigateBack();
  }

  getLocationFieldError(fieldName: 'inventory_id' | 'location_id' | 'batch_id'): string | null {
    const control = this.locationForm.controls[fieldName];
    if (!control || !control.touched || !control.errors) return null;
    if (control.errors['required']) {
      if (fieldName === 'inventory_id') return 'Select a warehouse.';
      if (fieldName === 'location_id') return 'Select a location.';
      return 'Select a batch or lot.';
    }
    if (control.errors['min']) return 'Must be a positive number.';
    if (control.errors['server']) return String(control.errors['server']);
    return 'Invalid value.';
  }

  getStorageAssignmentOptionDetail(option: StorageAssignmentOption): string | null {
    const detail = String(option.detail ?? '').trim();
    return detail || null;
  }

  private navigateBack(): void {
    const cfg = this.config();
    if (cfg) {
      this.router.navigate(['/master-data', cfg.routePath]);
    }
  }

  private toPositiveInt(value: unknown): number | null {
    if (value == null || value === '') return null;
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed <= 0) return null;
    return parsed;
  }

  private toRecordIdentifier(value: unknown): string | number | null {
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value;
    }
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
    return null;
  }

  private clearLocationServerErrors(): void {
    const controls = this.locationForm.controls;
    for (const control of [controls.inventory_id, controls.location_id, controls.batch_id]) {
      if (!control.errors?.['server']) continue;
      const nextErrors = { ...control.errors };
      delete nextErrors['server'];
      const remaining = Object.keys(nextErrors).length ? nextErrors : null;
      control.setErrors(remaining);
    }
  }

  private applyLocationAssignmentErrors(rawErrors: unknown): void {
    if (!rawErrors || typeof rawErrors !== 'object') {
      this.notify.showError('Failed to assign storage location.');
      return;
    }

    const errors = rawErrors as Record<string, unknown>;
    let fallbackMessage: string | null = null;

    for (const [key, value] of Object.entries(errors)) {
      const message = String(value);
      if (key === 'inventory_id' || key === 'location_id' || key === 'batch_id') {
        this.locationForm.controls[key].setErrors({ server: message });
        this.locationForm.controls[key].markAsTouched();
      } else if (!fallbackMessage) {
        fallbackMessage = message;
      }
    }

    this.notify.showError(fallbackMessage || 'Storage location assignment failed.');
  }

  private resetStorageAssignmentState(): void {
    this.latestStorageAssignmentRequestId += 1;
    this.storageAssignmentLoading.set(false);
    this.storageAssignmentError.set(null);
    this.storageAssignmentOptions.set(null);
    this.locationForm.reset(
      {
        inventory_id: null,
        location_id: null,
        batch_id: null,
      },
      { emitEvent: false },
    );
    this.locationForm.markAsPristine();
    this.locationForm.markAsUntouched();
    this.locationFormVersion.update((version) => version + 1);
  }

  private loadStorageAssignmentOptionsForCurrentItem(): void {
    const itemId = this.canAssignLocation() ? this.toPositiveInt(this.pk()) : null;
    if (itemId == null) {
      this.resetStorageAssignmentState();
      return;
    }

    const requestId = ++this.latestStorageAssignmentRequestId;
    this.storageAssignmentLoading.set(true);
    this.storageAssignmentError.set(null);
    this.replenishmentService.getStorageAssignmentOptions(itemId).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (options) => {
        if (requestId !== this.latestStorageAssignmentRequestId || options.item_id !== itemId) {
          return;
        }
        this.storageAssignmentLoading.set(false);
        this.storageAssignmentOptions.set(options);
        this.storageAssignmentError.set(null);
        this.syncStorageAssignmentSelections();
      },
      error: (err) => {
        if (requestId !== this.latestStorageAssignmentRequestId) {
          return;
        }
        this.storageAssignmentLoading.set(false);
        this.storageAssignmentOptions.set(null);
        this.storageAssignmentError.set(
          String(err?.error?.detail || 'Failed to load storage assignment choices.'),
        );
      },
    });
  }

  private syncStorageAssignmentSelections(): void {
    const inventoryId = this.toPositiveInt(this.locationForm.controls.inventory_id.value);
    if (inventoryId == null) {
      return;
    }

    if (!this.hasStorageOption(this.inventoryAssignmentOptions(), inventoryId)) {
      this.locationForm.reset(
        {
          inventory_id: null,
          location_id: null,
          batch_id: null,
        },
        { emitEvent: false },
      );
      this.locationFormVersion.update((version) => version + 1);
      return;
    }

    const locationId = this.toPositiveInt(this.locationForm.controls.location_id.value);
    if (locationId != null && !this.hasStorageOption(this.locationAssignmentOptions(), locationId)) {
      this.locationForm.controls.location_id.setValue(null, { emitEvent: false });
    }

    const batchId = this.toPositiveInt(this.locationForm.controls.batch_id.value);
    if (!this.assignmentIsBatched() && batchId != null) {
      this.locationForm.controls.batch_id.setValue(null, { emitEvent: false });
      this.locationFormVersion.update((version) => version + 1);
      return;
    }
    if (batchId != null && !this.hasStorageOption(this.batchAssignmentOptions(), batchId)) {
      this.locationForm.controls.batch_id.setValue(null, { emitEvent: false });
    }

    this.locationFormVersion.update((version) => version + 1);
  }

  private hasStorageOption(options: StorageAssignmentOption[], value: number): boolean {
    return options.some((option) => this.toPositiveInt(option.value) === value);
  }

  getFormErrorMessage(errorKey: string): string {
    return this.formErrorMessages[errorKey] || 'Please fix the validation errors.';
  }

  isFormErrorVisible(errorKey: string): boolean {
    if (!this.form.hasError(errorKey)) return false;

    const issuanceTouched = this.form.get('issuance_order')?.touched ?? false;
    const canExpireTouched = this.form.get('can_expire_flag')?.touched ?? false;
    return issuanceTouched || canExpireTouched || this.form.touched;
  }

  private setSubmissionError(message: string, details: string[], formErrorKey: string): void {
    this.submissionError.set(message);
    this.submissionErrorDetails.set(details);
    this.form.setErrors({
      ...(this.form.errors || {}),
      [formErrorKey]: true,
    });
  }

  private clearSubmissionError(): void {
    this.submissionError.set(null);
    this.submissionErrorDetails.set([]);
    this.duplicateCanonicalConflict.set(null);

    const formErrors = this.form.errors;
    if (!formErrors) return;

    const nextErrors: Record<string, unknown> = { ...formErrors };
    delete nextErrors[this.inactiveItemForwardWriteCode];
    delete nextErrors[this.duplicateCanonicalItemCodeError];
    delete nextErrors['versionConflict'];
    delete nextErrors['submitFailure'];
    this.form.setErrors(Object.keys(nextErrors).length ? nextErrors : null);
  }

  private extractDuplicateCanonicalItemConflict(error: unknown): DuplicateCanonicalItemConflict | null {
    const err = error as {
      error?: {
        errors?: Record<string, unknown>;
      };
    };
    const rawConflict = err?.error?.errors?.[this.duplicateCanonicalItemCodeError];
    if (!rawConflict || typeof rawConflict !== 'object') {
      return null;
    }

    const conflict = rawConflict as Record<string, unknown>;
    const existingItemRaw = conflict['existing_item'];
    const existingItem = existingItemRaw && typeof existingItemRaw === 'object'
      ? {
          item_id: this.toRecordIdentifier((existingItemRaw as Record<string, unknown>)['item_id']),
          item_name: String((existingItemRaw as Record<string, unknown>)['item_name'] ?? '').trim(),
          item_code: String((existingItemRaw as Record<string, unknown>)['item_code'] ?? '').trim(),
        }
      : null;

    return {
      code: String(conflict['code'] ?? '').trim(),
      ifrc_item_ref_id: this.toRecordIdentifier(conflict['ifrc_item_ref_id']),
      item_code: String(conflict['item_code'] ?? '').trim(),
      existing_item: existingItem,
    };
  }

  private buildDuplicateCanonicalConflictDetails(conflict: DuplicateCanonicalItemConflict): string[] {
    const details: string[] = [];
    if (conflict.item_code) {
      details.push(`Canonical IFRC Code: ${conflict.item_code}`);
    }
    if (conflict.existing_item?.item_name) {
      const existingItemSummary = conflict.existing_item.item_id != null && conflict.existing_item.item_id !== ''
        ? `${conflict.existing_item.item_name} (#${conflict.existing_item.item_id})`
        : conflict.existing_item.item_name;
      details.push(`Existing Item: ${existingItemSummary}`);
    }
    if (conflict.existing_item?.item_code) {
      details.push(`Existing Item Code: ${conflict.existing_item.item_code}`);
    }
    return details;
  }

  private extractSaveFailureResponse(error: unknown): MasterSaveFailureResponse | null {
    const err = error as {
      error?: MasterSaveFailureResponse;
    };
    return err?.error && typeof err.error === 'object'
      ? err.error
      : null;
  }

  private getItemSaveFailureMessage(
    status: number | undefined,
    payload: MasterSaveFailureResponse | null,
  ): string {
    const detail = String(payload?.detail ?? '').trim();
    if (status === 503) {
      if (!detail) {
        return 'The item save service is temporarily unavailable. Please try again.';
      }
      return /temporar|unavailable/i.test(detail)
        ? detail
        : `The item save service is temporarily unavailable. ${detail}`;
    }
    return detail || 'Save failed.';
  }

  private buildItemSaveFailureDetails(
    payload: MasterSaveFailureResponse | null,
    message: string,
  ): string[] {
    const details: string[] = [];
    const diagnostic = String(payload?.diagnostic ?? '').trim();
    if (diagnostic && diagnostic !== message) {
      details.push(`Diagnostic: ${diagnostic}`);
    }

    const warningMessages = (payload?.warnings ?? [])
      .map((warning) => this.normalizeSaveFailureWarning(warning))
      .filter((warning): warning is string => warning.length > 0)
      .filter((warning) => warning !== message && !details.includes(warning));

    return [...details, ...warningMessages];
  }

  private normalizeSaveFailureWarning(warning: string): string {
    const normalized = String(warning ?? '').trim();
    if (!normalized) {
      return '';
    }
    return /\s/.test(normalized) ? normalized : this.humanizeToken(normalized);
  }

  private extractInactiveItemForwardWriteGuard(error: unknown): InactiveItemForwardWriteGuard | null {
    const err = error as {
      error?: {
        errors?: Record<string, unknown>;
      };
    };
    const rawGuard = err?.error?.errors?.[this.inactiveItemForwardWriteCode];
    if (!rawGuard || typeof rawGuard !== 'object') {
      return null;
    }

    const guard = rawGuard as Record<string, unknown>;
    const itemIds = Array.isArray(guard['item_ids'])
      ? guard['item_ids']
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value > 0)
      : [];

    return {
      table: String(guard['table'] || '').trim() || 'unknown',
      workflow_state: String(guard['workflow_state'] || '').trim() || 'UNKNOWN',
      item_ids: [...new Set(itemIds)].sort((a, b) => a - b),
    };
  }

  private buildInactiveItemGuardDetails(guard: InactiveItemForwardWriteGuard): string[] {
    const details = [
      `Table: ${this.humanizeToken(guard.table)}`,
      `Workflow State: ${this.humanizeToken(guard.workflow_state)}`,
    ];

    if (guard.item_ids.length > 0) {
      details.push(`Inactive Item ID(s): ${guard.item_ids.join(', ')}`);
    }

    return details;
  }

  private applyInactiveItemControlError(guard: InactiveItemForwardWriteGuard): void {
    const itemControl = this.form.get('item_id');
    if (!itemControl) return;

    const message = guard.item_ids.length > 0
      ? `Inactive item ID(s): ${guard.item_ids.join(', ')}`
      : 'Selected item is inactive for forward-looking writes.';

    itemControl.setErrors({
      ...(itemControl.errors || {}),
      server: message,
    });
    itemControl.markAsTouched();
  }

  private humanizeToken(rawValue: string): string {
    const normalized = String(rawValue || '').trim();
    if (!normalized) return 'Unknown';

    return normalized
      .split('_')
      .filter(Boolean)
      .map((token) => token.charAt(0).toUpperCase() + token.slice(1).toLowerCase())
      .join(' ');
  }

  // ── Wizard navigation ──

  goToStep(index: number): void {
    if (index < 0 || index >= this.totalSteps()) return;
    // Allow going back freely; going forward requires validation of all prior steps.
    if (index > this.currentStep() && this.focusFirstInvalidStep(index)) {
      return;
    }
    this.currentStep.set(index);
  }

  goNext(): void {
    if (this.isOnReviewStep()) return;
    const nextStep = this.currentStep() + 1;
    if (this.focusFirstInvalidStep(nextStep)) {
      return;
    }
    this.currentStep.set(nextStep);
  }

  goBack(): void {
    if (this.currentStep() > 0) {
      this.currentStep.set(this.currentStep() - 1);
    }
  }

  getStepState(index: number): 'done' | 'active' | 'future' {
    const current = this.currentStep();
    if (index === current) return 'active';
    if (index < current) return 'done';
    return 'future';
  }

  navigateToFirstInvalidStep(): void {
    this.focusFirstInvalidStep(this.renderableFieldGroups().length);
  }

  private areStepsValidThrough(stepIndex: number): boolean {
    return this.findFirstInvalidStep(stepIndex + 1) === null;
  }

  private focusFirstInvalidStep(maxExclusive: number): boolean {
    const firstInvalidStep = this.findFirstInvalidStep(maxExclusive);
    if (firstInvalidStep == null) {
      return false;
    }

    this.markStepFieldsTouched(firstInvalidStep);
    this.currentStep.set(firstInvalidStep);
    return true;
  }

  private findFirstInvalidStep(maxExclusive: number): number | null {
    const groups = this.renderableFieldGroups();
    const limit = Math.min(maxExclusive, groups.length);
    for (let i = 0; i < limit; i++) {
      if (!this.isStepValid(i)) {
        return i;
      }
    }
    return null;
  }

  private isStepValid(stepIndex: number): boolean {
    const groups = this.renderableFieldGroups();
    if (stepIndex >= groups.length) return true;
    const group = groups[stepIndex];
    const fields = this.getRenderableFields(group);
    if (this.hasRelevantFormError(group, fields)) {
      return false;
    }
    // Also check taxonomy fields if this is a classification group
    if (this.isItemClassificationGroup(group.label)) {
      const taxonomyFields = ['category_id', 'ifrc_family_id', 'ifrc_item_ref_id'];
      for (const fieldName of taxonomyFields) {
        const control = this.form.get(fieldName);
        if (control && control.invalid) return false;
      }
    }
    for (const field of fields) {
      const control = this.form.get(field.field);
      if (control && control.invalid) return false;
    }
    return true;
  }

  private hasRelevantFormError(group: FormFieldGroup, fields: MasterFieldConfig[]): boolean {
    const fieldNames = new Set(fields.map((field) => field.field));

    if (this.isItemClassificationGroup(group.label)) {
      fieldNames.add('category_id');
      fieldNames.add('ifrc_family_id');
      fieldNames.add('ifrc_item_ref_id');
    }

    if (
      (fieldNames.has('issuance_order') || fieldNames.has('can_expire_flag'))
      && (this.form.hasError('fefoRequiresExpiry') || this.form.hasError('expiryRequiresFefo'))
    ) {
      return true;
    }

    if (
      fieldNames.has('ifrc_family_id')
      && (
        this.form.hasError('ifrcFamilyRequired')
        || this.form.hasError('ifrcFamilyOutsideCategory')
        || this.form.hasError('ifrcFamilyForReferenceRequired')
      )
    ) {
      return true;
    }

    if (
      fieldNames.has('ifrc_item_ref_id')
      && (
        this.form.hasError('ifrcReferenceRequired')
        || this.form.hasError('ifrcReferenceOutsideFamily')
        || this.form.hasError('ifrcFamilyForReferenceRequired')
      )
    ) {
      return true;
    }

    if (group.key === 'uom-conversions' && this.form.hasError('invalidItemUomConversions')) {
      return true;
    }

    return false;
  }

  private validateItemUomConversions(): ValidationErrors | null {
    if (this.config()?.tableKey !== 'items') {
      return null;
    }

    return this.getItemUomConversionValidationDetails().length > 0
      ? { invalidItemUomConversions: true }
      : null;
  }

  private getItemUomConversionValidationDetails(): string[] {
    return this.itemUomConversions().flatMap((row, index) => {
      const details: string[] = [];
      const rowNumber = index + 1;
      const normalizedUomCode = row.uom_code.trim();

      if (!normalizedUomCode) {
        details.push(`Item UOM conversion row ${rowNumber} is missing an alternate UOM.`);
      }

      if (row.conversion_factor == null) {
        details.push(`Item UOM conversion row ${rowNumber} is missing the units-in-alternate value.`);
      } else if (row.conversion_factor <= 0) {
        details.push(`Item UOM conversion row ${rowNumber} must use a conversion factor greater than 0.`);
      }

      return details;
    });
  }

  private getValidatedItemUomConversions(): { uom_code: string; conversion_factor: number }[] {
    const details = this.getItemUomConversionValidationDetails();
    if (details.length > 0) {
      throw new ItemUomConversionValidationError(details);
    }

    return this.itemUomConversions().map((row) => ({
      uom_code: row.uom_code.trim(),
      conversion_factor: row.conversion_factor as number,
    }));
  }

  private handleInvalidItemUomConversionSubmission(details = this.getItemUomConversionValidationDetails()): void {
    this.setSubmissionError(
      'Please complete each item UOM conversion row before saving.',
      details,
      'submitFailure',
    );
    this.notify.showWarning('Please fix the validation errors.');
  }

  private syncItemUomConversionState(): void {
    this.form.markAsDirty();
    this.formStateVersion.update(v => v + 1);
    this.form.updateValueAndValidity({ emitEvent: false });
    if (this.submissionError()) {
      this.clearSubmissionError();
    }
  }

  private markStepFieldsTouched(stepIndex: number): void {
    const groups = this.renderableFieldGroups();
    if (stepIndex >= groups.length) return;
    const group = groups[stepIndex];
    const fields = this.getRenderableFields(group);
    if (this.isItemClassificationGroup(group.label)) {
      for (const fieldName of ['category_id', 'ifrc_family_id', 'ifrc_item_ref_id']) {
        this.form.get(fieldName)?.markAsTouched();
      }
    }
    for (const field of fields) {
      this.form.get(field.field)?.markAsTouched();
    }
  }

  getReviewDisplayValue(field: MasterFieldConfig): string {
    const rawValue = this.form.get(field.field)?.value;
    if (rawValue == null || rawValue === '') return '\u2014';

    if (field.type === 'boolean') {
      return rawValue ? 'Yes' : 'No';
    }

    if (field.type === 'select' && field.options) {
      const match = field.options.find((opt) => this.sameValue(opt.value, rawValue));
      return match?.label ?? String(rawValue);
    }

    if (field.type === 'lookup' && field.lookupTable) {
      const items = this.lookups()[field.lookupTable] || [];
      const match = items.find((item) => this.sameValue(item.value, rawValue));
      return match?.label ?? String(rawValue);
    }

    if (field.type === 'date' && rawValue instanceof Date) {
      return rawValue.toLocaleDateString();
    }

    return String(rawValue);
  }

  private getReviewFields(group: FormFieldGroup): MasterFieldConfig[] {
    const fields = this.getRenderableFields(group);
    if (!this.isItemClassificationGroup(group.label)) {
      return fields;
    }

    const taxonomyFields = ['category_id', 'ifrc_family_id', 'ifrc_item_ref_id']
      .map((fieldName) => group.fields.find((field) => field.field === fieldName))
      .filter((field): field is MasterFieldConfig => !!field);
    const taxonomyNames = new Set(taxonomyFields.map((field) => field.field));

    return [
      ...taxonomyFields,
      ...fields.filter((field) => !taxonomyNames.has(field.field)),
    ];
  }

  private resetWizardUiState(): void {
    this.currentStep.set(0);
    this.ifrcAppliedConfirmation.set(null);
    this.ifrcCodeUpdatedOnStep1.set(false);
    this.expandedCandidateIds.set(new Set());
    this.itemUomConversions.set([]);
    this.previousDefaultUom = null;
  }
}

