import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of } from 'rxjs';

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
    storeStub.loadStagingRecommendation.calls.reset();
    masterData.lookup.and.returnValue(of([{ value: '9002', label: 'Destination warehouse' }]));
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
});
