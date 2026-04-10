import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, forkJoin, of } from 'rxjs';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AppAccessService } from '../../core/app-access.service';
import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { OpsMetricStripComponent, OpsMetricStripItem } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';
import { OperationsService } from '../services/operations.service';
import {
  DispatchQueueResponse,
  OperationsTaskListResponse,
  PackageQueueResponse,
  RequestListResponse,
} from '../models/operations.model';
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

const EMPTY_REQUEST_FEED: RequestListResponse = { results: [] };
const EMPTY_PACKAGE_QUEUE: PackageQueueResponse = { results: [] };
const EMPTY_DISPATCH_QUEUE: DispatchQueueResponse = { results: [] };

function buildDashboardMetrics(options: {
  requestCount: number;
  draftCount: number;
  reviewCount: number;
  packageCount: number;
  consolidationCount: number;
  dispatchCount: number;
  highCount: number;
  urgentCount: number;
  openAssignments: number;
  unreadNotifications: number;
  canAccessEligibility: boolean;
}): DashboardMetric[] {
  const metrics: DashboardMetric[] = [
    {
      label: 'Open Requests',
      value: options.requestCount,
      note: options.canAccessEligibility
        ? `${options.draftCount} drafts, ${options.reviewCount} awaiting review`
        : `${options.draftCount} drafts ready for submission`,
      route: '/operations/relief-requests',
      icon: 'assignment',
      tone: 'review',
    },
    {
      label: 'Package Worklist',
      value: options.packageCount,
      note: `${options.highCount} high-urgency cases`,
      route: '/operations/package-fulfillment',
      icon: 'inventory_2',
      tone: 'draft',
    },
    {
      label: 'Consolidation',
      value: options.consolidationCount,
      note: options.consolidationCount === 0
        ? 'No staged packages awaiting legs'
        : `${options.consolidationCount} staged package${options.consolidationCount === 1 ? '' : 's'} with active legs`,
      route: '/operations/consolidation',
      icon: 'warehouse',
      tone: options.consolidationCount > 0 ? 'review' : 'muted',
    },
    {
      label: 'Dispatch Queue',
      value: options.dispatchCount,
      note: 'Handoffs waiting for transport sign-off',
      route: '/operations/dispatch',
      icon: 'local_shipping',
      tone: 'success',
    },
    {
      label: 'Action Items',
      value: options.openAssignments + options.unreadNotifications,
      note: `${options.openAssignments} live assignments, ${options.unreadNotifications} unread notifications`,
      route: '/operations/tasks',
      icon: 'notifications_active',
      tone: 'warning',
    },
  ];

  if (options.canAccessEligibility) {
    metrics.splice(1, 0, {
      label: 'Eligibility Queue',
      value: options.reviewCount,
      note: `${options.urgentCount} critical requests in line`,
      route: '/operations/eligibility-review',
      icon: 'verified_user',
      tone: 'warning',
    });
    metrics.pop();
  }

  return metrics;
}

