import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

export type SkeletonVariant = 'stat-box' | 'warehouse-card' | 'table-row' | 'form-field' | 'summary-card' | 'text-line';

@Component({
  selector: 'dmis-skeleton-loader',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="skeleton-container" aria-label="Loading content" role="status" aria-live="polite">
      <ng-container *ngFor="let _ of countArray">
        <ng-container [ngSwitch]="variant">

          <!-- Stat box: 80px rounded box -->
          <div *ngSwitchCase="'stat-box'" class="skeleton skeleton-stat-box" aria-hidden="true">
            <div class="shimmer line-short"></div>
            <div class="shimmer line-wide"></div>
          </div>

          <!-- Warehouse card: header + 4 stat boxes -->
          <div *ngSwitchCase="'warehouse-card'" class="skeleton skeleton-warehouse-card" aria-hidden="true">
            <div class="shimmer line-header"></div>
            <div class="skeleton-stat-row">
              <div class="shimmer stat-placeholder"></div>
              <div class="shimmer stat-placeholder"></div>
              <div class="shimmer stat-placeholder"></div>
              <div class="shimmer stat-placeholder"></div>
            </div>
            <div class="shimmer line-wide"></div>
            <div class="shimmer line-medium"></div>
          </div>

          <!-- Table row: 6 column placeholders -->
          <div *ngSwitchCase="'table-row'" class="skeleton skeleton-table-row" aria-hidden="true">
            <div class="shimmer col-placeholder col-narrow"></div>
            <div class="shimmer col-placeholder col-wide"></div>
            <div class="shimmer col-placeholder col-medium"></div>
            <div class="shimmer col-placeholder col-medium"></div>
            <div class="shimmer col-placeholder col-narrow"></div>
            <div class="shimmer col-placeholder col-narrow"></div>
          </div>

          <!-- Form field: 56px field placeholder -->
          <div *ngSwitchCase="'form-field'" class="skeleton skeleton-form-field" aria-hidden="true">
            <div class="shimmer line-label"></div>
            <div class="shimmer field-box"></div>
          </div>

          <!-- Summary card: 3 text lines -->
          <div *ngSwitchCase="'summary-card'" class="skeleton skeleton-summary-card" aria-hidden="true">
            <div class="shimmer line-header"></div>
            <div class="shimmer line-wide"></div>
            <div class="shimmer line-medium"></div>
          </div>

          <!-- Text line: single 16px line -->
          <div *ngSwitchCase="'text-line'" class="skeleton skeleton-text-line" aria-hidden="true">
            <div class="shimmer line-wide"></div>
          </div>

        </ng-container>
      </ng-container>
    </div>
  `,
  styleUrl: './dmis-skeleton-loader.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DmisSkeletonLoaderComponent {
  @Input() variant: SkeletonVariant = 'text-line';
  @Input() count = 1;

  get countArray(): number[] {
    return Array.from({ length: this.count }, (_, i) => i);
  }
}
