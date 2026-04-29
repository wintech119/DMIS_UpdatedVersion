import {
  Component, ChangeDetectionStrategy, Input,
} from '@angular/core';
import { DecimalPipe, DatePipe } from '@angular/common';
import { MatTableModule } from '@angular/material/table';

import {
  formatOperationsUrgency,
  getOperationsUrgencyTone,
  mapOperationsToneToChipTone,
  type OperationsTone,
} from '../../operations-display.util';
import {
  OpsMetricStripComponent,
  type OpsMetricStripItem,
  type OpsMetricTileTone,
} from '../../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../../shared/ops-status-chip.component';

export interface ReviewFormValue {
  agency_id: number | null;
  agency_name: string | null;
  requester_label: string;
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

type ChipTone = ReturnType<typeof mapOperationsToneToChipTone>;

@Component({
  selector: 'app-request-review-step',
  standalone: true,
  imports: [
    DecimalPipe,
    DatePipe,
    MatTableModule,
    OpsMetricStripComponent,
    OpsStatusChipComponent,
  ],
  templateUrl: './request-review-step.component.html',
  styleUrl: './request-review-step.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RequestReviewStepComponent {
  @Input({ required: true }) formValue!: ReviewFormValue;

  readonly itemColumns = ['index', 'item_name', 'request_qty', 'urgency_ind', 'rqst_reason_desc', 'required_by_date'];

  readonly formatUrgency = (code: string | null | undefined): string => formatOperationsUrgency(code);

  /**
   * Tone resolver for the urgency chips inside the summary card and item
   * ledger. Centralises the routing so the review surface stays in lock
   * step with the eligibility / dispatch / list surfaces.
   */
  urgencyChipTone(code: string | null | undefined): ChipTone {
    const tone: OperationsTone = getOperationsUrgencyTone(code);
    return mapOperationsToneToChipTone(tone);
  }

  get totalItems(): number {
    return this.formValue.items?.length ?? 0;
  }

  get totalQuantity(): number {
    return (this.formValue.items ?? []).reduce(
      (sum, item) => sum + (Number(item.request_qty) || 0), 0
    );
  }

  /**
   * `app-ops-metric-strip` model for the review summary. Three
   * non-interactive tiles (Items / Total qty / Urgency). Token tones
   * keep the left-edge accent bar consistent with the queue surfaces.
   */
  get metricItems(): OpsMetricStripItem[] {
    const urgencyToken = mapMetricTileToneFromUrgency(this.formValue.urgency_ind);
    return [
      {
        label: 'Items',
        value: String(this.totalItems),
        token: 'info',
      },
      {
        label: 'Total qty',
        value: this.totalQuantity.toLocaleString(),
        token: 'neutral',
      },
      {
        label: 'Urgency',
        value: this.formValue.urgency_ind
          ? formatOperationsUrgency(this.formValue.urgency_ind)
          : 'Pending',
        token: urgencyToken,
      },
    ];
  }

  trackByIndex(index: number): number {
    return index;
  }
}

function mapMetricTileToneFromUrgency(code: string | null | undefined): OpsMetricTileTone {
  const normalized = String(code ?? '').trim().toUpperCase();
  switch (normalized) {
    case 'C':
      // Critical → red accent — closest available metric-tile tone is
      // 'awaiting' (warm warning amber) which mismatches; so the urgency
      // chip carries the colour and the tile uses 'neutral' to avoid
      // double-coding red.
      return 'neutral';
    case 'H':
      return 'awaiting';
    case 'M':
      return 'info';
    case 'L':
      return 'completed';
    default:
      return 'neutral';
  }
}
