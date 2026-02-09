import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  ChangeDetectorRef, inject
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule, DatePipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { DataFreshnessService } from '../../services/data-freshness.service';
import { DataFreshnessBannerState, FreshnessLevel } from '../../models/stock-status.model';

@Component({
  selector: 'dmis-data-freshness-banner',
  standalone: true,
  imports: [
    CommonModule,
    MatIconModule,
    MatButtonModule,
    MatTooltipModule,
    MatProgressBarModule,
    DatePipe
  ],
  templateUrl: './dmis-data-freshness-banner.component.html',
  styleUrl: './dmis-data-freshness-banner.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DmisDataFreshnessBannerComponent implements OnInit {
  private destroyRef = inject(DestroyRef);
  private cdr = inject(ChangeDetectorRef);
  private freshnessService = inject(DataFreshnessService);

  bannerState: DataFreshnessBannerState | null = null;
  isRefreshing = false;
  isExpanded = false;

  get isVisible(): boolean {
    return this.bannerState !== null && this.bannerState.overallState !== 'ALL_FRESH';
  }

  get isCritical(): boolean {
    return this.bannerState?.overallState === 'CRITICAL_STALE';
  }

  get isWarning(): boolean {
    return this.bannerState?.overallState === 'SOME_STALE';
  }

  ngOnInit(): void {
    this.freshnessService.getBannerState$().pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(state => {
      this.bannerState = state;
      this.cdr.markForCheck();
    });

    this.freshnessService.isRefreshing$().pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(refreshing => {
      this.isRefreshing = refreshing;
      this.cdr.markForCheck();
    });
  }

  toggleExpanded(): void {
    this.isExpanded = !this.isExpanded;
  }

  refreshData(): void {
    this.freshnessService.triggerRefresh();
  }

  getBannerIcon(): string {
    return this.isCritical ? 'error' : 'warning';
  }

  getBannerMessage(): string {
    if (!this.bannerState) return '';

    if (this.isCritical) {
      const names = this.bannerState.staleWarehouseNames.join(', ');
      const age = this.bannerState.maxAgeHours !== null
        ? `${this.bannerState.maxAgeHours.toFixed(1)} hours`
        : 'unknown duration';
      return `Critical: ${names} data is ${age} old. Burn rate calculations may be inaccurate.`;
    }

    return 'Warning: Some warehouse data is stale.';
  }

  getFreshnessIcon(level: FreshnessLevel): string {
    switch (level) {
      case 'HIGH': return 'check_circle';
      case 'MEDIUM': return 'warning';
      case 'LOW': return 'error';
    }
  }

  formatAgeHours(hours: number | null): string {
    if (hours === null) return 'Unknown';
    if (hours < 1) return `${Math.round(hours * 60)}m ago`;
    if (hours < 24) return `${hours.toFixed(1)}h ago`;
    const days = Math.floor(hours / 24);
    const remaining = Math.floor(hours % 24);
    return `${days}d ${remaining}h ago`;
  }
}
