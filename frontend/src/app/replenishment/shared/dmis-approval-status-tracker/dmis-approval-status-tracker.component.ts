import {
  Component, Input, Output, EventEmitter,
  ChangeDetectionStrategy, OnChanges, SimpleChanges
} from '@angular/core';
import { CommonModule, DatePipe, DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';

import {
  NeedsListResponse, NeedsListStatus,
  TrackerStep, TrackerStepId, TrackerStepState, TrackerBranch
} from '../../models/needs-list.model';
import { HorizonType, APPROVAL_WORKFLOWS } from '../../models/approval-workflows.model';

const STEP_ORDER: TrackerStepId[] = [
  'DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'IN_PROGRESS', 'FULFILLED'
];

const STEP_META: Record<TrackerStepId, { label: string; icon: string }> = {
  DRAFT: { label: 'Draft', icon: 'edit_note' },
  PENDING_APPROVAL: { label: 'Pending Approval', icon: 'hourglass_top' },
  APPROVED: { label: 'Approved', icon: 'verified' },
  IN_PROGRESS: { label: 'In Progress', icon: 'local_shipping' },
  FULFILLED: { label: 'Fulfilled', icon: 'task_alt' }
};

type TerminalStepId = 'CANCELLED' | 'SUPERSEDED';

/** Maps backend NeedsListStatus to our simplified TrackerStepId */
function mapStatusToStep(status: NeedsListStatus): TrackerStepId | TerminalStepId {
  switch (status) {
    case 'DRAFT':
    case 'RETURNED':
      return 'DRAFT';
    case 'SUBMITTED':
    case 'UNDER_REVIEW':
      return 'PENDING_APPROVAL';
    case 'APPROVED':
      return 'APPROVED';
    case 'IN_PROGRESS':
      return 'IN_PROGRESS';
    case 'FULFILLED':
      return 'FULFILLED';
    case 'REJECTED':
      return 'PENDING_APPROVAL';
    case 'CANCELLED':
      return 'CANCELLED';
    case 'SUPERSEDED':
      return 'SUPERSEDED';
    default:
      return 'DRAFT';
  }
}

@Component({
  selector: 'dmis-approval-status-tracker',
  standalone: true,
  imports: [
    CommonModule,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    DatePipe,
    DecimalPipe
  ],
  templateUrl: './dmis-approval-status-tracker.component.html',
  styleUrl: './dmis-approval-status-tracker.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DmisApprovalStatusTrackerComponent implements OnChanges {
  @Input() needsList: NeedsListResponse | null = null;
  @Input() horizon: HorizonType = 'A';
  @Output() sendReminder = new EventEmitter<void>();

  steps: TrackerStep[] = [];
  branch: TrackerBranch | null = null;
  detailsExpanded = false;
  readonly panelId = `detailsPanel-${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;

  get completedSteps(): TrackerStep[] {
    return this.steps.filter(s => s.state === 'completed' || s.state === 'active');
  }

  get isPendingApproval(): boolean {
    if (!this.needsList?.status) return false;
    return this.needsList.status === 'SUBMITTED' || this.needsList.status === 'UNDER_REVIEW';
  }

  get pendingApproverRole(): string {
    const explicitRole = this.needsList?.approval_summary?.approval?.approver_role;
    if (explicitRole) {
      return explicitRole;
    }

    const workflow = APPROVAL_WORKFLOWS[this.horizon];
    if (!workflow?.steps?.length) return 'Unknown';
    const tierMatch = this.approvalTier?.match(/(\d+)/);
    const tierValue = tierMatch ? Number(tierMatch[1]) : NaN;
    if (!Number.isFinite(tierValue)) return workflow.steps[0]?.role ?? 'Unknown';
    const index = Math.min(Math.max(tierValue - 1, 0), workflow.steps.length - 1);
    return workflow.steps[index]?.role ?? 'Unknown';
  }

  get approvalTier(): string | null {
    return this.needsList?.approval_summary?.approval?.tier ?? null;
  }

  get pendingHours(): number {
    if (!this.needsList?.submitted_at) return 0;
    const submitted = new Date(this.needsList.submitted_at).getTime();
    const now = Date.now();
    return (now - submitted) / (1000 * 60 * 60);
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['needsList']) {
      this.buildSteps();
    }
  }

  toggleDetails(): void {
    this.detailsExpanded = !this.detailsExpanded;
  }

  onSendReminder(): void {
    this.sendReminder.emit();
  }

  getStepIcon(step: TrackerStep): string {
    if (step.state === 'completed') return 'check_circle';
    return step.icon;
  }

  getBranchIcon(): string {
    if (!this.branch) return 'info';
    switch (this.branch.type) {
      case 'REJECTED': return 'cancel';
      case 'RETURNED': return 'undo';
      case 'CANCELLED': return 'block';
      case 'SUPERSEDED': return 'swap_horiz';
    }
  }

  getBranchLabel(): string {
    if (!this.branch) return '';
    switch (this.branch.type) {
      case 'REJECTED': return 'Rejected';
      case 'RETURNED': return 'Returned for Revision';
      case 'CANCELLED': return 'Cancelled';
      case 'SUPERSEDED': return 'Superseded';
    }
  }

  private buildSteps(): void {
    const nl = this.needsList;
    if (!nl) {
      this.steps = STEP_ORDER.map(id => ({
        ...STEP_META[id],
        id,
        state: 'pending' as TrackerStepState,
        timestamp: null,
        actor: null,
        comment: null
      }));
      this.branch = null;
      return;
    }

    const status = nl.status ?? 'DRAFT';
    const activeStep = mapStatusToStep(status);
    const isTerminated = status === 'CANCELLED' || status === 'SUPERSEDED';
    const displayStepId = isTerminated ? this.getTerminationStepId(nl) : (activeStep as TrackerStepId);
    const activeIndex = STEP_ORDER.indexOf(displayStepId);

    // Check for branch states
    this.branch = null;
    if (status === 'REJECTED') {
      this.branch = {
        type: 'REJECTED',
        reason: nl.reject_reason ?? null,
        actor: null,
        timestamp: null,
        fromStep: 'PENDING_APPROVAL'
      };
    } else if (status === 'RETURNED') {
      this.branch = {
        type: 'RETURNED',
        reason: nl.return_reason ?? null,
        actor: null,
        timestamp: null,
        fromStep: 'PENDING_APPROVAL'
      };
    } else if (status === 'CANCELLED') {
      this.branch = {
        type: 'CANCELLED',
        reason: null,
        actor: null,
        timestamp: null,
        fromStep: displayStepId
      };
    } else if (status === 'SUPERSEDED') {
      this.branch = {
        type: 'SUPERSEDED',
        reason: null,
        actor: null,
        timestamp: null,
        fromStep: displayStepId
      };
    }

    this.steps = STEP_ORDER.map((id, i) => {
      let state: TrackerStepState = 'pending';
      if (i < activeIndex) {
        state = 'completed';
      } else if (i === activeIndex) {
        if (status === 'REJECTED') {
          state = 'rejected';
        } else if (status === 'RETURNED') {
          // RETURNED goes back to DRAFT, so DRAFT is active again
          state = i === 0 ? 'active' : 'pending';
        } else if (isTerminated) {
          state = 'cancelled';
        } else {
          state = 'active';
        }
      }

      // For RETURNED, mark DRAFT as active and PENDING_APPROVAL as returned
      if (status === 'RETURNED' && id === 'PENDING_APPROVAL') {
        state = 'returned';
      }

      const { timestamp, actor, comment } = this.getStepAuditData(id, nl);

      return {
        id,
        ...STEP_META[id],
        state,
        timestamp,
        actor,
        comment
      };
    });
  }

  private getTerminationStepId(nl: NeedsListResponse): TrackerStepId {
    if (nl.approved_at) return 'APPROVED';
    if (nl.submitted_at) return 'PENDING_APPROVAL';
    return 'DRAFT';
  }

  private getStepAuditData(
    stepId: TrackerStepId,
    nl: NeedsListResponse
  ): { timestamp: string | null; actor: string | null; comment: string | null } {
    switch (stepId) {
      case 'DRAFT':
        return {
          timestamp: nl.created_at ?? null,
          actor: nl.created_by ?? null,
          comment: null
        };
      case 'PENDING_APPROVAL':
        return {
          timestamp: nl.submitted_at ?? null,
          actor: nl.submitted_by ?? null,
          comment: null
        };
      case 'APPROVED':
        return {
          timestamp: nl.approved_at ?? null,
          actor: nl.approved_by ?? null,
          comment: nl.review_comment ?? null
        };
      case 'IN_PROGRESS':
        return {
          timestamp: nl.approved_at ? nl.updated_at ?? null : null,
          actor: nl.updated_by ?? null,
          comment: null
        };
      case 'FULFILLED':
        return {
          timestamp: nl.updated_at ?? null,
          actor: nl.updated_by ?? null,
          comment: null
        };
      default:
        return { timestamp: null, actor: null, comment: null };
    }
  }
}
