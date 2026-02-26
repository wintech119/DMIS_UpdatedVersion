import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { NeedsListDuplicateSummary } from '../../services/replenishment.service';
import { getNeedsListActionTarget, NeedsListActionStatus } from '../needs-list-action.util';

export interface NeedsListDuplicateWarningData {
  existingLists: NeedsListDuplicateSummary[];
  warehouseCount: number;
  enforced?: boolean;
}

export type DuplicateWarningResult = 'view' | 'continue' | 'cancel';

@Component({
  selector: 'dmis-needs-list-duplicate-warning-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, DatePipe],
  templateUrl: './needs-list-duplicate-warning-dialog.component.html',
  styles: [`
    .duplicate-dialog-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;
    }
    .warning-icon-wrapper {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: #fff7ed;
      flex-shrink: 0;
    }
    .duplicate-dialog-icon {
      color: #ea580c;
      font-size: 24px;
      width: 24px;
      height: 24px;
    }
    h2[mat-dialog-title] {
      margin: 0;
      font-size: 1.125rem;
      font-weight: 600;
      color: #1f2937;
    }
    .duplicate-dialog-message {
      color: #6b7280;
      font-size: 14px;
      line-height: 1.5;
      margin: 0 0 16px;
    }
    .conflicts-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .conflict-card {
      padding: 12px;
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
    }
    .conflict-card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 8px;
    }
    .ref-link {
      font-size: 14px;
      font-weight: 600;
      color: var(--mat-sys-primary);
      background: none;
      border: none;
      cursor: pointer;
      padding: 0;
      text-decoration: underline;
    }
    .ref-link:hover {
      opacity: 0.8;
    }
    .status-badge {
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      white-space: nowrap;
    }
    .status-draft, .status-modified {
      background: var(--mat-sys-secondary-container);
      color: var(--mat-sys-on-secondary-container);
    }
    .status-submitted, .status-pending-approval, .status-under-review, .status-pending {
      background: #fff3e0;
      color: #e65100;
    }
    .status-approved, .status-in-progress, .status-in-preparation,
    .status-returned, .status-escalated {
      background: var(--mat-sys-primary-container);
      color: var(--mat-sys-on-primary-container);
    }
    .conflict-card-body {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .detail-row {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
    }
    .detail-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      color: #6b7280;
      flex-shrink: 0;
    }
    .detail-label {
      color: #6b7280;
      font-weight: 500;
      white-space: nowrap;
    }
    .detail-value {
      color: #1f2937;
      font-weight: 600;
      margin-left: auto;
    }
    .conflict-card-action {
      display: flex;
      justify-content: flex-end;
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid #e5e7eb;
    }
    .warning-note {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      margin-top: 16px;
      padding: 10px 12px;
      background: #fffbeb;
      border: 1px solid #fde68a;
      border-radius: 8px;
      font-size: 12px;
      color: #92400e;
      line-height: 1.5;
    }
    .warning-note--blocked {
      background: #fef2f2;
      border-color: #fecaca;
      color: #991b1b;
    }
    .note-icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      flex-shrink: 0;
      margin-top: 1px;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class NeedsListDuplicateWarningDialogComponent {
  data = inject<NeedsListDuplicateWarningData>(MAT_DIALOG_DATA);
  private dialogRef = inject(MatDialogRef<NeedsListDuplicateWarningDialogComponent>);
  private router = inject(Router);

  viewItem(id: string, status?: string): void {
    const target = getNeedsListActionTarget(id, (status || 'DRAFT') as NeedsListActionStatus);
    this.router.navigate(target.commands, { queryParams: target.queryParams });
    this.dialogRef.close('view' as DuplicateWarningResult);
  }

  continue(): void {
    this.dialogRef.close('continue' as DuplicateWarningResult);
  }

  cancel(): void {
    this.dialogRef.close('cancel' as DuplicateWarningResult);
  }

  actionLabel(status?: string): string {
    if (this.data.enforced) {
      const normalized = String(status || '').trim().toUpperCase();
      if (
        normalized === 'APPROVED' ||
        normalized === 'IN_PROGRESS' ||
        normalized === 'IN_PREPARATION' ||
        normalized === 'DISPATCHED' ||
        normalized === 'RECEIVED'
      ) {
        return 'Track Fulfillment';
      }
    }

    const target = getNeedsListActionTarget('placeholder', (status || 'DRAFT') as NeedsListActionStatus);
    return target.label || 'View';
  }

  formatStatus(status: string): string {
    return status.replace(/_/g, ' ');
  }

  statusClass(status: string): string {
    return 'status-badge status-' + status.toLowerCase().replace(/_/g, '-');
  }
}
