import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { BehaviorSubject, of } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { Router } from '@angular/router';

import { PreviewStepComponent } from './preview-step.component';
import { WizardStateService } from '../../services/wizard-state.service';
import { WizardState } from '../../models/wizard-state.model';
import { NeedsListItem, NeedsListResponse } from '../../../models/needs-list.model';
import { ReplenishmentService } from '../../../services/replenishment.service';

describe('PreviewStepComponent', () => {
  let fixture: ComponentFixture<PreviewStepComponent>;
  let component: PreviewStepComponent;
  let state$: BehaviorSubject<WizardState>;

  const wizardServiceStub = {
    getState: () => state$.value,
    getState$: () => state$.asObservable(),
    getAdjustment: jasmine.createSpy('getAdjustment').and.returnValue(null),
    setAdjustment: jasmine.createSpy('setAdjustment'),
    removeAdjustment: jasmine.createSpy('removeAdjustment'),
    updateState: jasmine.createSpy('updateState'),
    reset: jasmine.createSpy('reset')
  };

  const replenishmentServiceStub = {
    bulkDeleteDrafts: jasmine.createSpy('bulkDeleteDrafts').and.returnValue(
      of({ cancelled_ids: [], errors: [], count: 0 })
    )
  };

  const routerStub = {
    navigate: jasmine.createSpy('navigate')
  };

  const toPreviewResponse = (items: NeedsListItem[]): NeedsListResponse => ({
    event_id: 1,
    phase: 'BASELINE',
    items,
    as_of_datetime: '2026-02-16T00:00:00Z'
  });

  const createItem = (
    item_id: number,
    severity: NeedsListItem['severity'],
    gap_qty: number,
    item_name: string
  ): NeedsListItem => ({
    item_id,
    item_name,
    warehouse_id: 1,
    warehouse_name: 'Main Warehouse',
    available_qty: 0,
    inbound_strict_qty: 0,
    burn_rate_per_hour: 1,
    gap_qty,
    severity
  });

  beforeEach(async () => {
    state$ = new BehaviorSubject<WizardState>({
      adjustments: {},
      previewResponse: toPreviewResponse([
        createItem(1, 'OK', 0, 'OK Zero Gap'),
        createItem(2, 'WATCH', 30, 'Watch Item'),
        createItem(3, 'CRITICAL', 20, 'Critical Item'),
        createItem(4, 'WARNING', 25, 'Warning Item'),
        createItem(5, 'OK', 10, 'OK Positive Gap')
      ])
    });

    await TestBed.configureTestingModule({
      imports: [PreviewStepComponent, NoopAnimationsModule],
      providers: [
        { provide: WizardStateService, useValue: wizardServiceStub },
        { provide: ReplenishmentService, useValue: replenishmentServiceStub },
        { provide: Router, useValue: routerStub }
      ]
    }).compileComponents();

    fixture = TestBed.createComponent(PreviewStepComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('sorts actionable severities before OK items', () => {
    expect(component.items.map((item) => item.severity)).toEqual([
      'CRITICAL',
      'WARNING',
      'WATCH',
      'OK',
      'OK'
    ]);
  });

  it('auto-selects actionable gap items and leaves OK items unselected', () => {
    const includedByName = new Map(component.items.map((item) => [item.item_name, item.included]));

    expect(includedByName.get('Critical Item')).toBeTrue();
    expect(includedByName.get('Warning Item')).toBeTrue();
    expect(includedByName.get('Watch Item')).toBeTrue();
    expect(includedByName.get('OK Positive Gap')).toBeFalse();
    expect(includedByName.get('OK Zero Gap')).toBeFalse();
  });

  it('does not delete an existing edited draft when cancel is confirmed', () => {
    state$.next({
      ...state$.value,
      editing_draft_id: 'NL-40',
      draft_ids: ['NL-40'],
      previewResponse: {
        ...state$.value.previewResponse!,
        needs_list_id: 'NL-40',
        status: 'DRAFT'
      }
    });

    const dialog = (component as unknown as { dialog: MatDialog }).dialog;
    spyOn(dialog, 'open').and.returnValue({
      afterClosed: () => of(true)
    } as never);

    component.cancel();

    expect(replenishmentServiceStub.bulkDeleteDrafts).not.toHaveBeenCalled();
    expect(wizardServiceStub.reset).toHaveBeenCalled();
    expect(routerStub.navigate).toHaveBeenCalledWith(['/replenishment/dashboard']);
  });
});
