import {
  ChangeDetectionStrategy, Component, DestroyRef, OnInit, ViewChild, computed, inject, signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import {
  FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators,
} from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatStepper, MatStepperModule } from '@angular/material/stepper';
import { MatTooltipModule } from '@angular/material/tooltip';

import {
  CreateRequestItemPayload,
  CreateRequestPayload,
  RequestReferenceOption,
  RequestDetailResponse,
  UpdateRequestPayload,
  UrgencyCode,
} from '../models/operations.model';
import { OperationsService } from '../services/operations.service';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import {
  AuthRbacService,
  OperationsCapabilities,
} from '../../replenishment/services/auth-rbac.service';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { RequestItemsStepComponent } from './steps/request-items-step.component';
import { RequestReviewStepComponent, ReviewFormValue } from './steps/request-review-step.component';

const DATE_FORMATTER = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});

type RequestItemFormDefaults = Partial<CreateRequestItemPayload> & {
  item_name?: string | null;
};

@Component({
  selector: 'app-relief-request-wizard',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatIconModule,
    MatStepperModule,
    MatProgressBarModule,
    MatTooltipModule,
    DmisSkeletonLoaderComponent,
    RequestItemsStepComponent,
    RequestReviewStepComponent,
  ],
  templateUrl: './relief-request-wizard.component.html',
  styleUrl: './relief-request-wizard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReliefRequestWizardComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly operationsService = inject(OperationsService);
  private readonly notify = inject(DmisNotificationService);
  private readonly auth = inject(AuthRbacService);
  private readonly destroyRef = inject(DestroyRef);

  @ViewChild('stepper') stepper!: MatStepper;

  readonly loading = signal(true);
  readonly referenceLoading = signal(true);
  readonly saving = signal(false);
  readonly error = signal<string | null>(null);
  readonly isEditMode = signal(false);
  readonly completed = signal(false);
  readonly savedRequest = signal<RequestDetailResponse | null>(null);
  readonly currentStepIndex = signal(0);
  readonly requestDateIso = signal<string | null>(null);
  readonly initialAgencyName = signal<string | null>(null);
  readonly initialEventName = signal<string | null>(null);
  readonly agencyOptions = signal<RequestReferenceOption[]>([]);
  readonly eventOptions = signal<RequestReferenceOption[]>([]);
  readonly itemOptions = signal<RequestReferenceOption[]>([]);
  readonly formVersion = signal(0);

  private reliefrqstId: number | null = null;

  readonly requestForm: FormGroup = this.fb.nonNullable.group({
    agency_id: [null as number | null, [Validators.required]],
    urgency_ind: [null as UrgencyCode | null, [Validators.required]],
    eligible_event_id: [null as number | null],
    rqst_notes_text: [''],
    items: this.fb.array([] as FormGroup[]),
  });

  get itemsArray(): FormArray<FormGroup> {
    return this.requestForm.get('items') as FormArray<FormGroup>;
  }

  readonly pageBusy = computed(() =>
    this.loading()
    || this.referenceLoading()
    || !this.auth.loaded()
  );

  readonly capabilities = computed<OperationsCapabilities | null>(() => this.auth.operationsCapabilities());

  readonly creationBlocked = computed(() =>
    !this.isEditMode()
    && this.auth.loaded()
    && !(this.capabilities()?.can_create_relief_request ?? false)
  );

  readonly pageTitle = computed(() =>
    this.isEditMode() ? 'Edit Relief Request' : 'New Relief Request'
  );

  readonly backNavigationTooltip = computed(() =>
    this.isEditMode() ? 'Back to request details' : 'Back to relief requests'
  );

  readonly selectedAgencyName = computed(() => {
    this.formVersion();
    const agencyId = Number(this.requestForm.get('agency_id')?.value ?? 0);
    const matched = this.agencyOptions().find((option) => option.value === agencyId)?.label;
    if (matched) {
      return matched;
    }
    const initialAgencyName = this.initialAgencyName();
    if (initialAgencyName) {
      return initialAgencyName;
    }
    return agencyId ? `Agency ${agencyId}` : 'Not selected';
  });

  readonly selectedEventName = computed(() => {
    this.formVersion();
    const eventId = Number(this.requestForm.get('eligible_event_id')?.value ?? 0);
    const matched = this.eventOptions().find((option) => option.value === eventId)?.label;
    if (matched) {
      return matched;
    }
    const initialEventName = this.initialEventName();
    if (initialEventName) {
      return initialEventName;
    }
    return eventId ? `Event ${eventId}` : 'None selected';
  });

  readonly requestDateText = computed(() => {
    const requestDateIso = this.requestDateIso();
    if (requestDateIso) {
      return formatDisplayDate(requestDateIso);
    }
    return this.isEditMode() ? 'Waiting for request record' : 'System stamped on first save';
  });

  readonly requestDateHint = computed(() =>
    this.requestDateIso()
      ? 'Recorded by Operations when the request was first created.'
      : 'The backend stamps the formal request date when the draft is first saved.'
  );

  readonly submissionModeLabel = computed(() => {
    switch (this.capabilities()?.relief_request_submission_mode) {
      case 'for_subordinate':
        return 'For subordinate entity';
      case 'on_behalf_bridge':
        return 'ODPEM bridge on behalf';
      case 'self':
        return 'Self request';
      default:
        return this.isEditMode() ? 'Draft update' : 'Relief request unavailable';
    }
  });

  readonly submissionModeHint = computed(() => {
    switch (this.capabilities()?.relief_request_submission_mode) {
      case 'for_subordinate':
        return 'Select the subordinate agency or entity by name. This tenant is acting as the request authority for units under its control.';
      case 'on_behalf_bridge':
        return 'Select the beneficiary agency by name. This is the transitional ODPEM bridge lane for on-behalf request entry.';
      case 'self':
        return 'Select the requesting agency by name. This lane is for the active operational tenant requesting assistance for itself.';
      default:
        return 'This route reflects the backend capabilities advertised for the active tenant.';
    }
  });

  readonly workflowLabel = computed(() => {
    if (this.isEditMode()) {
      return 'Draft revision';
    }
    switch (this.capabilities()?.relief_request_submission_mode) {
      case 'for_subordinate':
        return 'Subordinate intake';
      case 'on_behalf_bridge':
        return 'ODPEM bridge intake';
      case 'self':
        return 'Self intake';
      default:
        return 'Request entry';
    }
  });

  readonly reviewFormValue = computed<ReviewFormValue>(() => {
    this.formVersion();
    const raw = this.requestForm.getRawValue();

    return {
      agency_id: raw.agency_id,
      agency_name: this.selectedAgencyName(),
      urgency_ind: raw.urgency_ind,
      eligible_event_id: raw.eligible_event_id,
      event_name: this.selectedEventName(),
      request_date_text: this.requestDateText(),
      submission_mode_label: this.submissionModeLabel(),
      rqst_notes_text: raw.rqst_notes_text,
      items: raw.items.map((item: Record<string, unknown>) => ({
        ...item,
        item_name: this.resolveItemName(item['item_id'], item['item_name']),
      })),
    } as ReviewFormValue;
  });

  readonly currentStageLabel = computed(() => {
    if (this.completed()) {
      return 'Completed';
    }
    return this.currentStepIndex() === 0 ? 'Request Setup' : 'Review & Route';
  });

  readonly isStep1Valid = computed(() => {
    this.formVersion();
    if (this.creationBlocked()) {
      return false;
    }

    const form = this.requestForm;
    const agencyValid = form.get('agency_id')?.valid ?? false;
    const urgencyValid = form.get('urgency_ind')?.valid ?? false;
    const hasItems = this.itemsArray.length > 0;
    const itemsValid = this.itemsArray.valid;
    return agencyValid && urgencyValid && hasItems && itemsValid;
  });

  readonly addItemFn = (): void => this.addItem();
  readonly removeItemFn = (index: number): void => this.removeItem(index);

  ngOnInit(): void {
    this.auth.load();
    this.loadReferenceData();
    this.bindFormReactivity();

    const idParam = this.route.snapshot.paramMap.get('reliefrqstId');
    if (idParam) {
      this.reliefrqstId = Number(idParam);
      this.isEditMode.set(true);
      this.loadExisting();
      return;
    }

    this.loading.set(false);
    this.addItem();
  }

  private bindFormReactivity(): void {
    this.requestForm.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.formVersion.update((version) => version + 1);
      });

    ['agency_id', 'eligible_event_id', 'urgency_ind'].forEach((controlName) => {
      this.requestForm.get(controlName)?.valueChanges
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe(() => {
          clearServerError(this.requestForm.get(controlName));
        });
    });
  }

  private loadReferenceData(): void {
    this.referenceLoading.set(true);

    this.operationsService.getRequestReferenceData()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (references) => {
          this.agencyOptions.update((current) => mergeReferenceOptions(current, references.agencies));
          this.eventOptions.update((current) => mergeReferenceOptions(current, references.events));
          this.itemOptions.update((current) => mergeReferenceOptions(current, references.items));
          this.applyDefaultAgencySelection();
          this.referenceLoading.set(false);
        },
        error: () => {
          this.agencyOptions.set([]);
          this.eventOptions.set([]);
          this.itemOptions.set([]);
          this.referenceLoading.set(false);
          this.notify.showWarning('Relief request reference data could not be loaded. Retry this page once Operations lookups are available.');
        },
      });
  }

  private applyDefaultAgencySelection(): void {
    if (this.isEditMode()) {
      return;
    }

    const agencyControl = this.requestForm.get('agency_id');
    if (agencyControl && agencyControl.value == null && this.agencyOptions().length === 1) {
      agencyControl.setValue(this.agencyOptions()[0].value);
    }
  }

  private loadExisting(): void {
    this.loading.set(true);
    this.error.set(null);

    this.operationsService.getRequest(this.reliefrqstId!)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          if (data.status_code !== 0) {
            this.error.set('Only draft requests can be edited in this workspace.');
            this.loading.set(false);
            return;
          }
          this.populateForm(data);
          this.loading.set(false);
        },
        error: (err: HttpErrorResponse) => {
          const message = err.status === 404
            ? 'Relief request not found.'
            : 'Failed to load request for editing.';
          this.error.set(message);
          this.loading.set(false);
        },
      });
  }

  private populateForm(data: RequestDetailResponse): void {
    this.requestDateIso.set(data.request_date ?? null);
    this.initialAgencyName.set(data.agency_name ?? null);
    this.initialEventName.set(data.event_name ?? null);

    this.requestForm.patchValue({
      agency_id: data.agency_id,
      urgency_ind: data.urgency_ind,
      eligible_event_id: data.eligible_event_id,
      rqst_notes_text: data.rqst_notes_text ?? '',
    });
    const agencyLabel = data.agency_name?.trim() || this.selectedAgencyName();
    const eventLabel = data.event_name?.trim() || this.selectedEventName();
    this.agencyOptions.update((current) => mergeReferenceOptions(current, [{
      value: data.agency_id ?? 0,
      label: agencyLabel,
    }].filter((option) => option.value > 0)));
    this.eventOptions.update((current) => mergeReferenceOptions(current, [{
      value: data.eligible_event_id ?? 0,
      label: eventLabel,
    }].filter((option) => option.value > 0)));

    this.itemsArray.clear();
    for (const item of data.items) {
      this.itemOptions.update((current) => mergeReferenceOptions(current, [{
        value: item.item_id,
        label: item.item_name ?? item.item_code ?? `Item ${item.item_id}`,
      }]));
      this.itemsArray.push(this.createItemGroup({
        item_id: item.item_id,
        item_name: item.item_name ?? item.item_code ?? `Item ${item.item_id}`,
        request_qty: item.request_qty,
        urgency_ind: item.urgency_ind ?? undefined,
        rqst_reason_desc: item.rqst_reason_desc ?? undefined,
        required_by_date: item.required_by_date ?? undefined,
      }));
    }

    this.formVersion.update((version) => version + 1);
  }

  addItem(): void {
    this.itemsArray.push(this.createItemGroup());
  }

  removeItem(index: number): void {
    this.itemsArray.removeAt(index);
  }

  private createItemGroup(defaults?: RequestItemFormDefaults): FormGroup {
    const group = this.fb.nonNullable.group({
      item_id: [defaults?.item_id ?? null as number | string | null, [Validators.required, selectedReferenceValidator]],
      item_name: [defaults?.item_name ?? '' as string],
      request_qty: [defaults?.request_qty ? Number(defaults.request_qty) : null as number | null, [Validators.required, Validators.min(1)]],
      urgency_ind: [defaults?.urgency_ind ?? null as UrgencyCode | null],
      rqst_reason_desc: [defaults?.rqst_reason_desc ?? ''],
      required_by_date: [defaults?.required_by_date ?? null as string | null],
    });

    group.get('urgency_ind')!.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((urgency) => {
        const reasonCtrl = group.get('rqst_reason_desc')!;
        if (urgency === 'C' || urgency === 'H') {
          reasonCtrl.setValidators([Validators.required]);
        } else {
          reasonCtrl.clearValidators();
        }
        reasonCtrl.updateValueAndValidity({ emitEvent: false });
      });

    return group;
  }

  private resolveItemName(itemId: unknown, fallback: unknown): string {
    const fallbackText = typeof fallback === 'string' ? fallback.trim() : '';
    if (typeof itemId === 'number' && Number.isFinite(itemId) && itemId > 0) {
      const matched = this.itemOptions().find((option) => option.value === itemId)?.label;
      return matched ?? (fallbackText || `Item ${itemId}`);
    }
    if (typeof itemId === 'string' && itemId.trim()) {
      return itemId.trim();
    }
    return fallbackText || 'Not selected';
  }

  onSaveAsDraft(): void {
    this.saveRequest(false);
  }

  onSaveAndSubmit(): void {
    this.saveRequest(true);
  }

  private saveRequest(andSubmit: boolean): void {
    clearServerError(this.requestForm.get('agency_id'));
    clearServerError(this.requestForm.get('eligible_event_id'));

    if (this.creationBlocked()) {
      this.notify.showError('The active tenant is not allowed to create relief requests in this Operations flow.');
      return;
    }

    if (this.requestForm.invalid) {
      this.requestForm.markAllAsTouched();
      this.itemsArray.controls.forEach((control) => (control as FormGroup).markAllAsTouched());
      this.notify.showWarning('Please fix the form errors before saving.');
      return;
    }

    if (this.itemsArray.length === 0) {
      this.notify.showWarning('Please add at least one item.');
      return;
    }

    this.saving.set(true);
    const raw = this.requestForm.getRawValue();

    const items: CreateRequestItemPayload[] = raw.items.map((item: Record<string, unknown>) => {
      const payload: CreateRequestItemPayload = {
        item_id: Number(item['item_id']),
        request_qty: String(item['request_qty']),
      };
      if (item['urgency_ind']) {
        payload.urgency_ind = item['urgency_ind'] as UrgencyCode;
      }
      if (item['rqst_reason_desc']) {
        payload.rqst_reason_desc = item['rqst_reason_desc'] as string;
      }
      if (item['required_by_date']) {
        const dateValue = item['required_by_date'];
        payload.required_by_date = dateValue instanceof Date
          ? dateValue.toISOString().split('T')[0]
          : String(dateValue);
      }
      return payload;
    });

    if (this.isEditMode() && this.reliefrqstId) {
      const updatePayload: UpdateRequestPayload = {
        agency_id: raw.agency_id,
        urgency_ind: raw.urgency_ind as UrgencyCode,
        eligible_event_id: raw.eligible_event_id,
        rqst_notes_text: raw.rqst_notes_text || undefined,
        items,
      };

      this.operationsService.updateRequest(this.reliefrqstId, updatePayload)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (saved) => this.handleSaveSuccess(saved, andSubmit),
          error: (err) => this.handleSaveError(err),
        });
      return;
    }

    const createPayload: CreateRequestPayload = {
      agency_id: raw.agency_id,
      urgency_ind: raw.urgency_ind as UrgencyCode,
      eligible_event_id: raw.eligible_event_id,
      rqst_notes_text: raw.rqst_notes_text || undefined,
      items,
    };

    this.operationsService.createRequest(createPayload)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (saved) => this.handleSaveSuccess(saved, andSubmit),
        error: (err) => this.handleSaveError(err),
      });
  }

  private handleSaveSuccess(saved: RequestDetailResponse, andSubmit: boolean): void {
    this.reliefrqstId = saved.reliefrqst_id;
    this.requestDateIso.set(saved.request_date ?? this.requestDateIso());
    this.initialAgencyName.set(saved.agency_name ?? this.selectedAgencyName());
    this.initialEventName.set(saved.event_name ?? this.selectedEventName());

    if (andSubmit) {
      this.operationsService.submitRequest(saved.reliefrqst_id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (submitted) => {
            this.saving.set(false);
            this.savedRequest.set(submitted);
            this.completed.set(true);
            this.notify.showSuccess('Request saved and submitted for review.');
          },
          error: (err: HttpErrorResponse) => {
            this.saving.set(false);
            this.savedRequest.set(saved);
            this.completed.set(true);
            const detail = (err.error as Record<string, unknown>)?.['detail'];
            const message = typeof detail === 'string' ? detail : 'Request saved as draft, but submission failed.';
            this.notify.showWarning(message);
          },
        });
      return;
    }

    this.saving.set(false);
    this.savedRequest.set(saved);
    this.completed.set(true);
    this.notify.showSuccess('Request saved as draft.');
  }

  private handleSaveError(err: HttpErrorResponse): void {
    this.saving.set(false);
    const errors = isRecord(err.error) && isRecord(err.error['errors'])
      ? err.error['errors'] as Record<string, unknown>
      : null;

    const agencyMessage = extractMessage(errors?.['agency_id']);
    if (agencyMessage) {
      this.requestForm.get('agency_id')?.setErrors({ server: agencyMessage });
      this.requestForm.get('agency_id')?.markAsTouched();
    }

    const eventMessage = extractMessage(errors?.['eligible_event_id']);
    if (eventMessage) {
      this.requestForm.get('eligible_event_id')?.setErrors({ server: eventMessage });
      this.requestForm.get('eligible_event_id')?.markAsTouched();
    }

    const message = extractMessage(err.error) ?? 'Failed to save request. Please try again.';
    this.notify.showError(message);
  }

  navigateToDetail(): void {
    if (this.reliefrqstId) {
      this.router.navigate(['/operations/relief-requests', this.reliefrqstId]);
    }
  }

  navigateToList(): void {
    this.router.navigate(['/operations/relief-requests']);
  }

  goBack(): void {
    if (this.isEditMode() && this.reliefrqstId) {
      this.router.navigate(['/operations/relief-requests', this.reliefrqstId]);
      return;
    }
    this.router.navigate(['/operations/relief-requests']);
  }
}

