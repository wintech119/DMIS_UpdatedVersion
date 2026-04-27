import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';

import {
  RequestReviewStepComponent,
  ReviewFormValue,
  ReviewItemValue,
} from './request-review-step.component';

function buildItem(overrides: Partial<ReviewItemValue> = {}): ReviewItemValue {
  return {
    item_id: 1,
    item_name: 'Tarpaulins',
    request_qty: 5,
    urgency_ind: null,
    rqst_reason_desc: '',
    required_by_date: null,
    ...overrides,
  };
}

function buildFormValue(overrides: Partial<ReviewFormValue> = {}): ReviewFormValue {
  return {
    agency_id: 12,
    agency_name: 'St. Mary Parish Council',
    requester_label: 'Requesting entity',
    urgency_ind: 'M',
    eligible_event_id: 44,
    event_name: 'Flood Response 2026',
    request_date_text: 'Will appear after saving',
    submission_mode_label: 'Your organisation\'s request',
    rqst_notes_text: '',
    items: [],
    ...overrides,
  };
}

describe('RequestReviewStepComponent', () => {
  let fixture: ComponentFixture<RequestReviewStepComponent>;
  let component: RequestReviewStepComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, RequestReviewStepComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(RequestReviewStepComponent);
    component = fixture.componentInstance;
  });

  it('renders the metric strip with Items, Total qty, and Urgency tiles', () => {
    component.formValue = buildFormValue({
      urgency_ind: 'H',
      items: [
        buildItem({ request_qty: 5 }),
        buildItem({ request_qty: 10 }),
        buildItem({ request_qty: 15 }),
      ],
    });
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const strip = host.querySelector<HTMLElement>('app-ops-metric-strip');
    expect(strip).not.toBeNull();
    expect(strip?.getAttribute('aria-label')).toBe('Review summary');

    const labels = Array.from(host.querySelectorAll<HTMLElement>('.ops-flow-strip__label'))
      .map((node) => node.textContent?.trim() ?? '');
    expect(labels).toEqual(['Items', 'Total qty', 'Urgency']);

    const values = Array.from(host.querySelectorAll<HTMLElement>('.ops-flow-strip__value'))
      .map((node) => node.textContent?.trim() ?? '');
    expect(values[0]).toBe('3');
    expect(values[1]).toBe('30');
    expect(values[2]).toBe('High');
  });

  it('routes the urgency badge through app-ops-status-chip with the critical tone for C', () => {
    component.formValue = buildFormValue({ urgency_ind: 'C', items: [buildItem()] });
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const chips = host.querySelectorAll<HTMLElement>('app-ops-status-chip');
    expect(chips.length).toBeGreaterThan(0);
    // Tone is a signal input — reflected on the inner `.ops-chip` class
    // list rather than as a DOM attribute on the host.
    const innerChip = chips[0].querySelector<HTMLElement>('.ops-chip');
    expect(innerChip?.classList.contains('ops-chip--critical')).toBeTrue();
    expect(chips[0].textContent).toContain('Critical');
  });

  it('preserves notes verbatim including newlines inside the .review-notes block', () => {
    component.formValue = buildFormValue({
      rqst_notes_text: 'Line one.\nLine two with detail.',
      items: [buildItem()],
    });
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const notes = host.querySelector<HTMLElement>('.review-notes');
    expect(notes).not.toBeNull();
    expect(notes?.textContent).toContain('Line one.');
    expect(notes?.textContent).toContain('Line two with detail.');
    // white-space: pre-wrap preserves the newline so the rendered text
    // contains the literal newline character.
    expect(notes?.textContent).toContain('\n');
  });

  it('renders the item ledger table with the canonical column set when items > 0', () => {
    component.formValue = buildFormValue({ items: [buildItem(), buildItem()] });
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    const table = host.querySelector<HTMLElement>('table.review-table');
    expect(table).not.toBeNull();

    const headers = Array.from(host.querySelectorAll<HTMLElement>('th.mat-mdc-header-cell'))
      .map((th) => th.textContent?.trim() ?? '');
    expect(headers).toEqual(['#', 'Item', 'Quantity', 'Urgency', 'Reason', 'Required by']);
  });

  it('hides the item ledger table when the items array is empty', () => {
    component.formValue = buildFormValue({ items: [] });
    fixture.detectChanges();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('table.review-table')).toBeNull();
  });
});
