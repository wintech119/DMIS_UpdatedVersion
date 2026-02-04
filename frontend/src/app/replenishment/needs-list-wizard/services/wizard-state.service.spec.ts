import { TestBed } from '@angular/core/testing';
import { WizardStateService } from './wizard-state.service';
import { ItemAdjustment } from '../models/wizard-state.model';
import { take } from 'rxjs/operators';

describe('WizardStateService', () => {
  let service: WizardStateService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({});
    service = TestBed.inject(WizardStateService);
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  describe('State Management', () => {
    it('should initialize with empty state', () => {
      const state = service.getState();
      expect(state.adjustments).toEqual({});
      expect(state.event_id).toBeUndefined();
      expect(state.warehouse_ids).toBeUndefined();
    });

    it('should update state', () => {
      service.updateState({
        event_id: 1,
        warehouse_ids: [1, 2],
        phase: 'BASELINE'
      });

      const state = service.getState();
      expect(state.event_id).toBe(1);
      expect(state.warehouse_ids).toEqual([1, 2]);
      expect(state.phase).toBe('BASELINE');
    });

    it('should persist state to localStorage', () => {
      service.updateState({
        event_id: 1,
        warehouse_ids: [1],
        phase: 'SURGE'
      });

      const saved = localStorage.getItem('dmis_needs_wizard_state');
      expect(saved).toBeTruthy();

      const parsed = JSON.parse(saved!);
      expect(parsed.event_id).toBe(1);
      expect(parsed.phase).toBe('SURGE');
    });

    it('should load state from localStorage on init', () => {
      localStorage.setItem('dmis_needs_wizard_state', JSON.stringify({
        event_id: 2,
        warehouse_ids: [3],
        phase: 'STABILIZED',
        adjustments: {}
      }));

      const newService = new WizardStateService();
      const state = newService.getState();

      expect(state.event_id).toBe(2);
      expect(state.warehouse_ids).toEqual([3]);
      expect(state.phase).toBe('STABILIZED');
    });

    it('should reset state', () => {
      service.updateState({
        event_id: 1,
        warehouse_ids: [1],
        phase: 'BASELINE'
      });

      service.reset();

      const state = service.getState();
      expect(state.adjustments).toEqual({});
      expect(state.event_id).toBeUndefined();

      const saved = localStorage.getItem('dmis_needs_wizard_state');
      expect(saved).toBeNull();
    });
  });

  describe('Step Validation', () => {
    it('should validate step 1 correctly', (done) => {
      // First check - should be invalid
      service.isStep1Valid$().pipe(take(1)).subscribe(valid => {
        expect(valid).toBe(false);
      });

      // Update state to make it valid
      service.updateState({
        event_id: 1,
        warehouse_ids: [1, 2],
        phase: 'BASELINE'
      });

      // Second check - should be valid
      service.isStep1Valid$().pipe(take(1)).subscribe(valid => {
        expect(valid).toBe(true);
        done();
      });
    });

    it('should invalidate step 1 with empty warehouse_ids', (done) => {
      service.updateState({
        event_id: 1,
        warehouse_ids: [],
        phase: 'BASELINE'
      });

      service.isStep1Valid$().pipe(take(1)).subscribe(valid => {
        expect(valid).toBe(false);
        done();
      });
    });

    it('should validate step 2 correctly', (done) => {
      // First check - should be invalid
      service.isStep2Valid$().pipe(take(1)).subscribe(valid => {
        expect(valid).toBe(false);
      });

      // Update state to make it valid
      service.updateState({
        previewResponse: {
          event_id: 1,
          phase: 'BASELINE',
          items: [
            {
              item_id: 1,
              available_qty: 10,
              inbound_strict_qty: 5,
              burn_rate_per_hour: 2,
              gap_qty: 0
            }
          ],
          as_of_datetime: new Date().toISOString()
        }
      });

      // Second check - should be valid
      service.isStep2Valid$().pipe(take(1)).subscribe(valid => {
        expect(valid).toBe(true);
        done();
      });
    });
  });

  describe('Adjustments', () => {
    it('should set adjustment for item', () => {
      const adjustment: ItemAdjustment = {
        item_id: 1,
        warehouse_id: 1,
        original_qty: 100,
        adjusted_qty: 80,
        reason: 'BUDGET_CONSTRAINT',
        notes: 'Budget limitations'
      };

      service.setAdjustment(1, 1, adjustment);

      const retrieved = service.getAdjustment(1, 1);
      expect(retrieved).toEqual(adjustment);
    });

    it('should use composite key for adjustments', () => {
      const adj1: ItemAdjustment = {
        item_id: 1,
        warehouse_id: 1,
        original_qty: 100,
        adjusted_qty: 80,
        reason: 'BUDGET_CONSTRAINT'
      };

      const adj2: ItemAdjustment = {
        item_id: 1,
        warehouse_id: 2,
        original_qty: 100,
        adjusted_qty: 90,
        reason: 'PRIORITY_CHANGE'
      };

      service.setAdjustment(1, 1, adj1);
      service.setAdjustment(1, 2, adj2);

      expect(service.getAdjustment(1, 1)?.adjusted_qty).toBe(80);
      expect(service.getAdjustment(1, 2)?.adjusted_qty).toBe(90);
    });

    it('should remove adjustment', () => {
      const adjustment: ItemAdjustment = {
        item_id: 1,
        warehouse_id: 1,
        original_qty: 100,
        adjusted_qty: 80,
        reason: 'BUDGET_CONSTRAINT'
      };

      service.setAdjustment(1, 1, adjustment);
      expect(service.getAdjustment(1, 1)).toBeTruthy();

      service.removeAdjustment(1, 1);
      expect(service.getAdjustment(1, 1)).toBeNull();
    });

    it('should return null for non-existent adjustment', () => {
      const result = service.getAdjustment(999, 999);
      expect(result).toBeNull();
    });
  });

  describe('Observable State', () => {
    it('should emit state changes', (done) => {
      const emissions: any[] = [];

      service.getState$().subscribe(state => {
        emissions.push(state);
      });

      service.updateState({ event_id: 1 });
      service.updateState({ warehouse_ids: [1] });

      setTimeout(() => {
        expect(emissions.length).toBeGreaterThan(1);
        expect(emissions[emissions.length - 1].event_id).toBe(1);
        expect(emissions[emissions.length - 1].warehouse_ids).toEqual([1]);
        done();
      }, 100);
    });
  });
});