function selectedReferenceValidator(control: { value: unknown }): Record<string, true> | null {
  const value = control.value;
  return typeof value === 'number' && Number.isFinite(value) && value > 0
    ? null
    : { invalidSelection: true };
}

function mergeReferenceOptions(
  current: RequestReferenceOption[],
  incoming: RequestReferenceOption[],
): RequestReferenceOption[] {
  const merged = new Map<number, RequestReferenceOption>();
  for (const option of [...current, ...incoming]) {
    if (!Number.isFinite(option.value) || option.value <= 0 || !option.label.trim()) {
      continue;
    }
    merged.set(option.value, {
      value: option.value,
      label: option.label.trim(),
    });
  }
  return [...merged.values()].sort((left, right) => left.label.localeCompare(right.label));
}

function clearServerError(control: FormGroup['controls'][string] | null | undefined): void {
  if (!control?.errors?.['server']) {
    return;
  }

  const nextErrors = { ...(control.errors ?? {}) };
  delete nextErrors['server'];
  control.setErrors(Object.keys(nextErrors).length ? nextErrors : null);
}

function extractMessage(value: unknown): string | null {
  if (typeof value === 'string') {
    return value.trim() || null;
  }
  if (Array.isArray(value)) {
    const first = value.map(extractMessage).find(Boolean);
    return first ?? null;
  }
  if (isRecord(value)) {
    if (typeof value['message'] === 'string' && value['message'].trim()) {
      return value['message'].trim();
    }
    if (isRecord(value['errors'])) {
      const nested = Object.values(value['errors']).map(extractMessage).find(Boolean);
      return nested ?? null;
    }
  }
  return null;
}

function formatDisplayDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return DATE_FORMATTER.format(parsed);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
