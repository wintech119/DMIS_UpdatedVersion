import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { DonationLineItem } from '../models/needs-list.model';
import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';

@Component({
  selector: 'app-donation-allocation',
  standalone: true,
  imports: [
    DecimalPipe,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatProgressBarModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent
  ],
  templateUrl: './donation-allocation.component.html',
  styleUrl: './donation-allocation.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DonationAllocationComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly lines = signal<DonationLineItem[]>([]);
  readonly exporting = signal(false);

  private needsListId = '';

  readonly hasLines = computed(() => this.lines().length > 0);
  readonly totalRequired = computed(() =>
    this.lines().reduce((sum, l) => sum + l.required_qty, 0)
  );
  readonly totalAllocated = computed(() =>
    this.lines().reduce((sum, l) => sum + l.allocated_qty, 0)
  );

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.needsListId = String(params.get('id') || '').trim();
      if (!this.needsListId) {
        this.error.set(true);
        this.loading.set(false);
        return;
      }
      this.loadDonations();
    });
  }

  backToTracker(): void {
    this.router.navigate(['/replenishment/needs-list', this.needsListId, 'track']);
  }

  exportNeeds(format: 'csv' | 'pdf'): void {
    this.exporting.set(true);
    this.replenishmentService.exportDonationNeeds(this.needsListId, format).subscribe({
      next: (blob) => {
        this.exporting.set(false);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `donation_needs_${this.needsListId}.${format}`;
        a.click();
        URL.revokeObjectURL(url);
        this.notifications.showSuccess(`Donation needs exported as ${format.toUpperCase()}.`);
      },
      error: () => {
        this.exporting.set(false);
        this.notifications.showError('Failed to export donation needs.');
      }
    });
  }

  getAllocationPercent(line: DonationLineItem): number {
    if (!line.required_qty) return 0;
    return Number(((line.allocated_qty / line.required_qty) * 100).toFixed(1));
  }

  private loadDonations(): void {
    this.loading.set(true);
    this.error.set(false);

    this.replenishmentService.getDonations(this.needsListId).subscribe({
      next: (response) => {
        this.lines.set(response.lines || []);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
        this.notifications.showError('Failed to load donation needs.');
      }
    });
  }
}
