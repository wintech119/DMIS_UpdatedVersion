import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { CurrencyPipe, DatePipe, DecimalPipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterModule } from '@angular/router';

import { HorizonSummaryBucket, NeedsListSummary, NeedsListSummaryStatus } from '../../models/needs-list.model';
import {
  getHorizonActionTargets,
  getNeedsListActionTarget,
  HorizonActionTarget,
  toNeedsListStatusLabel
} from '../needs-list-action.util';

interface HorizonDisplay {
  key: string;
  label: string;
  icon: string;
  bucket: HorizonSummaryBucket;
}

@Component({
  selector: 'app-submission-card',
  standalone: true,
  imports: [
    CurrencyPipe,
    DatePipe,
    DecimalPipe,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatProgressBarModule,
    MatTooltipModule,
    RouterModule
  ],
  templateUrl: './submission-card.component.html',
  styleUrl: './submission-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class SubmissionCardComponent {
  readonly submission = input.required<NeedsListSummary>();
  readonly showSelection = input(false);
  readonly selected = input(false);
  readonly recentlyChanged = input(false);

  readonly refresh = output<string>();
  readonly openAction = output<{ id: string; status: NeedsListSummaryStatus }>();
  readonly horizonAction = output<HorizonActionTarget>();
  readonly selectedChange = output<boolean>();

  readonly showProgress = signal(false);

  readonly progressPercentage = computed(() => {
    const current = this.submission();
    if (!current.total_items) {
      return 0;
    }
    const percentage = (current.fulfilled_items / current.total_items) * 100;
    return Number(percentage.toFixed(1));
  });

  readonly actionTarget = computed(() =>
    getNeedsListActionTarget(this.submission().id, this.submission().status)
  );

  readonly statusLabel = computed(() =>
    toNeedsListStatusLabel(this.submission().status)
  );

  readonly horizonDisplays = computed((): HorizonDisplay[] => {
    const hs = this.submission().horizon_summary;
    return [
      { key: 'A', label: 'Transfers', icon: 'local_shipping', bucket: hs.horizon_a },
      { key: 'B', label: 'Donations', icon: 'volunteer_activism', bucket: hs.horizon_b },
      { key: 'C', label: 'Procurement', icon: 'shopping_cart', bucket: hs.horizon_c }
    ];
  });

  readonly activeHorizons = computed(() =>
    this.horizonDisplays().filter(h => h.bucket.count > 0)
  );

  readonly horizonActions = computed(() =>
    getHorizonActionTargets(
      this.submission().id,
      this.submission().status,
      this.submission().horizon_summary
    )
  );

  readonly totalItems = computed(() => this.submission().total_items);
  readonly totalEstimatedValue = computed(() => {
    const hs = this.submission().horizon_summary;
    return hs.horizon_a.estimated_value + hs.horizon_b.estimated_value + hs.horizon_c.estimated_value;
  });

  readonly contextualTimestamp = computed(() => {
    const current = this.submission();
    switch (current.status) {
      case 'DRAFT':
      case 'MODIFIED':
        return { label: 'Last Modified', value: current.last_updated_at };
      case 'PENDING_APPROVAL':
        return { label: 'Submitted', value: current.submitted_at };
      case 'APPROVED':
      case 'IN_PROGRESS':
        return { label: 'Approved', value: current.approved_at || current.last_updated_at };
      case 'FULFILLED':
        return { label: 'Completed', value: current.last_updated_at };
      default:
        return { label: 'Updated', value: current.last_updated_at };
    }
  });

  onActionClick(): void {
    const current = this.submission();
    this.openAction.emit({ id: current.id, status: current.status });
  }

  onHorizonActionClick(target: HorizonActionTarget): void {
    this.horizonAction.emit(target);
  }

  toggleProgress(): void {
    this.showProgress.update((value) => !value);
  }

  onRefreshClick(): void {
    this.refresh.emit(this.submission().id);
  }

  onSelectedChange(checked: boolean): void {
    this.selectedChange.emit(checked);
  }

  onSelectionInput(event: Event): void {
    const target = event.target as HTMLInputElement | null;
    this.selectedChange.emit(Boolean(target?.checked));
  }
}
