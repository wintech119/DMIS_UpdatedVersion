import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';

import {
  DmisReasonDialogComponent,
  DmisReasonDialogData,
  DmisReasonDialogResult,
} from '../../replenishment/shared/dmis-reason-dialog/dmis-reason-dialog.component';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { formatFulfillmentMode } from '../models/operations-status.util';
import { ConsolidationLeg } from '../models/operations.model';
import { OpsConsolidationPanelComponent } from '../shared/ops-consolidation-panel.component';
import { OpsSplitBannerComponent } from '../shared/ops-split-banner.component';
import { OperationsWorkspaceStateService } from '../services/operations-workspace-state.service';

@Component({
  selector: 'app-consolidation-package',
  standalone: true,
  imports: [
    MatButtonModule,
    MatIconModule,
    OpsConsolidationPanelComponent,
    OpsSplitBannerComponent,
  ],
  providers: [OperationsWorkspaceStateService],
  template: `
    <div class="ops-shell">
      <header class="ops-hero">
        <div class="ops-hero__lead">
          <button
            mat-icon-button
            aria-label="Back to package"
            (click)="goBack()">
            <mat-icon>arrow_back</mat-icon>
          </button>
          <div>
            <span class="ops-hero__eyebrow">Operations / Consolidation</span>
            <h1 class="ops-hero__title">
              {{ trackingNumber() || 'Staged package' }}
            </h1>
            <p class="ops-hero__copy">
              {{ fulfillmentModeLabel() }}
            </p>
          </div>
        </div>
        <div class="ops-hero__actions">
          <button
            matButton="outlined"
            (click)="state.refreshConsolidationLegs()"
            [disabled]="state.legsLoading()">
            <mat-icon aria-hidden="true">refresh</mat-icon>
            Refresh
          </button>
        </div>
      </header>

      <app-ops-split-banner
        [parent]="state.parentSplitInfo()"
        [children]="state.splitChildren()" />

      <app-ops-consolidation-panel
        [package]="state.packageDetail()?.package ?? null"
        [legs]="state.consolidationLegs()"
        [legsLoading]="state.legsLoading()"
        [legsError]="state.legsError()"
        (legClick)="openLeg($event)"
        (requestPartial)="onRequestPartial()"
        (approvePartial)="onApprovePartial()"
        (refresh)="state.refreshConsolidationLegs()" />
    </div>
  `,
  styles: [`
    :host { display: block; }

    .ops-shell {
      padding: 24px;
      max-width: 1100px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }

    .ops-hero {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
    }

    .ops-hero__lead {
      display: flex;
      align-items: flex-start;
      gap: 8px;
    }

    .ops-hero__eyebrow {
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-hero__title {
      margin: 4px 0 2px;
      font-size: clamp(1.6rem, 2.5vw, 2.2rem);
      font-weight: 800;
      letter-spacing: -0.04em;
      color: var(--ops-ink, #37352F);
    }

    .ops-hero__copy {
      margin: 0;
      color: var(--ops-ink-muted, #787774);
      font-size: 0.92rem;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConsolidationPackageComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly notifications = inject(DmisNotificationService);
  readonly state = inject(OperationsWorkspaceStateService);

  ngOnInit(): void {
    const raw = this.route.snapshot.paramMap.get('reliefpkgId');
    const reliefpkgId = Number(raw);
    if (reliefpkgId > 0) {
      this.state.loadConsolidationLegs(reliefpkgId);
    }
  }

  trackingNumber(): string | null {
    return this.state.packageDetail()?.package?.tracking_no ?? null;
  }

  fulfillmentModeLabel(): string {
    return formatFulfillmentMode(this.state.fulfillmentMode());
  }

  goBack(): void {
    const reliefpkgId = this.state.reliefpkgId();
    const reliefrqstId = this.state.reliefrqstId();
    if (reliefpkgId) {
      if (reliefrqstId > 0) {
        this.router.navigate(['/operations/package-fulfillment', reliefrqstId]);
        return;
      }
      this.router.navigate(['/operations/package-fulfillment']);
      return;
    }
    this.router.navigate(['/operations/package-fulfillment']);
  }

  openLeg(leg: ConsolidationLeg): void {
    const pkgId = this.state.reliefpkgId();
    if (!pkgId) {
      return;
    }
    this.router.navigate(['/operations/consolidation', pkgId, 'leg', leg.leg_id]);
  }

  onRequestPartial(): void {
    const dialogRef = this.dialog.open<
      DmisReasonDialogComponent,
      DmisReasonDialogData,
      DmisReasonDialogResult
    >(DmisReasonDialogComponent, {
      width: '520px',
      data: {
        title: 'Request partial release',
        actionLabel: 'Request release',
      },
    });

    dialogRef.afterClosed().subscribe((result) => {
      const reason = result?.reason?.trim();
      if (!reason) {
        return;
      }
      this.state.requestPartialRelease({ reason }).subscribe({
        next: () => this.notifications.showSuccess('Partial release requested.'),
        error: () => this.notifications.showError('Failed to request partial release.'),
      });
    });
  }

  onApprovePartial(): void {
    const dialogRef = this.dialog.open<
      DmisReasonDialogComponent,
      DmisReasonDialogData,
      DmisReasonDialogResult
    >(DmisReasonDialogComponent, {
      width: '520px',
      data: {
        title: 'Approve partial release',
        actionLabel: 'Approve',
      },
    });

    dialogRef.afterClosed().subscribe((result) => {
      const reason = result?.reason?.trim();
      if (!reason) {
        return;
      }
      this.state.approvePartialRelease({ approval_reason: reason }).subscribe({
        next: (response) => {
          this.notifications.showSuccess(
            response.released?.tracking_no
              ? `Partial release approved. Released: ${response.released.tracking_no}`
              : 'Partial release approved.',
          );
          this.state.refreshConsolidationLegs();
        },
        error: () => this.notifications.showError('Failed to approve partial release.'),
      });
    });
  }
}
