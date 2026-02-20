import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ActivatedRoute } from '@angular/router';
import { Observable } from 'rxjs';
import { of } from 'rxjs';
import { throwError } from 'rxjs';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { NeedsListWizardComponent } from './needs-list-wizard.component';
import { WizardStateService } from './services/wizard-state.service';
import { ReplenishmentService } from '../services/replenishment.service';
import { NeedsListResponse } from '../models/needs-list.model';
import { DmisNotificationService } from '../services/notification.service';

describe('NeedsListWizardComponent', () => {
  let component: NeedsListWizardComponent;
  let fixture: ComponentFixture<NeedsListWizardComponent>;
  let mockRouter: jasmine.SpyObj<Router>;
  let mockActivatedRoute: Pick<ActivatedRoute, 'queryParams'>;
  let replenishmentService: jasmine.SpyObj<ReplenishmentService>;
  let notificationService: jasmine.SpyObj<DmisNotificationService>;
  let wizardService: WizardStateService;

  beforeEach(async () => {
    mockRouter = jasmine.createSpyObj('Router', ['navigate']);
    mockActivatedRoute = {
      queryParams: of({
        event_id: '1',
        warehouse_id: '2',
        phase: 'BASELINE'
      }) as Observable<Record<string, string>>
    };
    replenishmentService = jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', [
      'getNeedsList',
      'getActiveEvent',
      'getAllWarehouses'
    ]);
    notificationService = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showError',
      'showWarning'
    ]);
    const draftNeedsList: NeedsListResponse = {
      event_id: 1,
      phase: 'BASELINE',
      items: [],
      as_of_datetime: new Date().toISOString()
    };
    replenishmentService.getNeedsList.and.returnValue(of(draftNeedsList));
    replenishmentService.getActiveEvent.and.returnValue(
      of({
        event_id: 1,
        event_name: 'Event 1',
        status: 'ACTIVE',
        phase: 'BASELINE',
        declaration_date: new Date().toISOString()
      })
    );
    replenishmentService.getAllWarehouses.and.returnValue(
      of([{ warehouse_id: 2, warehouse_name: 'Warehouse 2' }])
    );

    await TestBed.configureTestingModule({
      imports: [NeedsListWizardComponent, NoopAnimationsModule],
      providers: [
        { provide: Router, useValue: mockRouter },
        { provide: ActivatedRoute, useValue: mockActivatedRoute },
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DmisNotificationService, useValue: notificationService },
        WizardStateService
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(NeedsListWizardComponent);
    component = fixture.componentInstance;
    wizardService = TestBed.inject(WizardStateService);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should load query params on init', () => {
    const state = wizardService.getState();
    expect(state.event_id).toBe(1);
    expect(state.warehouse_ids).toEqual([2]);
    expect(state.phase).toBe('BASELINE');
  });

  it('should navigate back to dashboard', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    component.backToDashboard();

    expect(wizardService.getState().event_id).toBeUndefined();
    expect(mockRouter.navigate).toHaveBeenCalledWith(
      ['/replenishment/dashboard'],
      { queryParams: { context: 'wizard', event_id: 1, phase: 'BASELINE' } }
    );
  });

  it('should not navigate if user cancels confirmation', () => {
    wizardService.updateState({ event_id: 1 });
    spyOn(window, 'confirm').and.returnValue(false);

    component.backToDashboard();

    expect(mockRouter.navigate).not.toHaveBeenCalled();
  });

  it('should set confirmation state on completion', () => {
    component.onComplete({
      action: 'submitted_for_approval',
      totalItems: 3,
      completedAt: new Date().toISOString(),
      approver: 'Senior Director'
    });

    expect(component.confirmationState).not.toBeNull();
    expect(component.confirmationState?.action).toBe('submitted_for_approval');
    expect(component.confirmationState?.totalItems).toBe(3);
  });

  it('should reset and navigate from confirmation page', () => {
    wizardService.updateState({ event_id: 1 });
    component.confirmationState = {
      action: 'draft_saved',
      totalItems: 2,
      completedAt: new Date().toISOString()
    };

    component.returnToDashboardFromConfirmation();

    expect(wizardService.getState().event_id).toBeUndefined();
    expect(component.confirmationState).toBeNull();
    expect(mockRouter.navigate).toHaveBeenCalledWith(
      ['/replenishment/dashboard'],
      { queryParams: { context: 'wizard', event_id: 1, phase: 'BASELINE' } }
    );
  });

  it('should return to submit step from draft confirmation', () => {
    component.confirmationState = {
      action: 'draft_saved',
      totalItems: 2,
      completedAt: new Date().toISOString()
    };
    const mockStepper = { selectedIndex: 3 };
    (component as unknown as { stepper: { selectedIndex: number } }).stepper = mockStepper;

    component.returnToSubmitStepFromConfirmation();

    expect(component.confirmationState).toBeNull();
    expect(mockStepper.selectedIndex).toBe(2);
  });

  it('should show error feedback and reset hydration on loadExistingNeedsList failure', () => {
    replenishmentService.getNeedsList.and.returnValue(
      throwError(() => ({ error: { errors: { needs_list_id: 'Not found.' } } }))
    );
    (component as unknown as { hydratedNeedsListId: string | null }).hydratedNeedsListId = 'abc-123';

    (component as unknown as { loadExistingNeedsList: (needsListId: string) => void })
      .loadExistingNeedsList('abc-123');

    expect((component as unknown as { hydratedNeedsListId: string | null }).hydratedNeedsListId).toBeNull();
    expect(notificationService.showError).toHaveBeenCalledWith('Failed to load needs list. Not found.');
  });
});
