import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { OperationsTask, OperationsTaskListResponse } from '../models/operations.model';
import {
  OperationsTone,
  OperationsTimeInStageTone,
  formatOperationsAge,
  formatOperationsRefreshedLabel,
  formatOperationsUrgency,
  formatTaskType,
  getOperationsTimeInStageTone,
  handleRovingRadioKeydown,
  getOperationsUrgencyTone,
  getTaskEntityRoute,
  getTaskTone,
  mapOperationsToneToChipTone,
} from '../operations-display.util';
import { OperationsService } from '../services/operations.service';
import { OpsMetricStripComponent, OpsMetricStripItem, OpsMetricTileTone } from '../shared/ops-metric-strip.component';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';

type TaskFilter = 'all' | 'PENDING' | 'IN_PROGRESS' | 'COMPLETED';

interface TaskMetric {
  label: string;
  value: number;
  note: string;
  /** Drives left-accent bar + pill badge on the strip tile (PFQ palette). */
  tileTone: OpsMetricTileTone;
  /** Short ALL-CAPS text shown inside the top-right badge pill. */
  badgeLabel: string;
  /** Status filter to activate when the tile is clicked (null = no-op). */
  filter: TaskFilter | null;
}

const EMPTY_TASK_FEED: OperationsTaskListResponse = {
  queue_assignments: [],
  notifications: [],
  results: [],
};

