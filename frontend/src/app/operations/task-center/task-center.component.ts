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
  formatOperationsAge,
  formatOperationsUrgency,
  formatTaskType,
  getOperationsUrgencyTone,
  getTaskEntityRoute,
  getTaskTone,
  mapOperationsToneToChipTone,
} from '../operations-display.util';
import { OperationsService } from '../services/operations.service';
import { OpsStatusChipComponent } from '../shared/ops-status-chip.component';

type TaskFilter = 'all' | 'PENDING' | 'IN_PROGRESS' | 'COMPLETED';

interface TaskMetric {
  label: string;
  value: number;
  note: string;
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

  readonly filterOptions: readonly { label: string; value: TaskFilter }[] = [
    { label: 'All', value: 'all' },
    { label: 'Pending', value: 'PENDING' },
    { label: 'In Progress', value: 'IN_PROGRESS' },
    { label: 'Completed', value: 'COMPLETED' },
  ];

  readonly tasks = computed(() => this.taskFeed().results);

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
      { label: 'Assignments', value: feed.queue_assignments.length, note: 'Live queue work' },
      { label: 'Notifications', value: feed.notifications.length, note: 'Workflow events' },
      { label: 'Open', value: rows.filter((task) => task.status === 'PENDING').length, note: 'Unread or awaiting action' },
      { label: 'Completed', value: rows.filter((task) => task.status === 'COMPLETED').length, note: 'Read or closed' },
    ];
  });

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
    const targetIndex = this.getFilterTargetIndex(event.key, index);
    if (targetIndex === null) {
      return;
    }

    const target = this.filterOptions[targetIndex];
    if (!target) {
      return;
    }

    event.preventDefault();
    this.setFilter(target.value);

    const group = (event.currentTarget as HTMLElement | null)?.closest('[role="radiogroup"]');
    const buttons = Array.from(group?.querySelectorAll<HTMLElement>('[role="radio"]') ?? []);
    requestAnimationFrame(() => buttons[targetIndex]?.focus());
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

  chipTone(tone: OperationsTone): 'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline' {
    return mapOperationsToneToChipTone(tone);
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

  private getFilterTargetIndex(key: string, currentIndex: number): number | null {
    const lastIndex = this.filterOptions.length - 1;
    if (lastIndex < 0) {
      return null;
    }

    switch (key) {
      case 'ArrowRight':
      case 'ArrowDown':
        return currentIndex === lastIndex ? 0 : currentIndex + 1;
      case 'ArrowLeft':
      case 'ArrowUp':
        return currentIndex === 0 ? lastIndex : currentIndex - 1;
      case 'Home':
        return 0;
      case 'End':
        return lastIndex;
      default:
        return null;
    }
  }

  loadTasks(): void {
    this.loading.set(true);
    this.error.set(null);

    this.operationsService.getTasks().subscribe({
      next: (response) => {
        this.taskFeed.set(response);
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
