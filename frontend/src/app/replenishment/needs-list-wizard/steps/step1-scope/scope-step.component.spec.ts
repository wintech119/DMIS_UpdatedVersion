import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of, throwError } from 'rxjs';

import { ScopeStepComponent } from './scope-step.component';
import { WizardStateService } from '../../services/wizard-state.service';
import { ReplenishmentService } from '../../../services/replenishment.service';

describe('ScopeStepComponent', () => {
  let component: ScopeStepComponent;
  let fixture: ComponentFixture<ScopeStepComponent>;
  let mockWizardService: jasmine.SpyObj<WizardStateService>;
  let mockReplenishmentService: jasmine.SpyObj<ReplenishmentService>;

  beforeEach(async () => {
    mockWizardService = jasmine.createSpyObj('WizardStateService', [
      'getState',
      'getState$',
      'updateState'
    ]);
    mockWizardService.getState$.and.returnValue(of({
      adjustments: {},
      event_id: undefined,
      warehouse_ids: undefined,
      phase: undefined
    }));

    mockReplenishmentService = jasmine.createSpyObj('ReplenishmentService', [
      'getStockStatusMulti'
    ]);

    await TestBed.configureTestingModule({
      imports: [ScopeStepComponent, ReactiveFormsModule, NoopAnimationsModule],
      providers: [
        { provide: WizardStateService, useValue: mockWizardService },
        { provide: ReplenishmentService, useValue: mockReplenishmentService }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(ScopeStepComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should initialize form with default values', () => {
    expect(component.form.value).toEqual({
      event_id: null,
      warehouse_ids: [],
      phase: 'BASELINE',
      as_of_datetime: ''
    });
  });

  it('should validate required fields', () => {
    expect(component.form.valid).toBe(false);

    component.form.patchValue({
      event_id: 1,
      warehouse_ids: [1],
      phase: 'BASELINE'
    });

    expect(component.form.valid).toBe(true);
  });

  it('should call API and emit next on successful gap calculation', () => {
    const mockResponse = {
      event_id: 1,
      phase: 'BASELINE' as const,
      warehouse_ids: [1],
      warehouses: [{ warehouse_id: 1, warehouse_name: 'Test Warehouse' }],
      items: [],
      as_of_datetime: new Date().toISOString()
    };

    mockReplenishmentService.getStockStatusMulti.and.returnValue(of(mockResponse));

    spyOn(component.next, 'emit');

    component.form.patchValue({
      event_id: 1,
      warehouse_ids: [1],
      phase: 'BASELINE'
    });

    component.calculateGaps();

    expect(mockReplenishmentService.getStockStatusMulti).toHaveBeenCalledWith(
      1,
      [1],
      'BASELINE',
      undefined
    );
    expect(mockWizardService.updateState).toHaveBeenCalledWith({
      previewResponse: mockResponse
    });
    expect(component.next.emit).toHaveBeenCalled();
  });

  it('should show errors on API failure', () => {
    mockReplenishmentService.getStockStatusMulti.and.returnValue(
      throwError(() => ({ message: 'API Error' }))
    );

    component.form.patchValue({
      event_id: 1,
      warehouse_ids: [1],
      phase: 'BASELINE'
    });

    component.calculateGaps();

    expect(component.errors).toContain('API Error');
    expect(component.loading).toBe(false);
  });

  it('should show validation errors for invalid form', () => {
    component.calculateGaps();

    expect(component.errors).toEqual([
      'Please provide valid event ID, warehouse(s), and phase.'
    ]);
  });

  it('should auto-save form changes to wizard state', () => {
    component.form.patchValue({
      event_id: 1,
      warehouse_ids: [1, 2],
      phase: 'SURGE'
    });

    expect(mockWizardService.updateState).toHaveBeenCalledWith({
      event_id: 1,
      warehouse_ids: [1, 2],
      phase: 'SURGE',
      as_of_datetime: ''
    });
  });
});