@Component({
  selector: 'app-task-center',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent,
    OpsMetricStripComponent,
    OpsStatusChipComponent,
  ],
  templateUrl: './task-center.component.html',
  styleUrls: ['../operations-shell.scss', './task-center.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TaskCenterComponent implements OnInit {
  private readonly operationsService = inject(OperationsService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly taskFeed = signal<OperationsTaskListResponse>(EMPTY_TASK_FEED);
  readonly activeFilter = signal<TaskFilter>('all');
  readonly searchTerm = signal('');
  readonly lastRefreshedAt = signal<number>(Date.now());

  readonly lastRefreshedLabel = computed(() => formatOperationsRefreshedLabel(this.lastRefreshedAt()));

  readonly filterOptions: readonly { label: string; value: TaskFilter }[] = [
    { label: 'All', value: 'all' },
    { label: 'Pending', value: 'PENDING' },
    { label: 'In Progress', value: 'IN_PROGRESS' },
    { label: 'Completed', value: 'COMPLETED' },
  ];

  readonly tasks = computed(() => this.taskFeed().results);

  readonly activeQueueCount = computed(() => this.tasks().length);

  readonly filteredTasks = computed(() => {
    const term = this.searchTerm().trim().toLowerCase();
    const filter = this.activeFilter();

    return this.tasks().filter((task) => {
      if (filter !== 'all' && task.status !== filter) {
        return false;
      }

      if (!term) {
        return true;
      }

      const haystack = [
        task.title,
        task.description,
        task.task_type,
        task.assigned_to,
        task.queue_code,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();

      return haystack.includes(term);
    });
  });

  readonly metrics = computed<TaskMetric[]>(() => {
    const feed = this.taskFeed();
    const rows = feed.results;
    return [
      {
        label: 'Assignments',
        value: feed.queue_assignments.length,
        note: 'Live queue work',
        tileTone: 'info',
        badgeLabel: 'ASSIGNED',
        filter: null,
      },
      {
        label: 'Notifications',
        value: feed.notifications.length,
        note: 'Workflow events',
        tileTone: 'drafts',
        badgeLabel: 'NOTICES',
        filter: null,
      },
      {
        label: 'Open',
        value: rows.filter((task) => task.status === 'PENDING').length,
        note: 'Unread or awaiting action',
        tileTone: 'awaiting',
        badgeLabel: 'PENDING',
        filter: 'PENDING',
      },
      {
        label: 'Completed',
        value: rows.filter((task) => task.status === 'COMPLETED').length,
        note: 'Read or closed',
        tileTone: 'ready',
        badgeLabel: 'DONE',
        filter: 'COMPLETED',
      },
    ];
  });

  readonly metricStrip = computed<readonly OpsMetricStripItem[]>(() =>
    this.metrics().map((metric) => ({
      label: metric.label,
      value: String(metric.value),
      hint: metric.note,
      interactive: metric.filter !== null,
      token: metric.tileTone,
      badge: { label: metric.badgeLabel, tone: metric.tileTone },
    })),
  );

  readonly formatTaskType = formatTaskType;
  readonly getTaskTone = getTaskTone;
  readonly formatOperationsAge = formatOperationsAge;
  readonly formatOperationsUrgency = formatOperationsUrgency;
  readonly getOperationsUrgencyTone = getOperationsUrgencyTone;

  ngOnInit(): void {
    this.loadTasks();
  }

  setFilter(filter: TaskFilter): void {
    this.activeFilter.set(filter);
  }

  onFilterKeydown(event: KeyboardEvent, index: number): void {
    handleRovingRadioKeydown(event, index, this.filterOptions, (value) => this.setFilter(value));
  }

  onSearch(value: string): void {
    this.searchTerm.set(value);
  }

  openTask(task: OperationsTask): void {
    const route = getTaskEntityRoute(task.related_entity_type, task.related_entity_id);
    if (route) {
      this.router.navigateByUrl(route);
    }
  }

  openMetricTile(item: OpsMetricStripItem): void {
    const filter = this.tileToneToFilter(item.token);
    if (filter === null) {
      return;
    }
    this.setFilter(filter);
  }

  private tileToneToFilter(tone: string | undefined): TaskFilter | null {
    switch (tone) {
      case 'awaiting': return 'PENDING';
      case 'ready': return 'COMPLETED';
      default: return null;
    }
  }

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
  }

  rowStageClass(task: OperationsTask): string {
    switch (task.status) {
      case 'PENDING':
        return 'ops-row--warning';
      case 'IN_PROGRESS':
        return 'ops-row--info';
      case 'COMPLETED':
        return 'ops-row--completed';
      default:
        return 'ops-row--neutral';
    }
  }

  stageLabel(task: OperationsTask): string {
    switch (task.status) {
      case 'PENDING':
        return 'Pending';
      case 'IN_PROGRESS':
        return 'In Progress';
      case 'COMPLETED':
        return 'Completed';
      default:
        return 'Open';
    }
  }

  stagePillClass(task: OperationsTask): string {
    switch (task.status) {
      case 'PENDING':
        return 'ops-stage-pill--warning';
      case 'IN_PROGRESS':
        return 'ops-stage-pill--info';
      case 'COMPLETED':
        return 'ops-stage-pill--completed';
      default:
        return 'ops-stage-pill--neutral';
    }
  }

  timePillClass(task: OperationsTask): string {
    return `ops-time-pill--${this.timePillTone(task)}`;
  }

  timePillTone(task: OperationsTask): OperationsTimeInStageTone {
    if (task.status === 'COMPLETED') {
      return 'fresh';
    }
    return getOperationsTimeInStageTone(task.created_at);
  }

  actionClass(task: OperationsTask): string {
    switch (task.status) {
      case 'PENDING':
        return 'ops-action--warning';
      case 'IN_PROGRESS':
        return 'ops-action--info';
      case 'COMPLETED':
        return 'ops-action--completed';
      default:
        return 'ops-action--neutral';
    }
  }

  actionLabel(task: OperationsTask): string {
    switch (task.status) {
      case 'PENDING':
        return 'Open task';
      case 'IN_PROGRESS':
        return 'Continue task';
      case 'COMPLETED':
        return 'View task';
      default:
        return 'Open task';
    }
  }

  assignmentLabel(task: OperationsTask): string | null {
    const assignee = task.assigned_to?.trim();
    if (assignee) {
      return assignee;
    }
    const queue = task.queue_code?.trim();
    if (queue) {
      return queue;
    }
    return null;
  }

  sourceLabel(task: OperationsTask): string {
    return task.source === 'QUEUE_ASSIGNMENT' ? 'Assignment' : 'Notification';
  }

  sourceTone(task: OperationsTask): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return task.source === 'QUEUE_ASSIGNMENT' ? 'info' : 'outline';
  }

  trackByTaskId(_index: number, task: OperationsTask): number {
    return task.id;
  }

  loadTasks(): void {
    this.loading.set(true);
    this.error.set(null);

    this.operationsService.getTasks().subscribe({
      next: (response) => {
        this.taskFeed.set(response);
        this.lastRefreshedAt.set(Date.now());
        this.loading.set(false);
      },
      error: (err) => {
        this.taskFeed.set(EMPTY_TASK_FEED);
        this.error.set(err?.message ?? 'Failed to load tasks');
        this.loading.set(false);
      },
    });
  }
}
