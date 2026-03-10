import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  inject, signal, computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  AbstractControl,
  ReactiveFormsModule,
  FormGroup,
  FormControl,
  Validators,
  ValidationErrors,
} from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Observable, of, Subject } from 'rxjs';
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

import { LookupItem, MasterFieldConfig, MasterTableConfig } from '../../models/master-data.models';
import {
  IfrcFamilyLookup,
  IfrcReferenceLookup,
  ItemCategoryLookup,
} from '../../models/item-taxonomy.models';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import { MasterDataService } from '../../services/master-data.service';
import { IfrcSuggestService } from '../../services/ifrc-suggest.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { ReplenishmentService } from '../../../replenishment/services/replenishment.service';
import { validateFefoRequiresExpiry } from '../../models/table-configs/item.config';
import { IFRCSuggestion } from '../../models/ifrc-suggest.models';

interface InactiveItemForwardWriteGuard {
  table: string;
  workflow_state: string;
  item_ids: number[];
}

interface ResolvedIfrcSuggestion {
  family: IfrcFamilyLookup | null;
  reference: IfrcReferenceLookup | null;
  warning: string | null;
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

@Component({
  selector: 'dmis-master-form-page',
  standalone: true,
  imports: [
    CommonModule, ReactiveFormsModule, RouterModule,
    TextFieldModule,
    MatAutocompleteModule,
    MatFormFieldModule, MatInputModule, MatSelectModule, MatButtonModule,
    MatIconModule, MatSlideToggleModule, MatDatepickerModule, MatNativeDateModule,
    MatProgressBarModule, MatCardModule, MatTooltipModule,
  ],
  templateUrl: './master-form-page.component.html',
  styleUrl: './master-form-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterFormPageComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(MasterDataService);
  private ifrcSuggestService = inject(IfrcSuggestService);
  private replenishmentService = inject(ReplenishmentService);
  private notify = inject(DmisNotificationService);
  private destroyRef = inject(DestroyRef);

  config = signal<MasterTableConfig | null>(null);
  form = new FormGroup<Record<string, FormControl>>({});
  isEdit = signal(false);
  isLoading = signal(false);
  isSaving = signal(false);
  assigningLocation = signal(false);
  lookups = signal<Record<string, LookupItem[]>>({});
  lookupLoading = signal<Record<string, boolean>>({});
  lookupErrors = signal<Record<string, string>>({});
  ifrcLoading = signal(false);
  ifrcSuggestion = signal<IFRCSuggestion | null>(null);
  ifrcSuggestionResolution = signal<ResolvedIfrcSuggestion | null>(null);
  ifrcError = signal<string | null>(null);
  submissionError = signal<string | null>(null);
  submissionErrorDetails = signal<string[]>([]);
  duplicateCanonicalConflict = signal<DuplicateCanonicalItemConflict | null>(null);
  pk = signal<string | number | null>(null);
  referenceSearchControl = new FormControl<string>('', { nonNullable: true });

  /** IFRC specification hint controls used only to improve suggestion quality */
  ifrcSpecForm = new FormGroup({
    size_weight: new FormControl<string>(''),
    form: new FormControl<string>(''),
    material: new FormControl<string>(''),
  });

  private readonly ifrcTrigger$ = new Subject<string>();
  readonly formErrorMessages: Record<string, string> = {
    fefoRequiresExpiry: 'Can Expire must be enabled when Issuance Order is FEFO.',
    expiryRequiresFefo: 'Issuance Order must be FEFO when Can Expire is enabled.',
  };

  private versionNbr: number | null = null;
  private acceptedIfrcSuggestLogId: string | null = null;
  private applyingTaxonomyPatch = false;
  private selectedReferenceOption: IfrcReferenceLookup | null = null;
  private itemCodeFallbackValue: string | null = null;
  private legacyItemCodeValue: string | null = null;
  private itemHadMappedClassificationOnLoad = false;
  private readonly duplicateCanonicalItemCodeError = 'duplicate_canonical_item_code';
  private readonly inactiveItemForwardWriteCode = 'inactive_item_forward_write_blocked';
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

  /** Group form fields by their group property */
  fieldGroups = computed(() => {
    const cfg = this.config();
    if (!cfg) return [];
    const groups: { label: string; fields: MasterFieldConfig[] }[] = [];
    const seen = new Map<string, MasterFieldConfig[]>();

    for (const f of cfg.formFields) {
      const groupLabel = f.group || 'General';
      if (!seen.has(groupLabel)) {
        seen.set(groupLabel, []);
        groups.push({ label: groupLabel, fields: seen.get(groupLabel)! });
      }
      seen.get(groupLabel)!.push(f);
    }
    return groups;
  });

  isItemRecord = computed(() => this.config()?.tableKey === 'items');
  isBatchedItem = computed(() => Boolean(this.form.get('is_batched_flag')?.value));
  canAssignLocation = computed(() => this.isItemRecord() && this.isEdit() && this.toPositiveInt(this.pk()) != null);
  itemCategoryOptions = computed(() => this.readLookup<ItemCategoryLookup>('item_categories'));
  itemIfrcFamilyOptions = computed(() => this.readLookup<IfrcFamilyLookup>('ifrc_families'));
  itemIfrcReferenceOptions = computed(() => this.readLookup<IfrcReferenceLookup>('ifrc_references'));

  ngOnInit(): void {
    this.route.data.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(data => {
      const routePath = data['routePath'] as string;
      const cfg = ALL_TABLE_CONFIGS[routePath];
      if (cfg) {
        this.config.set(cfg);
        this.buildForm(cfg);
        this.setupItemTaxonomyState(cfg);
        this.setupItemIfrcSuggestion(cfg);
        this.loadLookups(cfg);
      }
    });

    this.route.params.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(params => {
      const pkParam = params['pk'];
      if (pkParam && pkParam !== 'new') {
        this.pk.set(pkParam);
        this.isEdit.set(true);
        this.loadRecord();
      }
    });
  }

  private buildForm(cfg: MasterTableConfig): void {
    for (const field of cfg.formFields) {
      const validators = [];
      if (field.required) validators.push(Validators.required);
      if (field.maxLength) validators.push(Validators.maxLength(field.maxLength));
      if (field.pattern) validators.push(Validators.pattern(field.pattern));
      if (field.type === 'email') {
        validators.push(Validators.email);
      }

      this.form.addControl(
        field.field,
        new FormControl(field.defaultValue ?? null, validators),
      );
    }

    if (cfg.tableKey === 'items') {
      this.form.setValidators([
        validateFefoRequiresExpiry,
        (control) => this.validateItemClassification(control),
      ]);
      this.form.updateValueAndValidity({ emitEvent: false });
    }

    this.form.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      if (this.submissionError()) {
        this.clearSubmissionError();
      }
    });
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
          this.syncDisplayedItemCode();
          this.form.updateValueAndValidity({ emitEvent: false });
        }
      }

      this.updateItemTaxonomyControlState();
      this.loadItemReferenceOptions(selectedFamilyId, search);
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
    const requiresMappedClassification = !this.isEdit() || this.itemHadMappedClassificationOnLoad;

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
    this.ifrcSuggestion.set(null);
    this.ifrcSuggestionResolution.set(null);
    this.ifrcError.set(null);
    this.clearAcceptedSuggestion();

    if (cfg.tableKey !== 'items') return;

    const itemNameControl = this.form.get('item_name');
    if (!itemNameControl) return;

    // Item name changes -> push to trigger stream (debounced + deduplicated)
    itemNameControl.valueChanges.pipe(
      map((v) => (typeof v === 'string' ? v.trim() : '')),
      debounceTime(600),
      distinctUntilChanged(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((name) => {
      this.clearAcceptedSuggestion();
      this.ifrcTrigger$.next(name);
    });

    // Spec hint changes -> re-trigger with current item name
    this.ifrcSpecForm.valueChanges.pipe(
      debounceTime(400),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.clearAcceptedSuggestion();
      const name = String(itemNameControl.value ?? '').trim();
      this.ifrcTrigger$.next(name);
    });

    // Main suggest pipeline
    this.ifrcTrigger$.pipe(
      switchMap((itemName) => {
        if (itemName.length < 3) {
          this.ifrcSuggestion.set(null);
          this.ifrcSuggestionResolution.set(null);
          this.ifrcError.set(null);
          return of(null);
        }
        this.ifrcLoading.set(true);
        const { size_weight, form, material } = this.ifrcSpecForm.value;
        return this.ifrcSuggestService.suggest(itemName, {
          size_weight: size_weight ?? '',
          form: form ?? '',
          material: material ?? '',
        }).pipe(
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
      this.resolveIfrcSuggestion(suggestion);
    });
  }

  onAcceptIfrcSuggestion(): void {
    const suggestion = this.ifrcSuggestion();
    const resolved = this.ifrcSuggestionResolution();
    if (!suggestion || !resolved?.family || !resolved.reference) {
      this.notify.showError('Resolve the suggested IFRC reference before applying it.');
      return;
    }

    const categoryControl = this.form.get('category_id');
    const familyControl = this.form.get('ifrc_family_id');
    const referenceControl = this.form.get('ifrc_item_ref_id');
    if (!categoryControl || !familyControl || !referenceControl) {
      return;
    }

    this.applyingTaxonomyPatch = true;
    const family = resolved.family;
    const reference = resolved.reference;

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
    this.syncDisplayedItemCode(reference);
    this.loadItemFamilyOptions(family.category_id, family.value);
    this.loadItemReferenceOptions(
      family.value,
      String(reference.ifrc_code ?? reference.label ?? ''),
      reference.value,
    );
    this.updateItemTaxonomyControlState();
    this.form.updateValueAndValidity({ emitEvent: false });
    this.notify.showSuccess('Suggested IFRC classification applied.');
  }

  onRejectIfrcSuggestion(): void {
    this.clearAcceptedSuggestion();
    this.ifrcSuggestion.set(null);
    this.ifrcSuggestionResolution.set(null);
    this.ifrcError.set(null);
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
    this.clearAcceptedSuggestion();
    this.syncDisplayedItemCode(reference);
    this.updateItemTaxonomyControlState();
    this.form.updateValueAndValidity({ emitEvent: false });
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
    this.syncDisplayedItemCode();
    this.updateItemTaxonomyControlState();
    this.form.updateValueAndValidity({ emitEvent: false });
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

  private writeLookup(lookupKey: string, items: LookupItem[]): void {
    this.lookups.set({
      ...this.lookups(),
      [lookupKey]: items,
    });
  }

  private setLookupLoading(lookupKey: string, isLoading: boolean): void {
    this.lookupLoading.set({
      ...this.lookupLoading(),
      [lookupKey]: isLoading,
    });
  }

  private setLookupError(lookupKey: string, message: string | null): void {
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

  private findLookupByValue<T extends LookupItem>(items: T[], value: unknown): T | null {
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
    const lookupTables = new Map<string, string>();
    for (const field of lookupFields) {
      lookupTables.set(field.lookupTable!, field.label);
    }
    if (cfg.tableKey === 'items') {
      lookupTables.set('inventory', 'Inventory');
      lookupTables.set('locations', 'Location');
      this.loadItemCategoryOptions();
      this.writeLookup('ifrc_families', []);
      this.writeLookup('ifrc_references', []);
    }

    this.lookupErrors.set({});

    for (const [tableKey, label] of lookupTables.entries()) {
      this.setLookupLoading(tableKey, true);
      this.service.lookup(tableKey).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: (items) => {
          this.writeLookup(tableKey, items);
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
    if (categoryId == null || categoryId === '') {
      this.writeLookup('ifrc_families', []);
      this.setLookupLoading('ifrc_families', false);
      this.updateItemTaxonomyControlState();
      this.form.updateValueAndValidity({ emitEvent: false });
      return;
    }

    this.setLookupLoading('ifrc_families', true);
    this.updateItemTaxonomyControlState();
    this.service.lookupIfrcFamilies({ categoryId }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (items) => {
        this.writeLookup('ifrc_families', items);
        this.setLookupLoading('ifrc_families', false);
        this.setLookupError('ifrc_families', null);

        const familyControl = this.form.get('ifrc_family_id');
        const selectedValue = preserveValue ?? familyControl?.value;
        if (familyControl && selectedValue && !this.findLookupByValue(items, selectedValue)) {
          familyControl.patchValue(null, { emitEvent: false });
        }
        this.updateItemTaxonomyControlState();
        this.form.updateValueAndValidity({ emitEvent: false });
      },
      error: () => {
        this.writeLookup('ifrc_families', []);
        this.setLookupLoading('ifrc_families', false);
        this.setLookupError('ifrc_families', 'Failed to load IFRC family options.');
        this.updateItemTaxonomyControlState();
      },
    });
  }

  private loadItemReferenceOptions(
    familyId: string | number | null | undefined,
    search = '',
    preserveValue: string | number | null = null,
  ): void {
    if (familyId == null || familyId === '') {
      this.writeLookup('ifrc_references', []);
      this.setLookupLoading('ifrc_references', false);
      this.updateItemTaxonomyControlState();
      this.form.updateValueAndValidity({ emitEvent: false });
      return;
    }

    this.setLookupLoading('ifrc_references', true);
    this.updateItemTaxonomyControlState();
    this.service.lookupIfrcReferences({
      ifrcFamilyId: familyId,
      search: search || undefined,
      limit: 50,
    }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (items) => {
        this.writeLookup('ifrc_references', items);
        this.setLookupLoading('ifrc_references', false);
        this.setLookupError('ifrc_references', null);

        const referenceControl = this.form.get('ifrc_item_ref_id');
        const selectedValue = preserveValue ?? referenceControl?.value;
        const selectedReference = this.findLookupByValue(items, selectedValue);
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
        this.writeLookup('ifrc_references', []);
        this.setLookupLoading('ifrc_references', false);
        this.setLookupError('ifrc_references', 'Failed to load IFRC reference options.');
        this.updateItemTaxonomyControlState();
      },
    });
  }

  private resolveIfrcSuggestion(suggestion: IFRCSuggestion): void {
    const familySearch = String(suggestion.family_code ?? '').trim();
    if (!familySearch) {
      this.ifrcSuggestionResolution.set({
        family: null,
        reference: null,
        warning: 'Suggestion did not include a resolvable IFRC family.',
      });
      return;
    }

    this.service.lookupIfrcFamilies({ search: familySearch }).pipe(
      switchMap((families) => {
        const family = this.findMatchingSuggestedFamily(suggestion, families);
        if (!family) {
          return of({
            family: null,
            reference: null,
            warning: 'Suggestion could not be matched to an active IFRC family.',
          } satisfies ResolvedIfrcSuggestion);
        }

        return this.resolveSuggestedReference(suggestion, family).pipe(
          map((reference) => ({
            family,
            reference,
            warning: suggestion.ifrc_code && !reference
              ? 'Suggested IFRC reference could not be matched to an active catalog entry.'
              : null,
          })),
        );
      }),
      catchError(() => of({
        family: null,
        reference: null,
        warning: 'Failed to resolve the IFRC suggestion against the active taxonomy.',
      })),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((resolved) => this.ifrcSuggestionResolution.set(resolved));
  }

  private resolveSuggestedReference(
    suggestion: IFRCSuggestion,
    family: IfrcFamilyLookup,
  ): Observable<IfrcReferenceLookup | null> {
    const primarySearch = String(suggestion.ifrc_code ?? '').trim()
      || String(suggestion.ifrc_description ?? '').trim();
    if (!primarySearch) {
      return of<IfrcReferenceLookup | null>(null);
    }

    return this.service.lookupIfrcReferences({
      ifrcFamilyId: family.value,
      search: primarySearch,
      limit: 25,
    }).pipe(
      map((references) => this.findMatchingSuggestedReference(suggestion, references)),
      switchMap((reference) => {
        if (reference) {
          return of(reference);
        }

        const fallbackSearch = String(suggestion.ifrc_description ?? '').trim();
        if (!fallbackSearch || fallbackSearch === primarySearch) {
          return of<IfrcReferenceLookup | null>(null);
        }

        return this.service.lookupIfrcReferences({
          ifrcFamilyId: family.value,
          search: fallbackSearch,
          limit: 25,
        }).pipe(
          map((references) => this.findMatchingSuggestedReference(suggestion, references)),
        );
      }),
      catchError(() => of<IfrcReferenceLookup | null>(null)),
    );
  }

  private findMatchingSuggestedFamily(
    suggestion: IFRCSuggestion,
    families: IfrcFamilyLookup[],
  ): IfrcFamilyLookup | null {
    const familyCode = String(suggestion.family_code ?? '').trim().toUpperCase();
    const groupCode = String(suggestion.group_code ?? '').trim().toUpperCase();

    return families.find((family) => {
      const sameFamilyCode = String(family.family_code ?? '').trim().toUpperCase() === familyCode;
      const sameGroupCode = !groupCode
        || String(family.group_code ?? '').trim().toUpperCase() === groupCode;
      return sameFamilyCode && sameGroupCode;
    }) ?? null;
  }

  private findMatchingSuggestedReference(
    suggestion: IFRCSuggestion,
    references: IfrcReferenceLookup[],
  ): IfrcReferenceLookup | null {
    const ifrcCode = String(suggestion.ifrc_code ?? '').trim().toUpperCase();
    const description = String(suggestion.ifrc_description ?? '').trim().toUpperCase();

    if (ifrcCode) {
      const exactCodeMatch = references.find((reference) => (
        String(reference.ifrc_code ?? '').trim().toUpperCase() === ifrcCode
      ));
      if (exactCodeMatch) {
        return exactCodeMatch;
      }
    }

    if (!description) {
      return null;
    }

    return references.find((reference) => (
      String(reference.label ?? '').trim().toUpperCase() === description
    )) ?? null;
  }

  private clearAcceptedSuggestion(): void {
    this.acceptedIfrcSuggestLogId = null;
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
        this.itemCodeFallbackValue = String(record['item_code'] ?? '').trim() || null;
        this.legacyItemCodeValue = String(record['legacy_item_code'] ?? '').trim() || null;

        for (const field of cfg.formFields) {
          const control = this.form.get(field.field);
          if (control && record[field.field] !== undefined) {
            control.setValue(record[field.field], { emitEvent: false });
          }
          if (field.readonlyOnEdit && this.isEdit() && control) {
            control.disable();
          }
        }

        if (cfg.tableKey === 'items') {
          const categoryId = record['category_id'] as string | number | null | undefined;
          const familyId = record['ifrc_family_id'] as string | number | null | undefined;
          const referenceId = record['ifrc_item_ref_id'] as string | number | null | undefined;
          this.itemHadMappedClassificationOnLoad = referenceId != null && referenceId !== '';

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
        }

        this.updateItemTaxonomyControlState();
        this.form.updateValueAndValidity({ emitEvent: false });

        this.isLoading.set(false);
      },
      error: () => {
        this.notify.showError('Failed to load record.');
        this.navigateBack();
      },
    });
  }

  onSave(): void {
    this.clearSubmissionError();

    if (!this.form.valid) {
      this.form.markAllAsTouched();
      return;
    }

    const cfg = this.config();
    if (!cfg) return;

    this.isSaving.set(true);
    const rawData = this.form.getRawValue();

    if (cfg.tableKey === 'items') {
      delete rawData['item_code'];
      delete rawData['legacy_item_code'];
    }

    // Apply uppercase transforms
    for (const field of cfg.formFields) {
      if (field.uppercase && typeof rawData[field.field] === 'string') {
        rawData[field.field] = rawData[field.field].trim().toUpperCase();
      }
    }
    if (cfg.tableKey === 'items' && this.acceptedIfrcSuggestLogId) {
      rawData['ifrc_suggest_log_id'] = this.acceptedIfrcSuggestLogId;
    }

    const obs$ = this.isEdit()
      ? this.service.update(cfg.tableKey, this.pk()!, {
          ...rawData,
          ...(this.versionNbr != null ? { version_nbr: this.versionNbr } : {}),
        })
      : this.service.create(cfg.tableKey, rawData);

    obs$.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => {
        this.clearSubmissionError();
        this.notify.showSuccess(this.isEdit() ? 'Record updated.' : 'Record created.');
        this.service.clearLookupCache(cfg.tableKey);
        const newPk = res.record?.[cfg.pkField] ?? null;
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
        this.isSaving.set(false);
        if (err.status === 400 && err.error?.errors) {
          const errors = err.error.errors as Record<string, string>;
          for (const [field, msg] of Object.entries(errors)) {
            const control = this.form.get(field);
            if (control) {
              control.setErrors({ server: msg });
              control.markAsTouched();
            }
          }
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
          }
          this.notify.showWarning('Please fix the validation errors.');
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
          const message = err.error?.detail || 'Save failed.';
          this.setSubmissionError(message, [], 'submitFailure');
          this.notify.showError(message);
        }
      },
    });
  }

  getRenderableFields(group: { label: string; fields: MasterFieldConfig[] }): MasterFieldConfig[] {
    if (!this.isItemRecord() || group.label !== 'Classification') {
      return group.fields;
    }

    return group.fields.filter((field) => !['category_id', 'ifrc_family_id', 'ifrc_item_ref_id'].includes(field.field));
  }

  isItemClassificationGroup(groupLabel: string): boolean {
    return this.isItemRecord() && groupLabel === 'Classification';
  }

  isItemFamilyRequired(): boolean {
    return !!this.form.get('category_id')?.value
      && (!this.isEdit() || this.itemHadMappedClassificationOnLoad);
  }

  isItemReferenceRequired(): boolean {
    return !!this.form.get('ifrc_family_id')?.value;
  }

  isManagedItemCodeField(fieldName: string): boolean {
    return this.isItemRecord() && fieldName === 'item_code';
  }

  canAcceptResolvedIfrcSuggestion(): boolean {
    return this.ifrcSuggestionResolution()?.reference != null;
  }

  getLegacyItemCode(): string | null {
    return this.legacyItemCodeValue;
  }

  isLookupLoading(lookupKey: string): boolean {
    return this.lookupLoading()[lookupKey] === true;
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
    const suggestion = this.ifrcSuggestion();
    if (resolved?.reference) {
      return this.getItemReferenceLabel(resolved.reference);
    }

    const description = String(suggestion?.ifrc_description ?? '').trim();
    const code = String(suggestion?.ifrc_code ?? '').trim();
    if (!description && !code) {
      return null;
    }

    return code ? `${description || 'Suggested reference'} (${code})` : description;
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

    if (!inventoryId || !locationId) {
      this.locationForm.markAllAsTouched();
      return;
    }

    if (this.isBatchedItem() && !batchId) {
      this.locationForm.controls.batch_id.setErrors({ required: true });
      this.locationForm.controls.batch_id.markAsTouched();
      this.notify.showWarning('Batch ID is required for batched items.');
      return;
    }

    if (!this.isBatchedItem() && batchId) {
      this.notify.showWarning('Batch ID must be empty for non-batched items.');
      this.locationForm.controls.batch_id.setErrors({ server: 'Must be empty for non-batched items.' });
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
      'Inventory Rules': 'inventory_2',
      'Tracking & Behaviour': 'track_changes',
      'Notes & Storage': 'notes',
      'Notes': 'notes',
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
    if (control.errors['required']) return 'This field is required.';
    if (control.errors['min']) return 'Must be a positive number.';
    if (control.errors['server']) return String(control.errors['server']);
    return 'Invalid value.';
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
}
