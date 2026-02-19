import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { forkJoin, fromEvent, interval, of, Subscription } from 'rxjs';
import { catchError, startWith, switchMap } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { NeedsListFulfillmentLine, NeedsListResponse } from '../models/needs-list.model';
import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';

@Component({
  selector: 'app-needs-list-fulfillment-tracker',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatProgressSpinnerModule
  ],
  templateUrl: './needs-list-fulfillment-tracker.component.html',
  styleUrl: './needs-list-fulfillment-tracker.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class NeedsListFulfillmentTrackerComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly needsList = signal<NeedsListResponse | null>(null);
  readonly lines = signal<NeedsListFulfillmentLine[]>([]);
  readonly isOffline = signal(false);
  readonly isStale = signal(false);
  readonly lastSyncedAt = signal<string | null>(null);

  private needsListId = '';
  private dataVersion = '';
  private versionWatcherSubscription: Subscription | null = null;

  readonly mode = computed<'track' | 'history' | 'superseded'>(() => {
    const lastSegment = this.route.snapshot.url.at(-1)?.path || 'track';
    if (lastSegment === 'history' || lastSegment === 'superseded') {
      return lastSegment;
    }
    return 'track';
  });

  readonly pageTitle = computed(() => {
    switch (this.mode()) {
      case 'history':
        return 'Needs List History';
      case 'superseded':
        return 'Superseded Needs List';
      default:
        return 'Fulfillment Tracker';
    }
  });

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.needsListId = String(params.get('id') || '').trim();
      if (!this.needsListId) {
        this.stopVersionWatcher();
        this.error.set(true);
        this.loading.set(false);
        return;
      }
      this.dataVersion = '';
      this.isStale.set(false);
      this.loadData();
      this.startVersionWatcher();
    });

    fromEvent(window, 'offline')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.isOffline.set(true));
    fromEvent(window, 'online')
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.isOffline.set(false));
    this.isOffline.set(!navigator.onLine);
  }

  refreshData(): void {
    this.loadData();
  }

  backToSubmissions(): void {
    this.router.navigate(['/replenishment/my-submissions']);
  }

  goToReplacement(): void {
    const replacementId = this.needsList()?.superseded_by_needs_list_id;
    if (!replacementId) {
      return;
    }
    this.router.navigate(['/replenishment/needs-list', replacementId, 'review']);
  }

  private loadData(): void {
    this.loading.set(true);
    this.error.set(false);

    forkJoin({
      list: this.replenishmentService.getNeedsList(this.needsListId),
      sources: this.replenishmentService.getNeedsListFulfillmentSources(this.needsListId),
      version: this.replenishmentService.getNeedsListSummaryVersion(this.needsListId)
    }).subscribe({
      next: ({ list, sources, version }) => {
        this.needsList.set(list);
        this.lines.set(sources.lines || []);
        this.dataVersion = version.data_version;
        this.isStale.set(false);
        this.lastSyncedAt.set(new Date().toISOString());
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
        this.notifications.showError('Failed to load fulfillment details.');
      }
    });
  }

  private startVersionWatcher(): void {
    this.stopVersionWatcher();
    this.versionWatcherSubscription = interval(45000)
      .pipe(
        startWith(0),
        switchMap(() =>
          this.replenishmentService.getNeedsListSummaryVersion(this.needsListId).pipe(
            catchError(() => of(null))
          )
        ),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe((version) => {
        if (!version || !this.dataVersion) {
          return;
        }
        if (version.data_version !== this.dataVersion) {
          this.isStale.set(true);
        }
      });
  }

  private stopVersionWatcher(): void {
    this.versionWatcherSubscription?.unsubscribe();
    this.versionWatcherSubscription = null;
  }
}
