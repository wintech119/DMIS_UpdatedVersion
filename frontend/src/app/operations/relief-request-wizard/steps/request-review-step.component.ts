import {
  Component, ChangeDetectionStrategy, Input,
} from '@angular/core';
import { DecimalPipe, DatePipe } from '@angular/common';
import { MatTableModule } from '@angular/material/table';

import { formatUrgency, getUrgencyCssClass } from '../../models/operations-status.util';

export interface ReviewFormValue {
  agency_id: number | null;
  agency_name: string | null;
  urgency_ind: string | null;
  eligible_event_id: number | null;
  event_name: string | null;
  request_date_text: string;
  submission_mode_label: string;
  rqst_notes_text: string;
  items: ReviewItemValue[];
}

export interface ReviewItemValue {
  item_id: number | null;
  item_name: string | null;
  request_qty: number | null;
  urgency_ind: string | null;
  rqst_reason_desc: string;
  required_by_date: string | Date | null;
}

@Component({
  selector: 'app-request-review-step',
  standalone: true,
  imports: [
    DecimalPipe,
    DatePipe,
    MatTableModule,
  ],
  templateUrl: './request-review-step.component.html',
  styleUrl: './request-review-step.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RequestReviewStepComponent {
  @Input({ required: true }) formValue!: ReviewFormValue;

  readonly itemColumns = ['index', 'item_name', 'request_qty', 'urgency_ind', 'rqst_reason_desc', 'required_by_date'];

  readonly formatUrgency = formatUrgency;
  readonly getUrgencyCssClass = getUrgencyCssClass;

  get totalItems(): number {
    return this.formValue.items?.length ?? 0;
  }

  get totalQuantity(): number {
    return (this.formValue.items ?? []).reduce(
      (sum, item) => sum + (Number(item.request_qty) || 0), 0
    );
  }

  trackByIndex(index: number): number {
    return index;
  }
}