function buildUnavailableDashboardMetrics(canAccessEligibility: boolean): DashboardMetric[] {
  const metrics: DashboardMetric[] = [
    {
      label: 'Open Requests',
      value: 0,
      note: 'Unavailable',
      route: '/operations/relief-requests',
      icon: 'assignment',
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
      label: 'Consolidation',
      value: 0,
      note: 'Unavailable',
      route: '/operations/consolidation',
      icon: 'warehouse',
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
    {
      label: 'Action Items',
      value: 0,
      note: 'Unavailable',
      route: '/operations/tasks',
      icon: 'notifications_active',
      tone: 'muted',
    },
  ];

  if (canAccessEligibility) {
    metrics.splice(1, 0, {
      label: 'Eligibility Queue',
      value: 0,
      note: 'Unavailable',
      route: '/operations/eligibility-review',
      icon: 'verified_user',
      tone: 'muted',
    });
    metrics.pop();
  }

  return metrics;
}

@Component({
  selector: 'app-operations-dashboard',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, OpsMetricStripComponent, OpsStatusChipComponent],
  templateUrl: './operations-dashboard.component.html',
  styleUrls: ['../operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OperationsDashboardComponent implements OnInit {
  private readonly auth = inject(AuthRbacService);
  private readonly appAccess = inject(AppAccessService);
  private readonly router = inject(Router);
  private readonly operationsService = inject(OperationsService);

  readonly loading = signal(true);
  readonly metrics = signal<DashboardMetric[]>([]);
  readonly priorityWork = signal<DashboardQueueItem[]>([]);
  readonly dashboardSubtitle = signal('Operations command center for relief requests, eligibility review, packing, and dispatch.');
  readonly recentTasks = signal<DashboardQueueItem[]>([]);

  readonly heroStats = computed(() => this.metrics().slice(0, 5));
  readonly heroMetricItems = computed<readonly OpsMetricStripItem[]>(() =>
    this.heroStats().map((metric) => ({
      label: metric.label,
      value: String(metric.value),
      hint: metric.note,
    })),
  );
  readonly canAccessEligibility = computed(() => this.appAccess.canAccessNavKey('operations.eligibility'));

  ngOnInit(): void {
    this.auth.ensureLoaded().subscribe(() => this.loadDashboard());
  }

  open(route: string): void {
    this.router.navigateByUrl(route);
  }

  queueTone(tone: DashboardQueueItem['tone']): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  private loadDashboard(): void {
    this.loading.set(true);
    const canAccessEligibility = this.canAccessEligibility();

    forkJoin({
      requests: this.operationsService.listRequests().pipe(catchError(() => of(EMPTY_REQUEST_FEED))),
      eligibility: canAccessEligibility
        ? this.operationsService.getEligibilityQueue().pipe(catchError(() => of({ results: [] })))
        : of({ results: [] }),
      packages: this.operationsService.getPackagesQueue().pipe(catchError(() => of(EMPTY_PACKAGE_QUEUE))),
      dispatch: this.operationsService.getDispatchQueue().pipe(catchError(() => of(EMPTY_DISPATCH_QUEUE))),
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
        const consolidationCount = packages.results.filter((row) => {
          const pkg = row.current_package;
          if (!pkg) {
            return false;
          }
          const mode = String(pkg.fulfillment_mode ?? '').toUpperCase();
          if (!mode || mode === 'DIRECT') {
            return false;
          }
          return (pkg.leg_summary?.total_legs ?? 0) > 0;
        }).length;
        const dispatchCount = dispatch.results.length;
        const urgentCount = requestRows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'C').length;
        const highCount = requestRows.filter((row) => String(row.urgency_ind ?? '').toUpperCase() === 'H').length;
        const openAssignments = tasks.queue_assignments.filter((task) => task.status === 'PENDING').length;
        const unreadNotifications = tasks.notifications.filter((task) => task.status === 'PENDING').length;

        this.dashboardSubtitle.set(
          `Operations command center for relief requests, ${canAccessEligibility ? 'eligibility review, ' : ''}packing, dispatch, and task coordination. `
          + `${openAssignments} live assignments and ${unreadNotifications} unread notifications.`,
        );

        this.metrics.set(buildDashboardMetrics({
          requestCount: requestRows.length,
          draftCount,
          reviewCount,
          packageCount,
          consolidationCount,
          dispatchCount,
          highCount,
          urgentCount,
          openAssignments,
          unreadNotifications,
          canAccessEligibility,
        }));

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
          ...(canAccessEligibility
            ? eligibility.results.slice(0, 1).map((row) => ({
              title: row.tracking_no ?? `Review ${row.reliefrqst_id}`,
              detail: row.agency_name ?? `Agency ${row.agency_id ?? 'pending'}`,
              status: `${formatOperationsRequestStatus(row.status_code)} | review`,
              tone: getOperationsRequestTone(row.status_code),
              age: formatOperationsAge(row.create_dtime ?? row.request_date),
              route: `/operations/eligibility-review/${row.reliefrqst_id}`,
              icon: 'fact_check',
            }))
            : []),
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
        this.metrics.set(buildUnavailableDashboardMetrics(canAccessEligibility));
        this.priorityWork.set([]);
        this.dashboardSubtitle.set(
          `Operations command center for relief requests, ${canAccessEligibility ? 'eligibility review, ' : ''}packing, dispatch, and task coordination.`,
        );
        this.loading.set(false);
      },
    });
  }
}
