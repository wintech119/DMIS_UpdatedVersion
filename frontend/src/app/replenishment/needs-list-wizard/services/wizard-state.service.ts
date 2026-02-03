import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { WizardState, ItemAdjustment } from '../models/wizard-state.model';

const STORAGE_KEY = 'dmis_needs_wizard_state';

@Injectable({ providedIn: 'root' })
export class WizardStateService {
  private state$ = new BehaviorSubject<WizardState>({ adjustments: {} });

  constructor() {
    this.loadFromStorage();
  }

  getState(): WizardState {
    return this.state$.value;
  }

  getState$(): Observable<WizardState> {
    return this.state$.asObservable();
  }

  updateState(partial: Partial<WizardState>): void {
    const newState = { ...this.state$.value, ...partial };
    this.state$.next(newState);
    this.saveToStorage(newState);
  }

  // Step 1 validation
  isStep1Valid$(): Observable<boolean> {
    return this.state$.pipe(
      map(state => !!(
        state.event_id &&
        state.warehouse_ids &&
        state.warehouse_ids.length > 0 &&
        state.phase
      ))
    );
  }

  // Step 2 validation
  isStep2Valid$(): Observable<boolean> {
    return this.state$.pipe(
      map(state => !!(state.previewResponse?.items.length))
    );
  }

  // Adjustments (keyed by item_id + warehouse_id)
  setAdjustment(item_id: number, warehouse_id: number, adjustment: ItemAdjustment): void {
    const key = `${item_id}_${warehouse_id}`;
    const adjustments = { ...this.state$.value.adjustments, [key]: adjustment };
    this.updateState({ adjustments });
  }

  getAdjustment(item_id: number, warehouse_id: number): ItemAdjustment | null {
    const key = `${item_id}_${warehouse_id}`;
    return this.state$.value.adjustments[key] || null;
  }

  removeAdjustment(item_id: number, warehouse_id: number): void {
    const key = `${item_id}_${warehouse_id}`;
    const adjustments = { ...this.state$.value.adjustments };
    delete adjustments[key];
    this.updateState({ adjustments });
  }

  private saveToStorage(state: WizardState): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      console.error('Failed to save wizard state:', e);
    }
  }

  private loadFromStorage(): void {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        this.state$.next(JSON.parse(saved));
      }
    } catch (e) {
      console.error('Failed to load wizard state:', e);
    }
  }

  reset(): void {
    this.state$.next({ adjustments: {} });
    localStorage.removeItem(STORAGE_KEY);
  }
}
