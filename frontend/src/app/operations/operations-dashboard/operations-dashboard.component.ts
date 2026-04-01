import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, forkJoin, of } from 'rxjs';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import { OperationsTaskListResponse } from '../models/operations.model';
import {
  formatOperationsAge,
  formatOperationsRequestStatus,
  formatOperationsUrgency,
  formatTaskType,
  getOperationsRequestTone,
  getTaskEntityRoute,
  getTaskTone,
  mapOperationsToneToChipTone,
} from '../operations-display.util';

interface DashboardMetric {
  label: string;
  value: number;
  note: string;
  route: string;
  icon: string;
  tone: 'draft' | 'review' | 'success' | 'warning' | 'danger' | 'muted';
}

interface DashboardQueueItem {
  title: string;
  detail: string;
  status: string;
  tone: 'draft' | 'review' | 'success' | 'warning' | 'danger' | 'muted';
  age: string;
  route: string;
  icon: string;
}

const EMPTY_TASK_FEED: OperationsTaskListResponse = {
  queue_assignments: [],
  notifications: [],
  results: [],
};

@Component({
  selector: 'app-operations-dashboard',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, OpsMetricStripComponent, OpsStatusChipComponent],
  templateUrl: './operations-dashboard.component.html',
  styleUrls: ['../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OperationsDashboardComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly operationsService = inject(OperationsService);

  readonly loading = signal(true);
  readonly metrics = signal<DashboardMetric[]>([]);
  readonly priorityWork = signal<DashboardQueueItem[]>([]);
  readonly dashboardSubtitle = signal('Operations command center for relief requests, eligibility review, packing, and dispatch.');
  readonly recentTasks = signal<DashboardQueueItem[]>([]);

  readonly heroStats = computed(() => this.metrics().slice(0, 4));
  readonly heroMetricItems = computed<readonly OpsMetricStripItem[]>(() =>
    this.heroStats().map((metric) => ({
      label: metric.label,
      value: String(metric.value),
      hint: metric.note,
    })),
  );

  ngOnInit(): void {
    this.loadDashboard();
  }

  open(route: string): void {
    this.router.navigateByUrl(route);
  }

  queueTone(tone: DashboardQueueItem['tone']): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  private loadDashboard(): void {
    this.loading.set(true);

    forkJoin({
      requests: this.operationsService.listRequests(),
      eligibility: this.operationsService.getEligibilityQueue(),
      packages: this.operationsService.getPackagesQueue(),
      dispatch: this.operationsService.getDispatchQueue(),
      tasks: this.operationsService.getTasks().pipe(catchError(() => of(EMPTY_TASK_FEED))),
    }).subscribe({
      next: ({ requests, eligibility, packages, dispatch, tasks }) => {
        const requestRows = [...requests.results].sort((left, right) =>
          new Date(right.create_dtime ?? right.request_date ?? 0).getTime() -
          new Date(left.create_dtime ?? left.request_date ?? 0).getTime(),
        );

        const draftCount = requestRows.filter((row) => row.status_code === 'DRAFT').length;
        const reviewCount = eligibility.results.length;
        const packageCount = packages.results.length;
        const dispatchCount = dispatch.results.length;
        const urgentCount = requestRows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'C').length;
        const highCount = requestRows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'H').length;
        const openAssignments = tasks.queue_assignments.filter((task) => task.status === 'PENDING').length;
        const unreadNotifications = tasks.notifications.filter((task) => task.status === 'PENDING').length;

        this.dashboardSubtitle.set(
          `Operations command center for relief requests, eligibility review, packing, and dispatch. `
          + `${openAssignments} live assignments and ${unreadNotifications} unread notifications.`,
        );

        this.metrics.set([
          {
            label: 'Open Requests',
            value: requestRows.length,
            note: `${draftCount} drafts, ${reviewCount} awaiting review`,
            route: '/operations/relief-requests',
            icon: 'assignment',
            tone: 'review',
          },
          {
            label: 'Eligibility Queue',
            value: reviewCount,
            note: `${urgentCount} critical requests in line`,
            route: '/operations/eligibility-review',
            icon: 'verified_user',
            tone: 'warning',
          },
          {
            label: 'Package Worklist',
            value: packageCount,
            note: `${highCount} high-urgency cases`,
            route: '/operations/package-fulfillment',
            icon: 'inventory_2',
            tone: 'draft',
          },
          {
            label: 'Dispatch Queue',
            value: dispatchCount,
            note: 'Handoffs waiting for transport sign-off',
            route: '/operations/dispatch',
            icon: 'local_shipping',
            tone: 'success',
          },
        ]);

        const priorityRequests = requestRows
          .filter((row) => row.status_code !== 'FULFILLED')
          .slice(0, 5)
          .map<DashboardQueueItem>((row) => ({
            title: row.tracking_no ?? `Request ${row.reliefrqst_id}`,
            detail: [row.agency_name ?? `Agency ${row.agency_id ?? 'pending'}`, row.event_name ?? 'No event set']
              .filter(Boolean)
              .join(' | '),
            status: `${formatOperationsRequestStatus(row.status_code)} | ${formatOperationsUrgency(row.urgency_ind)}`,
            tone: row.status_code === 'DRAFT' ? 'draft' : getOperationsRequestTone(row.status_code),
            age: formatOperationsAge(row.create_dtime ?? row.request_date),
            route: `/operations/relief-requests/${row.reliefrqst_id}`,
            icon: 'description',
          }));

        const queueHighlights: DashboardQueueItem[] = [
          ...priorityRequests,
          ...eligibility.results.slice(0, 1).map((row) => ({
            title: row.tracking_no ?? `Review ${row.reliefrqst_id}`,
            detail: row.agency_name ?? `Agency ${row.agency_id ?? 'pending'}`,
            status: `${formatOperationsRequestStatus(row.status_code)} | review`,
            tone: getOperationsRequestTone(row.status_code),
            age: formatOperationsAge(row.create_dtime ?? row.request_date),
            route: `/operations/eligibility-review/${row.reliefrqst_id}`,
            icon: 'fact_check',
          })),
        ];

        this.priorityWork.set(queueHighlights.slice(0, 6));

        const taskItems = (tasks.results ?? [])
          .filter((t) => t.status === 'PENDING' || t.status === 'IN_PROGRESS')
          .slice(0, 5)
          .map<DashboardQueueItem>((t) => ({
            title: t.title || formatTaskType(t.task_type),
            detail: t.description || 'Workflow event',
            status: `${t.source === 'QUEUE_ASSIGNMENT' ? 'Assignment' : 'Notification'} | ${formatTaskType(t.task_type)}`,
            tone: getTaskTone(t.task_type),
            age: formatOperationsAge(t.created_at),
            route: getTaskEntityRoute(t.related_entity_type, t.related_entity_id) ?? '/operations/tasks',
            icon: t.source === 'QUEUE_ASSIGNMENT' ? 'assignment_late' : 'notifications',
          }));
        this.recentTasks.set(taskItems);

        this.loading.set(false);
      },
      error: () => {
        this.metrics.set([
          {
            label: 'Open Requests',
            value: 0,
            note: 'Unavailable',
            route: '/operations/relief-requests',
            icon: 'assignment',
            tone: 'muted',
          },
          {
            label: 'Eligibility Queue',
            value: 0,
            note: 'Unavailable',
            route: '/operations/eligibility-review',
            icon: 'verified_user',
            tone: 'muted',
          },
          {
            label: 'Package Worklist',
            value: 0,
            note: 'Unavailable',
            route: '/operations/package-fulfillment',
            icon: 'inventory_2',
            tone: 'muted',
          },
          {
            label: 'Dispatch Queue',
            value: 0,
            note: 'Unavailable',
            route: '/operations/dispatch',
            icon: 'local_shipping',
            tone: 'muted',
          },
        ]);
        this.priorityWork.set([]);
        this.dashboardSubtitle.set('Operations command center for relief requests, eligibility review, packing, and dispatch.');
        this.loading.set(false);
      },
    });
  }
}
