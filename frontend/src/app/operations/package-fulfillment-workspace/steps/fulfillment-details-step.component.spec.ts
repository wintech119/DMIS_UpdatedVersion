import { signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of, throwError } from 'rxjs';

import { FulfillmentDetailsStepComponent } from './fulfillment-details-step.component';
import { MasterDataService } from '../../../master-data/services/master-data.service';
import { AuthRbacService } from '../../../replenishment/services/auth-rbac.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';

describe('FulfillmentDetailsStepComponent', () => {
  const draftState = signal({
    fulfillment_mode: 'DIRECT',
    to_inventory_id: '',
    transport_mode: '',
    comments_text: '',
    override_reason_code: '',
    override_note: '',
    staging_warehouse_id: '',
    staging_override_reason: '',
  });
  const loading = signal(false);
  const isStagedFulfillment = signal(false);
  const stagingRecommendation = signal(null);
  const stagingWarehouseId = signal<number | null>(null);
  const stagingSelectionBasis = signal<string | null>(null);
  const recommendationLoading = signal(false);
  const recommendationError = signal<string | null>(null);
  const planRequiresOverride = signal(false);
  const planNeedsApproval = signal(false);
  const hasPendingOverride = signal(false);
  const reliefrqstId = signal<number | null>(null);

  const storeStub = {
    draft: draftState,
    loading,
    isStagedFulfillment,
    stagingRecommendation,
    stagingWarehouseId,
    stagingSelectionBasis,
    recommendationLoading,
    recommendationError,
    planRequiresOverride,
    planNeedsApproval,
    hasPendingOverride,
    reliefrqstId,
    patchDraft: jasmine.createSpy('patchDraft').and.callFake((patch: Record<string, unknown>) => {
      draftState.update((current) => ({ ...current, ...patch }));
    }),
    saveFulfillmentModeDraft: jasmine.createSpy('saveFulfillmentModeDraft').and.returnValue(of({})),
    extractWriteError: jasmine.createSpy('extractWriteError').and.callFake(
      (error: HttpErrorResponse, fallback: string) =>
        error.error?.errors?.staging_warehouse_id ?? fallback,
    ),
    loadStagingRecommendation: jasmine.createSpy('loadStagingRecommendation'),
  };

  const masterData = jasmine.createSpyObj<MasterDataService>('MasterDataService', ['lookup']);
  const auth = jasmine.createSpyObj<AuthRbacService>('AuthRbacService', ['hasPermission']);
  const notifications = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
    'showError',
    'showSuccess',
  ]);

  beforeEach(async () => {
    draftState.set({
      fulfillment_mode: 'DIRECT',
      to_inventory_id: '',
      transport_mode: '',
      comments_text: '',
      override_reason_code: '',
      override_note: '',
      staging_warehouse_id: '',
      staging_override_reason: '',
    });
    loading.set(false);
    isStagedFulfillment.set(false);
    stagingRecommendation.set(null);
    stagingWarehouseId.set(null);
    stagingSelectionBasis.set(null);
    recommendationLoading.set(false);
    recommendationError.set(null);
    planRequiresOverride.set(false);
    planNeedsApproval.set(false);
    hasPendingOverride.set(false);
    reliefrqstId.set(null);
    storeStub.patchDraft.calls.reset();
    storeStub.saveFulfillmentModeDraft.calls.reset();
    storeStub.extractWriteError.calls.reset();
    storeStub.loadStagingRecommendation.calls.reset();
    masterData.lookup.and.returnValue(of([
      { value: '9002', label: 'Destination warehouse' },
      { value: '9501', label: 'ODPEM Staging Hub' },
    ]));
    auth.hasPermission.and.returnValue(true);
    notifications.showError.calls.reset();
    notifications.showSuccess.calls.reset();

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, FulfillmentDetailsStepComponent],
      providers: [
        { provide: MasterDataService, useValue: masterData },
        { provide: AuthRbacService, useValue: auth },
        { provide: DmisNotificationService, useValue: notifications },
        { provide: OperationsWorkspaceStateService, useValue: storeStub },
      ],
    }).compileComponents();
  });

  it('hides the override note field for order-only bypasses', () => {
    planRequiresOverride.set(true);

    const fixture = TestBed.createComponent(FulfillmentDetailsStepComponent);
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.textContent).toContain('Order Override');
    expect(host.textContent).toContain('Override Reason');
    expect(host.textContent).not.toContain('Approval Request Note');
    expect(host.textContent).not.toContain('Override Note');
    expect(host.querySelector('textarea[placeholder=\"Operational reason for the bypass\"]')).toBeNull();
  });

  it('shows the override note field when the selected plan still needs override approval evidence', () => {
    planRequiresOverride.set(true);
    planNeedsApproval.set(true);

    const fixture = TestBed.createComponent(FulfillmentDetailsStepComponent);
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.textContent).toContain('Override Approval');
    expect(host.textContent).toContain('Override Reason');
    expect(host.textContent).toContain('Override Note');
    expect(host.querySelector('textarea[placeholder=\"Operational reason for the bypass\"]')).not.toBeNull();
  });

  it('shows the override note field once approval is pending', () => {
    planRequiresOverride.set(true);
    planNeedsApproval.set(true);
    hasPendingOverride.set(true);

    const fixture = TestBed.createComponent(FulfillmentDetailsStepComponent);
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.textContent).toContain('Override Approval');
    expect(host.textContent).toContain('Override Reason');
    expect(host.textContent).toContain('Override Note');
    expect(host.querySelector('textarea[placeholder=\"Operational reason for the bypass\"]')).not.toBeNull();
  });

  it('keeps helper descriptions visible for the editable operational fields', () => {
    isStagedFulfillment.set(true);
    draftState.update((current) => ({
      ...current,
      fulfillment_mode: 'DELIVER_FROM_STAGING',
    }));

    const fixture = TestBed.createComponent(FulfillmentDetailsStepComponent);
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.textContent).toContain('Choose how this package moves from the source warehouse to the requester.');
    expect(host.textContent).toContain('Final receiving warehouse for the request. Keep this separate from the staging hub.');
    expect(host.textContent).toContain('Select the ODPEM staging warehouse that will receive this staged package.');
    expect(host.textContent).toContain('How the package is expected to move or be released after stock is reserved.');
    expect(host.textContent).toContain('Notes for warehouse, dispatch, or receiving staff. Keep this short and operational.');
  });

  it('does not overwrite destination warehouse when switching to a staged mode', () => {
    reliefrqstId.set(95009);
    draftState.update((current) => ({
      ...current,
      fulfillment_mode: 'DIRECT',
      to_inventory_id: '9002',
      staging_warehouse_id: '9501',
    }));

    const fixture = TestBed.createComponent(FulfillmentDetailsStepComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    component.onFulfillmentModeChange('PICKUP_AT_STAGING');

    expect(storeStub.saveFulfillmentModeDraft).toHaveBeenCalledWith('PICKUP_AT_STAGING', 9501, null);
    expect(draftState().to_inventory_id).toBe('9002');
  });

  it('saves the chosen staging hub without changing the destination warehouse', () => {
    reliefrqstId.set(95009);
    isStagedFulfillment.set(true);
    draftState.update((current) => ({
      ...current,
      fulfillment_mode: 'DELIVER_FROM_STAGING',
      to_inventory_id: '9002',
      staging_warehouse_id: '',
    }));

    const fixture = TestBed.createComponent(FulfillmentDetailsStepComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    component.onStagingHubChange('9501');

    expect(storeStub.saveFulfillmentModeDraft).toHaveBeenCalledWith('DELIVER_FROM_STAGING', 9501, null);
    expect(draftState().to_inventory_id).toBe('9002');
  });

  it('surfaces backend errors when saving the staging hub fails', () => {
    reliefrqstId.set(95009);
    isStagedFulfillment.set(true);
    draftState.update((current) => ({
      ...current,
      fulfillment_mode: 'DELIVER_FROM_STAGING',
      staging_warehouse_id: '',
    }));
    storeStub.saveFulfillmentModeDraft.and.returnValue(
      throwError(() => new HttpErrorResponse({
        status: 400,
        error: { errors: { staging_warehouse_id: 'Choose a valid staging hub.' } },
      })),
    );
    storeStub.extractWriteError.and.returnValue('Choose a valid staging hub.');

    const fixture = TestBed.createComponent(FulfillmentDetailsStepComponent);
    const component = fixture.componentInstance;
    fixture.detectChanges();

    component.onStagingHubChange('9501');

    expect(notifications.showError).toHaveBeenCalledWith('Choose a valid staging hub.');
  });
});
