import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, input, output, signal } from '@angular/core';
import { NgClass } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { NeedsListSummary } from '../../models/needs-list.model';
import { toNeedsListStatusLabel } from '../needs-list-action.util';

type StatusDotClass = 'dot-critical' | 'dot-warning' | 'dot-info' | 'dot-success' | 'dot-muted';

const STATUS_DOT_MAP: Record<string, StatusDotClass> = {
  DRAFT: 'dot-warning',
  MODIFIED: 'dot-warning',
  RETURNED: 'dot-critical',
  PENDING_APPROVAL: 'dot-info',
  SUBMITTED: 'dot-info',
  UNDER_REVIEW: 'dot-info',
  APPROVED: 'dot-info',
  IN_PROGRESS: 'dot-info',
  DISPATCHED: 'dot-info',
  IN_TRANSIT: 'dot-info',
  FULFILLED: 'dot-success',
  RECEIVED: 'dot-success',
  COMPLETED: 'dot-success',
  REJECTED: 'dot-critical',
  CANCELLED: 'dot-muted',
  SUPERSEDED: 'dot-muted'
};

const PRIMARY_ACTION_MAP: Record<string, string> = {
  DRAFT: 'Edit',
  MODIFIED: 'Edit',
  RETURNED: 'Revise',
  PENDING_APPROVAL: 'Review',
  SUBMITTED: 'Review',
  UNDER_REVIEW: 'Review',
  APPROVED: 'View Progress',
  IN_PROGRESS: 'View Progress',
  DISPATCHED: 'View Progress',
  IN_TRANSIT: 'View Progress'
};

const PROGRESS_ACTION_STATUSES = new Set([
  'APPROVED',
  'IN_PROGRESS',
  'DISPATCHED',
  'IN_TRANSIT'
]);

@Component({
  selector: 'app-compact-submission-card',
  standalone: true,
  imports: [NgClass, MatButtonModule, MatIconModule, MatTooltipModule],
  templateUrl: './compact-submission-card.component.html',
  styleUrl: './compact-submission-card.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class CompactSubmissionCardComponent {
  private readonly destroyRef = inject(DestroyRef);
  private readonly now = signal(Date.now());

  readonly submission = input.required<NeedsListSummary>();
  readonly selected = input(false);
  readonly showSelection = input(false);
  readonly recentlyChanged = input(false);

  readonly cardClick = output<NeedsListSummary>();
  readonly selectionToggle = output<{ id: string; selected: boolean }>();
  readonly actionClick = output<{ submission: NeedsListSummary; action: string }>();

  readonly statusDotClass = computed((): StatusDotClass =>
    STATUS_DOT_MAP[this.submission().status] ?? 'dot-muted'
  );

  readonly statusLabel = computed(() =>
    toNeedsListStatusLabel(this.submission().status)
  );

  readonly primaryAction = computed((): string | null =>
    PRIMARY_ACTION_MAP[this.submission().status] ?? null
  );

  readonly itemCountLabel = computed(() => {
    const totalItems = this.submission().total_items;
    return `${totalItems} ${totalItems === 1 ? 'item' : 'items'}`;
  });

  readonly showsProgressAction = computed(() => PROGRESS_ACTION_STATUSES.has(this.submission().status));

  constructor() {
    const timerId = window.setInterval(() => this.now.set(Date.now()), 60_000);
    this.destroyRef.onDestroy(() => window.clearInterval(timerId));
  }

  readonly formattedDate = computed((): string => {
    const sub = this.submission();
    const raw = sub.submitted_at || sub.last_updated_at;
    if (!raw) return '';

    const date = new Date(raw);
    const diffMs = this.now() - date.getTime();
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffHours < 1) return 'Just now';
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays}d ago`;

    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  });

  onCardClick(): void {
    this.cardClick.emit(this.submission());
  }

  onCardKeydown(event: Event): void {
    if (!(event instanceof KeyboardEvent)) {
      return;
    }

    if (event.target !== event.currentTarget) {
      return;
    }

    event.preventDefault();
    this.onCardClick();
  }

  onActionClick(event: MouseEvent): void {
    event.stopPropagation();
    const action = this.primaryAction();
    if (action) {
      this.actionClick.emit({ submission: this.submission(), action });
    }
  }

  onSelectionInput(event: Event): void {
    event.stopPropagation();
    const target = event.target as HTMLInputElement | null;
    this.selectionToggle.emit({
      id: this.submission().id,
      selected: Boolean(target?.checked)
    });
  }
}
