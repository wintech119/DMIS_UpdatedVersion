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
  RequestOriginMode,
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
import { DmisStepTrackerComponent, StepDefinition } from '../../shared/dmis-step-tracker/dmis-step-tracker.component';
import { RequestItemsStepComponent } from './steps/request-items-step.component';
import { RequestReviewStepComponent, ReviewFormValue } from './steps/request-review-step.component';
import { extractOperationsErrorMessage } from '../operations-display.util';

const DATE_FORMATTER = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
});
const REQUEST_NOTES_MAX_LENGTH = 500;
const REQUEST_REASON_MAX_LENGTH = 255;

type RequestItemFormDefaults = Partial<CreateRequestItemPayload> & {
  item_name?: string | null;
};

interface ReliefRequestBridgeState {
  source_needs_list_id: number;
  beneficiary_tenant_id: number | null;
  beneficiary_agency_id: number | null;
  suggested_event_id: number | null;
  allowed_origin_modes: RequestOriginMode[];
}

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
    DmisStepTrackerComponent,
    RequestItemsStepComponent,
    RequestReviewStepComponent,
  ],
  templateUrl: './relief-request-wizard.component.html',
  styleUrls: ['./relief-request-wizard.component.scss', '../operations-shell.scss'],
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
  readonly bridgeState = signal<ReliefRequestBridgeState | null>(null);
  readonly sourceNeedsListId = signal<number | null>(null);
  readonly agencyOptions = signal<RequestReferenceOption[]>([]);
  readonly eventOptions = signal<RequestReferenceOption[]>([]);
  readonly itemOptions = signal<RequestReferenceOption[]>([]);
  readonly formVersion = signal(0);

  private reliefrqstId: number | null = null;

  readonly requestForm: FormGroup = this.fb.nonNullable.group({
    agency_id: [null as number | null, [Validators.required]],
    urgency_ind: [null as UrgencyCode | null, [Validators.required]],
    eligible_event_id: [null as number | null],
    rqst_notes_text: ['', [Validators.maxLength(REQUEST_NOTES_MAX_LENGTH)]],
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

  readonly availableOriginModes = computed<RequestOriginMode[]>(() => {
    const capabilityModes = normalizeCapabilityOriginModes(this.capabilities());
    const bridgeModes = this.bridgeState()?.allowed_origin_modes ?? null;
    if (bridgeModes) {
      return capabilityModes.filter((mode) => bridgeModes.includes(mode));
    }
    return capabilityModes;
  });

  readonly isDualMode = computed(() => {
    const modes = this.availableOriginModes();
    return modes.length > 1;
  });

  readonly explicitOriginMode = computed<RequestOriginMode | null>(() => {
    const modes = this.availableOriginModes();
    return modes.length === 1 ? modes[0] : null;
  });

  readonly isOnBehalfMode = computed(() => this.explicitOriginMode() === 'ODPEM_BRIDGE');

  readonly requestingEntityLabel = computed(() =>
    this.isOnBehalfMode() ? 'Represented requester' : 'Requesting entity'
  );

  readonly creationBlocked = computed(() =>
    !this.isEditMode()
    && this.auth.loaded()
    && (
      !(this.capabilities()?.can_create_relief_request ?? false)
      || this.availableOriginModes().length === 0
    )
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
    return this.isEditMode() ? 'Will appear after saving' : 'Set automatically when saved';
  });

  readonly requestDateHint = computed(() =>
    this.requestDateIso()
      ? 'Date this request was first saved.'
      : 'This date is recorded automatically the first time you save the request.'
  );

  readonly submissionModeLabel = computed(() => {
    if (this.isDualMode()) {
      return 'Your organisation or managed entity';
    }
    switch (this.explicitOriginMode()) {
      case 'FOR_SUBORDINATE':
        return 'Request on behalf of a managed entity';
      case 'ODPEM_BRIDGE':
        return 'ODPEM-assisted request';
      case 'SELF':
        return 'Your organisation\'s request';
      default:
        return this.isEditMode() ? 'Editing draft request' : 'Request creation is not available';
    }
  });

  readonly submissionModeHint = computed(() => {
    if (this.isDualMode()) {
      return 'Choose the agency that needs supplies. You can select your own organisation or any entity you manage.';
    }
    switch (this.explicitOriginMode()) {
      case 'FOR_SUBORDINATE':
        return 'Choose which agency under your authority needs supplies. You are submitting on their behalf.';
      case 'ODPEM_BRIDGE':
        return 'Choose the agency that needs support. As ODPEM, you are entering this request on their behalf.';
      case 'SELF':
        return 'Choose the agency that needs relief supplies. This request will be submitted under your organisation\'s authority.';
      default:
        return 'Your account does not have permission to create relief requests. Contact your administrator if you believe this is incorrect.';
    }
  });

  readonly workflowLabel = computed(() => {
    if (this.isEditMode()) {
      return 'Editing draft';
    }
    if (this.isDualMode()) {
      return 'New request';
    }
    switch (this.explicitOriginMode()) {
      case 'FOR_SUBORDINATE':
        return 'New request (on behalf)';
      case 'ODPEM_BRIDGE':
        return 'New request (ODPEM-assisted)';
      case 'SELF':
        return 'New request';
      default:
        return 'New request';
    }
  });

  readonly reviewFormValue = computed<ReviewFormValue>(() => {
    this.formVersion();
    const raw = this.requestForm.getRawValue();

    return {
      agency_id: raw.agency_id,
      agency_name: this.selectedAgencyName(),
      requester_label: this.requestingEntityLabel(),
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
    const notesValid = form.get('rqst_notes_text')?.valid ?? true;
    const hasItems = this.itemsArray.length > 0;
    const itemsValid = this.itemsArray.valid;
    return agencyValid && urgencyValid && notesValid && hasItems && itemsValid;
  });

  readonly trackerSteps = computed<StepDefinition[]>(() => [
    { label: 'Request Setup', completed: this.isStep1Valid() },
    { label: 'Review & Route' },
  ]);

  readonly addItemFn = (): void => this.addItem();
  readonly removeItemFn = (index: number): void => this.removeItem(index);

  ngOnInit(): void {
    this.captureBridgeState();
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

    const urgencyCtrl = this.requestForm.get('urgency_ind')!;
    this.applyRequestNotesValidators(urgencyCtrl.value);

    urgencyCtrl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((urgency) => {
        this.applyRequestNotesValidators(urgency);
      });
  }

  private captureBridgeState(): void {
    const state = this.navigationState();
    const sourceNeedsListId = toPositiveNumber(state['source_needs_list_id']);
    if (!sourceNeedsListId) {
      return;
    }

    const bridgeState: ReliefRequestBridgeState = {
      source_needs_list_id: sourceNeedsListId,
      beneficiary_tenant_id: toNullableNumber(state['beneficiary_tenant_id']),
      beneficiary_agency_id: toNullableNumber(state['beneficiary_agency_id']),
      suggested_event_id: toNullableNumber(state['suggested_event_id']),
      allowed_origin_modes: normalizeRouteOriginModes(state['allowed_origin_modes']),
    };
    this.bridgeState.set(bridgeState);
    this.sourceNeedsListId.set(sourceNeedsListId);
    this.applyBridgeStateDefaults();
  }

  private navigationState(): Record<string, unknown> {
    const routerWithOptionalNavigation = this.router as Router & {
      getCurrentNavigation?: () => { extras?: { state?: unknown } } | null;
    };
    const navigationState = routerWithOptionalNavigation.getCurrentNavigation?.()?.extras?.state;
    if (isRecord(navigationState)) {
      return navigationState;
    }
    return isRecord(history.state) ? history.state : {};
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
          this.applyBridgeStateDefaults();
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
    if (this.bridgeState()?.beneficiary_agency_id) {
      return;
    }

    const agencyControl = this.requestForm.get('agency_id');
    if (agencyControl && agencyControl.value == null && this.agencyOptions().length === 1) {
      agencyControl.setValue(this.agencyOptions()[0].value);
    }
  }

  private applyBridgeStateDefaults(): void {
    if (this.isEditMode()) {
      return;
    }
    const bridge = this.bridgeState();
    if (!bridge) {
      return;
    }

    if (bridge.beneficiary_agency_id) {
      this.agencyOptions.update((current) => mergeReferenceOptions(current, [{
        value: bridge.beneficiary_agency_id!,
        label: `Agency ${bridge.beneficiary_agency_id}`,
      }]));
      const agencyControl = this.requestForm.get('agency_id');
      if (agencyControl && agencyControl.value == null) {
        agencyControl.setValue(bridge.beneficiary_agency_id);
      }
    }

    if (bridge.suggested_event_id) {
      this.eventOptions.update((current) => mergeReferenceOptions(current, [{
        value: bridge.suggested_event_id!,
        label: `Event ${bridge.suggested_event_id}`,
      }]));
      const eventControl = this.requestForm.get('eligible_event_id');
      if (eventControl && eventControl.value == null) {
        eventControl.setValue(bridge.suggested_event_id);
      }
    }

    this.formVersion.update((version) => version + 1);
  }

  private loadExisting(): void {
    this.loading.set(true);
    this.error.set(null);

    this.operationsService.getRequest(this.reliefrqstId!)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          if (data.status_code !== 'DRAFT') {
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
    this.sourceNeedsListId.set(data.source_needs_list_id ?? null);

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
      rqst_reason_desc: [defaults?.rqst_reason_desc ?? '', [Validators.maxLength(REQUEST_REASON_MAX_LENGTH)]],
      required_by_date: [defaults?.required_by_date ?? null as string | null],
    });

    const urgencyCtrl = group.get('urgency_ind')!;
    this.applyItemReasonValidators(group, urgencyCtrl.value);

    urgencyCtrl.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((urgency) => {
        this.applyItemReasonValidators(group, urgency);
      });

    return group;
  }

  private applyRequestNotesValidators(urgency: UrgencyCode | null): void {
    const notesCtrl = this.requestForm.get('rqst_notes_text')!;
    notesCtrl.setValidators(
      urgency === 'H'
        ? [trimmedRequiredValidator, Validators.maxLength(REQUEST_NOTES_MAX_LENGTH)]
        : [Validators.maxLength(REQUEST_NOTES_MAX_LENGTH)],
    );
    notesCtrl.updateValueAndValidity({ emitEvent: false });
  }

  private applyItemReasonValidators(group: FormGroup, urgency: UrgencyCode | null): void {
    const reasonCtrl = group.get('rqst_reason_desc')!;
    reasonCtrl.setValidators(
      urgency === 'C' || urgency === 'H'
        ? [trimmedRequiredValidator, Validators.maxLength(REQUEST_REASON_MAX_LENGTH)]
        : [Validators.maxLength(REQUEST_REASON_MAX_LENGTH)],
    );
    reasonCtrl.updateValueAndValidity({ emitEvent: false });
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

  onTrackerStepClick(index: number): void {
    if (this.stepper) {
      this.stepper.selectedIndex = index;
    }
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
      const reason = String(item['rqst_reason_desc'] ?? '').trim();
      if (reason) {
        payload.rqst_reason_desc = reason;
      }
      if (item['required_by_date']) {
        const dateValue = item['required_by_date'];
        payload.required_by_date = dateValue instanceof Date
          ? dateValue.toISOString().split('T')[0]
          : String(dateValue);
      }
      return payload;
    });

    const notes = String(raw.rqst_notes_text ?? '').trim();
    const notesPayload = notes || undefined;
    const sourceNeedsListId = this.sourceNeedsListId();

    if (this.isEditMode() && this.reliefrqstId) {
      const updatePayload: UpdateRequestPayload = {
        agency_id: raw.agency_id,
        urgency_ind: raw.urgency_ind as UrgencyCode,
        eligible_event_id: raw.eligible_event_id,
        rqst_notes_text: notesPayload,
        items,
      };
      if (sourceNeedsListId != null) {
        updatePayload.source_needs_list_id = sourceNeedsListId;
      }

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
      rqst_notes_text: notesPayload,
      items,
    };
    if (sourceNeedsListId != null) {
      createPayload.source_needs_list_id = sourceNeedsListId;
    }
    const originMode = this.explicitOriginMode();
    if (originMode) {
      createPayload.origin_mode = originMode;
    }
    if (originMode === 'ODPEM_BRIDGE' || originMode === 'FOR_SUBORDINATE') {
      createPayload.beneficiary_agency_id = raw.agency_id;
    }

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
            const fallback = typeof detail === 'string' ? detail : 'Request saved as draft, but submission failed.';
            this.notify.showWarning(extractOperationsErrorMessage(err.error) ?? fallback);
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
    let shouldRefreshStepState = false;

    const agencyMessage = extractOperationsErrorMessage(errors?.['agency_id']);
    if (agencyMessage) {
      this.requestForm.get('agency_id')?.setErrors({ server: agencyMessage });
      this.requestForm.get('agency_id')?.markAsTouched();
      shouldRefreshStepState = true;
    }

    const eventMessage = extractOperationsErrorMessage(errors?.['eligible_event_id']);
    if (eventMessage) {
      this.requestForm.get('eligible_event_id')?.setErrors({ server: eventMessage });
      this.requestForm.get('eligible_event_id')?.markAsTouched();
      shouldRefreshStepState = true;
    }

    if (shouldRefreshStepState) {
      this.requestForm.updateValueAndValidity({ emitEvent: true });
    }

    const message = extractOperationsErrorMessage(err.error) ?? 'Failed to save request. Please try again.';
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

export function trimmedRequiredValidator(control: { value: unknown }): Record<string, true> | null {
  // Parity with backend `.strip()` at backend/operations/contract_services.py:795, 825.
  // Whitespace-only text gets dropped to undefined in the payload, so the form must
  // reject it up front rather than letting a submit fail on the server.
  const raw = control.value;
  if (raw == null) {
    return { required: true };
  }
  return String(raw).trim().length > 0 ? null : { required: true };
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

function formatDisplayDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return DATE_FORMATTER.format(parsed);
}

function normalizeCapabilityOriginModes(capabilities: OperationsCapabilities | null): RequestOriginMode[] {
  const explicitModes = (capabilities?.allowed_origin_modes ?? [])
    .map((mode) => toCanonicalOriginMode(mode))
    .filter((mode): mode is RequestOriginMode => mode !== null);
  if (explicitModes.length > 0) {
    return [...new Set(explicitModes)];
  }

  const fallback = toCanonicalOriginMode(capabilities?.relief_request_submission_mode ?? null);
  return fallback ? [fallback] : [];
}

function normalizeRouteOriginModes(value: unknown): RequestOriginMode[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return [...new Set(
    value
      .map((entry) => toCanonicalOriginMode(entry))
      .filter((mode): mode is RequestOriginMode => mode !== null),
  )];
}

function toCanonicalOriginMode(value: unknown): RequestOriginMode | null {
  const normalized = String(value ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'SELF':
      return 'SELF';
    case 'FOR_SUBORDINATE':
    case 'SUBORDINATE':
      return 'FOR_SUBORDINATE';
    case 'ODPEM_BRIDGE':
      return 'ODPEM_BRIDGE';
    default:
      break;
  }

  const lower = String(value ?? '').trim().toLowerCase();
  switch (lower) {
    case 'self':
      return 'SELF';
    case 'for_subordinate':
      return 'FOR_SUBORDINATE';
    case 'on_behalf_bridge':
      return 'ODPEM_BRIDGE';
    default:
      return null;
  }
}

function toPositiveNumber(value: unknown): number | null {
  const parsed = toNullableNumber(value);
  return parsed && parsed > 0 ? parsed : null;
}

function toNullableNumber(value: unknown): number | null {
  if (value == null || value === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
