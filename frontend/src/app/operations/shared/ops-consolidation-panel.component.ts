import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { DmisSkeletonLoaderComponent } from '../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisEmptyStateComponent } from '../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import {
  formatConsolidationLegStatus,
  formatConsolidationStatus,
} from '../models/operations-status.util';
import {
  ConsolidationLeg,
  PackageLegSummary,
  PackageSummary,
} from '../models/operations.model';
import { OperationsWorkspaceStateService } from '../services/operations-workspace-state.service';
import {
  getOperationsConsolidationLegTone,
  getOperationsConsolidationStatusTone,
  mapOperationsToneToChipTone,
} from '../operations-display.util';
import { OpsMetricStripComponent, OpsMetricStripItem } from './ops-metric-strip.component';
import { OpsStatusChipComponent } from './ops-status-chip.component';

@Component({
  selector: 'app-ops-consolidation-panel',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    DmisSkeletonLoaderComponent,
    DmisEmptyStateComponent,
    OpsMetricStripComponent,
    OpsStatusChipComponent,
  ],
  template: `
    <section class="ops-card ops-consolidation" aria-label="Consolidation status">
      <header class="ops-consolidation__header">
        <div>
          <span class="ops-consolidation__eyebrow">Consolidation</span>
          <h3 class="ops-consolidation__title">Staging hub progress</h3>
          <p class="ops-consolidation__copy">
            Track staged inbound legs once the package has been committed.
          </p>
        </div>
        @if (consolidationStatus()) {
          <app-ops-status-chip
            [label]="consolidationStatusLabel()"
            [tone]="consolidationStatusTone()" />
        }
      </header>

      @if (showMetrics()) {
        <app-ops-metric-strip [items]="metrics()" />
      }

      @if (legsLoading()) {
        <dmis-skeleton-loader variant="table-row" />
      } @else if (legsError()) {
        <dmis-empty-state
          icon="error_outline"
          title="Could not load legs"
          [message]="legsError() || ''"
          actionLabel="Retry"
          actionIcon="refresh"
          (action)="refresh.emit()" />
      } @else if (!legs().length) {
        <div class="ops-consolidation__empty">
          <mat-icon aria-hidden="true">inventory_2</mat-icon>
          <div>
            <strong>No consolidation legs yet</strong>
            <p>Legs will appear here after the staged package is committed.</p>
          </div>
        </div>
      } @else {
        <ul class="ops-consolidation__legs" role="list">
          @for (leg of legs(); track leg.leg_id) {
            <li class="ops-row ops-row--interactive"
              role="button"
              tabindex="0"
              (click)="legClick.emit(leg)"
              (keydown.enter)="legClick.emit(leg)"
              (keydown.space)="legClick.emit(leg); $event.preventDefault()">
              <div class="ops-row__lead">
                <div class="ops-row__header">
                  <strong>Leg #{{ leg.leg_sequence }}</strong>
                  <app-ops-status-chip
                    [label]="legLabel(leg)"
                    [tone]="legTone(leg)" />
                </div>
                <div class="ops-row__meta">
                  <span>Source wh: {{ leg.source_warehouse_id }}</span>
                  @if (leg.driver_name) {
                    <span>Driver: {{ leg.driver_name }}</span>
                  }
                  @if (leg.vehicle_registration) {
                    <span>Vehicle: {{ leg.vehicle_registration }}</span>
                  }
                  @if (leg.estimated_arrival_dtime || leg.expected_arrival_at) {
                    <span>ETA: {{ leg.estimated_arrival_dtime || leg.expected_arrival_at }}</span>
                  }
                </div>
              </div>
              <div class="ops-row__actions">
                <mat-icon aria-hidden="true">chevron_right</mat-icon>
              </div>
            </li>
          }
        </ul>
      }

      <div class="ops-consolidation__actions">
        @if (canRequestPartial()) {
          <button
            type="button"
            matButton="outlined"
            (click)="requestPartial.emit()">
            <mat-icon aria-hidden="true">call_split</mat-icon>
            Request partial release
          </button>
        }
        @if (canApprovePartial()) {
          <button
            type="button"
            mat-flat-button
            color="primary"
            (click)="approvePartial.emit()">
            <mat-icon aria-hidden="true">check_circle</mat-icon>
            Approve partial release
          </button>
        }
      </div>
    </section>
  `,
  styles: [`
    :host { display: block; }

    .ops-card {
      background: var(--ops-card, #fbfaf7);
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: var(--ops-radius-md, 10px);
      padding: 22px 24px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    .ops-consolidation__header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }

    .ops-consolidation__eyebrow {
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-consolidation__title {
      margin: 4px 0 0;
      font-size: 1rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--ops-ink, #37352F);
    }

    .ops-consolidation__copy {
      margin: 4px 0 0;
      font-size: 0.82rem;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-consolidation__empty {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      padding: 12px 14px;
      border: 1px dashed var(--ops-outline, rgba(55, 53, 47, 0.12));
      border-radius: var(--ops-radius-md, 10px);
      background: color-mix(in srgb, var(--ops-surface, #ffffff) 88%, var(--ops-card, #fbfaf7));
      color: var(--ops-ink-muted, #787774);
    }

    .ops-consolidation__empty strong {
      display: block;
      font-size: 0.9rem;
      color: var(--ops-ink, #37352F);
    }

    .ops-consolidation__empty p {
      margin: 2px 0 0;
      font-size: 0.8rem;
    }

    .ops-consolidation__empty mat-icon {
      margin-top: 2px;
      color: var(--ops-ink-subtle, #908d87);
    }

    .ops-consolidation__legs {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .ops-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: var(--ops-radius-md, 10px);
      background: var(--ops-surface, #ffffff);
      cursor: pointer;
      transition: background-color 180ms ease, transform 180ms ease, border-color 180ms ease;
    }

    .ops-row:hover,
    .ops-row:focus-visible {
      background: var(--ops-emphasis, #eceae4);
      border-color: var(--ops-outline-strong, rgba(55, 53, 47, 0.14));
      transform: translateY(-1px);
    }

    .ops-row:focus-visible {
      outline: 2px solid #1565c0;
      outline-offset: 2px;
    }

    .ops-row__lead {
      flex: 1;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .ops-row__header {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }

    .ops-row__meta {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      font-size: 0.82rem;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-row__meta span + span::before {
      content: '·';
      margin-right: 10px;
      color: var(--ops-ink-subtle, #908d87);
    }

    .ops-row__actions mat-icon {
      color: var(--ops-ink-subtle, #908d87);
    }

    .ops-consolidation__actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }

    @media (prefers-reduced-motion: reduce) {
      .ops-row {
        transition: none;
        transform: none;
      }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsConsolidationPanelComponent {
  readonly state = inject(OperationsWorkspaceStateService);
  private readonly auth = inject(AuthRbacService);

  readonly package = input<PackageSummary | null>(null);
  readonly legs = input<readonly ConsolidationLeg[]>([]);
  readonly legsLoading = input(false);
  readonly legsError = input<string | null>(null);

  readonly legClick = output<ConsolidationLeg>();
  readonly requestPartial = output<void>();
  readonly approvePartial = output<void>();
  readonly refresh = output<void>();

  readonly consolidationStatus = computed(
    () => this.package()?.consolidation_status ?? null,
  );
  readonly consolidationStatusLabel = computed(() =>
    formatConsolidationStatus(this.consolidationStatus()),
  );
  readonly consolidationStatusTone = computed(() =>
    mapOperationsToneToChipTone(getOperationsConsolidationStatusTone(this.consolidationStatus())),
  );

  readonly legSummary = computed<PackageLegSummary | null>(
    () => this.package()?.leg_summary ?? null,
  );

  readonly metrics = computed<OpsMetricStripItem[]>(() => {
    const summary = this.legSummary();
    const total = summary?.total_legs ?? 0;
    const received = summary?.received_legs ?? 0;
    const inTransit = summary?.in_transit_legs ?? 0;
    const planned = summary?.planned_legs ?? 0;
    return [
      { label: 'Total legs', value: String(total) },
      { label: 'Planned', value: String(planned) },
      { label: 'In transit', value: String(inTransit) },
      { label: 'Received', value: `${received} / ${total}` },
    ];
  });
  readonly showMetrics = computed(() => {
    const summary = this.legSummary();
    if (!summary) {
      return false;
    }
    return (
      (summary.total_legs ?? 0) > 0
      || (summary.planned_legs ?? 0) > 0
      || (summary.in_transit_legs ?? 0) > 0
      || (summary.received_legs ?? 0) > 0
    );
  });

  readonly canRequestPartial = computed(() =>
    this.state.canRequestPartialRelease()
    && this.auth.hasPermission('operations.partial_release.request'),
  );
  readonly canApprovePartial = computed(() =>
    this.state.canApprovePartialRelease()
    && this.auth.hasPermission('operations.partial_release.approve'),
  );

  legLabel(leg: ConsolidationLeg): string {
    return leg.status_label || formatConsolidationLegStatus(leg.status_code);
  }

  legTone(leg: ConsolidationLeg): ReturnType<typeof mapOperationsToneToChipTone> {
    return mapOperationsToneToChipTone(getOperationsConsolidationLegTone(leg.status_code));
  }
}
