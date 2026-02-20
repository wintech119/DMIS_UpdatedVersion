import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { NgClass } from '@angular/common';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { NeedsListSummary } from '../../models/needs-list.model';

interface StatusGroup {
  label: string;
  count: number;
  icon: string;
  cssClass: string;
}

const DRAFT_FILTER_STATUS_SET = new Set<string>(['DRAFT', 'MODIFIED', 'RETURNED']);
const DRAFT_FILTER_STATUS_QUERY = 'DRAFT,MODIFIED,RETURNED';

@Component({
  selector: 'app-my-drafts-submissions-panel',
  standalone: true,
  imports: [NgClass, MatButtonModule, MatIconModule],
  templateUrl: './my-drafts-submissions-panel.component.html',
  styleUrl: './my-drafts-submissions-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class MyDraftsSubmissionsPanelComponent {
  private readonly router = inject(Router);

  readonly submissions = input<NeedsListSummary[]>([]);
  readonly title = input('My Drafts & Submissions');

  readonly totalCount = computed(() => this.submissions().length);

  readonly statusGroups = computed<StatusGroup[]>(() => {
    const items = this.submissions();
    const draftCount = items.filter((s) => DRAFT_FILTER_STATUS_SET.has(s.status)).length;
    const pendingCount = items.filter((s) => s.status === 'PENDING_APPROVAL').length;
    const activeCount = items.filter(
      (s) => s.status === 'APPROVED' || s.status === 'IN_PROGRESS'
    ).length;
    const otherCount = items.filter(
      (s) =>
        s.status === 'FULFILLED' ||
        s.status === 'REJECTED' ||
        s.status === 'SUPERSEDED' ||
        s.status === 'CANCELLED'
    ).length;

    const groups: StatusGroup[] = [];
    if (draftCount > 0) {
      groups.push({ label: 'Drafts', count: draftCount, icon: 'edit_note', cssClass: 'group-draft' });
    }
    if (pendingCount > 0) {
      groups.push({ label: 'Pending Approval', count: pendingCount, icon: 'pending_actions', cssClass: 'group-pending' });
    }
    if (activeCount > 0) {
      groups.push({ label: 'Active', count: activeCount, icon: 'local_shipping', cssClass: 'group-active' });
    }
    if (otherCount > 0) {
      groups.push({ label: 'Completed / Other', count: otherCount, icon: 'history', cssClass: 'group-other' });
    }
    return groups;
  });

  readonly hasDrafts = computed(() =>
    this.submissions().some((s) => DRAFT_FILTER_STATUS_SET.has(s.status))
  );

  navigateToFullPage(): void {
    this.router.navigate(['/replenishment/my-submissions']);
  }

  navigateToDrafts(): void {
    this.router.navigate(['/replenishment/my-submissions'], {
      queryParams: { status: DRAFT_FILTER_STATUS_QUERY }
    });
  }
}
