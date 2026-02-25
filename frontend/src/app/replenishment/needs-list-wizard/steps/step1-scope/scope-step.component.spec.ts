import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MatDialog } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';

import { ScopeStepComponent } from './scope-step.component';
import { WizardStateService } from '../../services/wizard-state.service';
import { ReplenishmentService } from '../../../services/replenishment.service';
import { DmisNotificationService } from '../../../services/notification.service';

describe('ScopeStepComponent', () => {
  let component: ScopeStepComponent;
  let fixture: ComponentFixture<ScopeStepComponent>;
  let mockWizardService: jasmine.SpyObj<WizardStateService>;
  let mockReplenishmentService: jasmine.SpyObj<ReplenishmentService>;
  let mockNotificationService: jasmine.SpyObj<DmisNotificationService>;

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
    mockWizardService.getState.and.returnValue({
      adjustments: {}
    });

    mockReplenishmentService = jasmine.createSpyObj('ReplenishmentService', [
      'getActiveEvent',
      'getAllWarehouses',
      'checkActiveNeedsLists',
      'getStockStatusMulti'
    ]);
    mockReplenishmentService.getActiveEvent.and.returnValue(of(null));
    mockReplenishmentService.getAllWarehouses.and.returnValue(of([]));
    mockReplenishmentService.checkActiveNeedsLists.and.returnValue(of([]));

    mockNotificationService = jasmine.createSpyObj('DmisNotificationService', [
      'showNetworkError'
    ]);

    await TestBed.configureTestingModule({
      imports: [ScopeStepComponent, ReactiveFormsModule, NoopAnimationsModule],
      providers: [
        { provide: WizardStateService, useValue: mockWizardService },
        { provide: ReplenishmentService, useValue: mockReplenishmentService },
        { provide: DmisNotificationService, useValue: mockNotificationService }
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

  it('should pass current needs list id to duplicate checks when recalculating', () => {
    const mockResponse = {
      event_id: 1,
      phase: 'BASELINE' as const,
      warehouse_ids: [1],
      warehouses: [{ warehouse_id: 1, warehouse_name: 'Test Warehouse' }],
      items: [],
      as_of_datetime: new Date().toISOString()
    };
    mockWizardService.getState.and.returnValue({
      adjustments: {},
      draft_ids: ['NL-EXISTING-1']
    });
    mockReplenishmentService.getStockStatusMulti.and.returnValue(of(mockResponse));

    component.form.patchValue({
      event_id: 1,
      warehouse_ids: [1, 2],
      phase: 'BASELINE'
    });

    component.calculateGaps();

    expect(mockReplenishmentService.checkActiveNeedsLists).toHaveBeenCalledWith(
      1,
      1,
      'BASELINE',
      'NL-EXISTING-1'
    );
    expect(mockReplenishmentService.checkActiveNeedsLists).toHaveBeenCalledWith(
      1,
      2,
      'BASELINE',
      'NL-EXISTING-1'
    );
  });

  it('should deduplicate duplicate conflicts before opening warning dialog', () => {
    const mockResponse = {
      event_id: 1,
      phase: 'BASELINE' as const,
      warehouse_ids: [1],
      warehouses: [{ warehouse_id: 1, warehouse_name: 'Test Warehouse' }],
      items: [],
      as_of_datetime: new Date().toISOString()
    };
    mockReplenishmentService.checkActiveNeedsLists.and.callFake((_eventId, warehouseId: number) =>
      of([
        {
          needs_list_id: 'NL-DUP-1',
          needs_list_no: 'NL-2026-001',
          status: 'SUBMITTED',
          created_by: 'submitter',
          created_at: new Date().toISOString(),
          warehouse_name: `Warehouse ${warehouseId}`
        }
      ])
    );
    mockReplenishmentService.getStockStatusMulti.and.returnValue(of(mockResponse));

    const openSpy = spyOn((component as unknown as { dialog: MatDialog }).dialog, 'open').and.returnValue({
      afterClosed: () => of('cancel')
    } as never);

    component.form.patchValue({
      event_id: 1,
      warehouse_ids: [1, 2],
      phase: 'BASELINE'
    });

    component.calculateGaps();

    expect(openSpy).toHaveBeenCalled();
    const dialogConfig = openSpy.calls.mostRecent().args[1] as { data: { existingLists: { needs_list_id: string }[] } };
    expect(dialogConfig.data.existingLists.length).toBe(1);
    expect(dialogConfig.data.existingLists[0].needs_list_id).toBe('NL-DUP-1');
    expect(mockReplenishmentService.getStockStatusMulti).not.toHaveBeenCalled();
  });

  it('should show network error on API failure', () => {
    mockReplenishmentService.getStockStatusMulti.and.returnValue(
      throwError(() => ({ message: 'API Error' }))
    );

    component.form.patchValue({
      event_id: 1,
      warehouse_ids: [1],
      phase: 'BASELINE'
    });

    component.calculateGaps();

    expect(mockNotificationService.showNetworkError).toHaveBeenCalledWith(
      'API Error',
      jasmine.any(Function)
    );
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
