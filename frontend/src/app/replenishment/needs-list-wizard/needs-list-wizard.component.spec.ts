import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import { NeedsListWizardComponent } from './needs-list-wizard.component';
import { WizardStateService } from './services/wizard-state.service';

describe('NeedsListWizardComponent', () => {
  let component: NeedsListWizardComponent;
  let fixture: ComponentFixture<NeedsListWizardComponent>;
  let mockRouter: jasmine.SpyObj<Router>;
  let mockActivatedRoute: any;
  let wizardService: WizardStateService;

  beforeEach(async () => {
    mockRouter = jasmine.createSpyObj('Router', ['navigate']);
    mockActivatedRoute = {
      queryParams: of({
        event_id: '1',
        warehouse_id: '2',
        phase: 'BASELINE'
      })
    };

    await TestBed.configureTestingModule({
      imports: [NeedsListWizardComponent, NoopAnimationsModule],
      providers: [
        { provide: Router, useValue: mockRouter },
        { provide: ActivatedRoute, useValue: mockActivatedRoute },
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
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/replenishment/dashboard']);
  });

  it('should not navigate if user cancels confirmation', () => {
    wizardService.updateState({ event_id: 1 });
    spyOn(window, 'confirm').and.returnValue(false);

    component.backToDashboard();

    expect(mockRouter.navigate).not.toHaveBeenCalled();
  });

  it('should handle wizard completion', () => {
    spyOn(window, 'confirm').and.returnValue(true);
    wizardService.updateState({ event_id: 1 });

    component.onComplete();

    expect(wizardService.getState().event_id).toBeUndefined();
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/replenishment/dashboard']);
  });
});
