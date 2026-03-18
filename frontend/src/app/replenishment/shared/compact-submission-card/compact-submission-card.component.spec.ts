import { ComponentFixture, TestBed } from '@angular/core/testing';

import { NeedsListSummary } from '../../models/needs-list.model';
import { CompactSubmissionCardComponent } from './compact-submission-card.component';

describe('CompactSubmissionCardComponent', () => {
  let fixture: ComponentFixture<CompactSubmissionCardComponent>;
  let component: CompactSubmissionCardComponent;

  const submission: NeedsListSummary = {
    id: 'NL-100',
    reference_number: 'REF-100',
    warehouse: {
      id: 1,
      name: 'Central Warehouse',
      code: 'CW'
    },
    event: {
      id: 10,
      name: 'Storm',
      phase: 'SURGE'
    },
    selected_method: 'A',
    status: 'APPROVED',
    total_items: 4,
    fulfilled_items: 1,
    remaining_items: 3,
    horizon_summary: {
      horizon_a: { count: 1, estimated_value: 10 },
      horizon_b: { count: 1, estimated_value: 20 },
      horizon_c: { count: 1, estimated_value: 30 }
    },
    submitted_at: '2026-03-17T12:00:00Z',
    approved_at: null,
    last_updated_at: '2026-03-17T13:00:00Z',
    superseded_by_id: null,
    supersedes_id: null,
    has_external_updates: false,
    external_update_summary: [],
    created_by: {
      id: 5,
      name: 'Analyst'
    }
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CompactSubmissionCardComponent]
    }).compileComponents();

    fixture = TestBed.createComponent(CompactSubmissionCardComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('submission', submission);
    fixture.componentRef.setInput('showSelection', true);
    fixture.detectChanges();
  });

  it('uses a submission-specific checkbox aria-label', () => {
    const checkbox: HTMLInputElement | null = fixture.nativeElement.querySelector('.card-checkbox');

    expect(checkbox?.getAttribute('aria-label')).toBe('Select submission REF-100');
  });

  it('shows the full reference and warehouse name as tooltips', () => {
    const reference: HTMLElement | null = fixture.nativeElement.querySelector('.ref-number');
    const warehouse: HTMLElement | null = fixture.nativeElement.querySelector('.warehouse');

    expect(reference?.getAttribute('ng-reflect-message')).toBe('REF-100');
    expect(warehouse?.getAttribute('ng-reflect-message')).toBe('Central Warehouse');
  });

  it('uses clearer progress action wording and pluralized item counts', () => {
    const itemCount: HTMLElement | null = fixture.nativeElement.querySelector('.item-count');
    const actionButton: HTMLButtonElement | null = fixture.nativeElement.querySelector('.action-btn');

    expect(itemCount?.textContent?.trim()).toBe('4 items');
    expect(actionButton?.textContent?.trim()).toBe('View Progress');
  });

  it('opens the card when keyboard activation originates on the card container', () => {
    const card = fixture.nativeElement.querySelector('.compact-card') as HTMLDivElement;
    const emitSpy = spyOn(component.cardClick, 'emit');
    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true });

    card.dispatchEvent(event);

    expect(emitSpy).toHaveBeenCalledWith(submission);
  });

  it('ignores bubbled keydown events from nested controls', () => {
    const checkbox = fixture.nativeElement.querySelector('.card-checkbox') as HTMLInputElement;
    const emitSpy = spyOn(component.cardClick, 'emit');
    const event = new KeyboardEvent('keydown', { key: ' ', bubbles: true });

    checkbox.dispatchEvent(event);

    expect(emitSpy).not.toHaveBeenCalled();
  });

  it('renders a singular item count when there is only one item', () => {
    fixture.componentRef.setInput('submission', {
      ...submission,
      total_items: 1
    });
    fixture.detectChanges();

    const itemCount: HTMLElement | null = fixture.nativeElement.querySelector('.item-count');

    expect(itemCount?.textContent?.trim()).toBe('1 item');
  });
});
