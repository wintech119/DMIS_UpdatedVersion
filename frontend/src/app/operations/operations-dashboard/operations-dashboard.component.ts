import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { MonoTypeOperatorFunction, catchError, forkJoin, of, throwError } from 'rxjs';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AppAccessService } from '../../core/app-access.service';
import {
  isAuthSensitiveApiResponse,
  isExpiredOrInvalidTokenResponse,
  isInsufficientPermissionsResponse,
} from '../../core/auth-session.service';
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

interface DashboardLaneAccess {
  reliefRequests: boolean;
  eligibility: boolean;
  fulfillment: boolean;
  dispatch: boolean;
  tasks: boolean;
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
  laneAccess: DashboardLaneAccess;
}): DashboardMetric[] {
  const metrics: DashboardMetric[] = [
    {
      label: 'Open Requests',
      value: options.laneAccess.reliefRequests ? options.requestCount : 0,
      note: options.laneAccess.reliefRequests
        ? options.canAccessEligibility
          ? `${options.draftCount} drafts, ${options.reviewCount} awaiting review`
          : `${options.draftCount} drafts ready for submission`
        : 'Not available to your role.',
      route: '/operations/relief-requests',
      icon: 'assignment',
      tone: options.laneAccess.reliefRequests ? 'review' : 'muted',
    },
    {
      label: 'Package Worklist',
      value: options.laneAccess.fulfillment ? options.packageCount : 0,
      note: options.laneAccess.fulfillment
        ? `${options.highCount} high-urgency cases`
        : 'Not available to your role.',
      route: '/operations/package-fulfillment',
      icon: 'inventory_2',
      tone: options.laneAccess.fulfillment ? 'draft' : 'muted',
    },
    {
      label: 'Consolidation',
      value: options.laneAccess.fulfillment ? options.consolidationCount : 0,
      note: options.laneAccess.fulfillment
        ? options.consolidationCount === 0
          ? 'No staged packages awaiting legs'
          : `${options.consolidationCount} staged package${options.consolidationCount === 1 ? '' : 's'} with active legs`
        : 'Not available to your role.',
      route: '/operations/consolidation',
      icon: 'warehouse',
      tone: !options.laneAccess.fulfillment
        ? 'muted'
        : options.consolidationCount > 0
          ? 'review'
          : 'muted',
    },
    {
      label: 'Dispatch Queue',
      value: options.laneAccess.dispatch ? options.dispatchCount : 0,
      note: options.laneAccess.dispatch
        ? 'Handoffs waiting for transport sign-off'
        : 'Not available to your role.',
      route: '/operations/dispatch',
      icon: 'local_shipping',
      tone: options.laneAccess.dispatch ? 'success' : 'muted',
    },
    {
      label: 'Action Items',
      value: options.laneAccess.tasks ? options.openAssignments + options.unreadNotifications : 0,
      note: options.laneAccess.tasks
        ? `${options.openAssignments} live assignments, ${options.unreadNotifications} unread notifications`
        : 'Not available to your role.',
      route: '/operations/tasks',
      icon: 'notifications_active',
      tone: options.laneAccess.tasks ? 'warning' : 'muted',
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

function buildDashboardLaneAccessNotice(laneAccess: DashboardLaneAccess): string | null {
  const hiddenLanes: string[] = [];
  if (!laneAccess.reliefRequests) {
    hiddenLanes.push('relief requests');
  }
  if (!laneAccess.eligibility) {
    hiddenLanes.push('eligibility review');
  }
  if (!laneAccess.fulfillment) {
    hiddenLanes.push('package fulfillment');
  }
  if (!laneAccess.dispatch) {
    hiddenLanes.push('dispatch');
  }
  if (!laneAccess.tasks) {
    hiddenLanes.push('task center');
  }

  if (hiddenLanes.length === 0) {
    return null;
  }

  return `This dashboard is showing only the operations lanes available to your account. Hidden lanes: ${hiddenLanes.join(', ')}.`;
}

function describeDashboardAccessFailure(error: HttpErrorResponse): string {
  if (isInsufficientPermissionsResponse(error)) {
    return 'DMIS could not load the operations dashboard because the backend denied one or more feeds for this signed-in account. Use a route your role is allowed to access, or contact an administrator if this should be available.';
  }
  if (isExpiredOrInvalidTokenResponse(error)) {
    return 'Your DMIS sign-in session is no longer valid. Redirecting you to sign in again.';
  }
  return 'DMIS could not complete the dashboard authentication checks for this route.';
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
  private readonly appAccess = inject(AppAccessService);
  private readonly router = inject(Router);
  private readonly operationsService = inject(OperationsService);

  readonly loading = signal(true);
  readonly loadError = signal<string | null>(null);
  readonly laneAccessNotice = signal<string | null>(null);
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
  readonly canAccessReliefRequests = computed(() => this.appAccess.canAccessNavKey('operations.relief-requests'));
  readonly canAccessEligibility = computed(() => this.appAccess.canAccessNavKey('operations.eligibility'));
  readonly canAccessFulfillment = computed(() => this.appAccess.canAccessNavKey('operations.fulfillment'));
  readonly canAccessDispatch = computed(() => this.appAccess.canAccessNavKey('operations.dispatch'));
  readonly canAccessTasks = computed(() => this.appAccess.canAccessNavKey('operations.tasks'));
  readonly priorityWorkEmptyTitle = computed(() =>
    this.canAccessReliefRequests() ? 'No active work items' : 'Relief request queues are hidden for this account.',
  );
  readonly priorityWorkEmptyCopy = computed(() =>
    this.canAccessReliefRequests()
      ? 'The current queues are empty or the backend is unavailable.'
      : 'This dashboard stays available for your other operations lanes, but relief-request queue access is not granted.',
  );
  readonly recentTasksEmptyTitle = computed(() =>
    this.canAccessTasks() ? 'No pending tasks' : 'Tasks are hidden for this account.',
  );
  readonly recentTasksEmptyCopy = computed(() =>
    this.canAccessTasks()
      ? 'Workflow notifications will appear here as operations progress.'
      : 'This account can open other operations lanes, but task-center access is not granted.',
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
    this.loadError.set(null);
    const laneAccess: DashboardLaneAccess = {
      reliefRequests: this.canAccessReliefRequests(),
      eligibility: this.canAccessEligibility(),
      fulfillment: this.canAccessFulfillment(),
      dispatch: this.canAccessDispatch(),
      tasks: this.canAccessTasks(),
    };
    const canAccessEligibility = laneAccess.eligibility;
    this.laneAccessNotice.set(buildDashboardLaneAccessNotice(laneAccess));

    forkJoin({
      requests: laneAccess.reliefRequests
        ? this.operationsService.listRequests().pipe(this.recoverDashboardFeed(EMPTY_REQUEST_FEED))
        : of(EMPTY_REQUEST_FEED),
      eligibility: canAccessEligibility
        ? this.operationsService.getEligibilityQueue().pipe(this.recoverDashboardFeed({ results: [] }))
        : of({ results: [] }),
      packages: laneAccess.fulfillment
        ? this.operationsService.getPackagesQueue().pipe(this.recoverDashboardFeed(EMPTY_PACKAGE_QUEUE))
        : of(EMPTY_PACKAGE_QUEUE),
      dispatch: laneAccess.dispatch
        ? this.operationsService.getDispatchQueue().pipe(this.recoverDashboardFeed(EMPTY_DISPATCH_QUEUE))
        : of(EMPTY_DISPATCH_QUEUE),
      tasks: laneAccess.tasks
        ? this.operationsService.getTasks().pipe(this.recoverDashboardFeed(EMPTY_TASK_FEED))
        : of(EMPTY_TASK_FEED),
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
          laneAccess,
        }));

        const priorityRequests = laneAccess.reliefRequests
          ? requestRows
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
            }))
          : [];

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
      error: (error: unknown) => {
        this.metrics.set(buildUnavailableDashboardMetrics(canAccessEligibility));
        this.priorityWork.set([]);
        this.recentTasks.set([]);
        this.loadError.set(
          error instanceof HttpErrorResponse && isAuthSensitiveApiResponse(error)
            ? describeDashboardAccessFailure(error)
            : 'DMIS could not load the operations dashboard right now.',
        );
        this.dashboardSubtitle.set(
          `Operations command center for relief requests, ${canAccessEligibility ? 'eligibility review, ' : ''}packing, dispatch, and task coordination.`,
        );
        this.loading.set(false);
      },
    });
  }

  private recoverDashboardFeed<T>(fallback: T): MonoTypeOperatorFunction<T> {
    return catchError((error: unknown) => {
      if (isAuthSensitiveApiResponse(error)) {
        return throwError(() => error);
      }
      return of(fallback);
    });
  }
}
