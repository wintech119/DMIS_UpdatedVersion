import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { NeedsListDuplicateSummary } from '../../services/replenishment.service';

export interface NeedsListDuplicateWarningData {
  existingLists: NeedsListDuplicateSummary[];
  warehouseCount: number;
}

export type DuplicateWarningResult = 'view' | 'continue' | 'cancel';

@Component({
  selector: 'dmis-needs-list-duplicate-warning-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, DatePipe],
  templateUrl: './needs-list-duplicate-warning-dialog.component.html',
  styles: [`
    .duplicate-warning-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;
    }
    .warning-icon {
      color: var(--mat-sys-error);
      font-size: 28px;
      width: 28px;
      height: 28px;
    }
    .dialog-message {
      color: var(--mat-sys-on-surface-variant);
      font-size: 14px;
      line-height: 1.5;
      margin: 0 0 16px;
    }
    .conflicts-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .conflict-row {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding: 12px;
      border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 8px;
      background: var(--mat-sys-surface-container-low);
    }
    .conflict-info {
      flex: 1;
      min-width: 0;
    }
    .conflict-ref {
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 6px;
    }
    .ref-label {
      font-size: 12px;
      color: var(--mat-sys-on-surface-variant);
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
    .conflict-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .status-badge {
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
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
    .meta-item {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 12px;
      color: var(--mat-sys-on-surface-variant);
    }
    .meta-icon {
      font-size: 14px;
      width: 14px;
      height: 14px;
    }
    .row-view-btn {
      flex-shrink: 0;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class NeedsListDuplicateWarningDialogComponent {
  data = inject<NeedsListDuplicateWarningData>(MAT_DIALOG_DATA);
  private dialogRef = inject(MatDialogRef<NeedsListDuplicateWarningDialogComponent>);
  private router = inject(Router);

  viewItem(id: string): void {
    this.router.navigate(['/replenishment/needs-list', id, 'track']);
    this.dialogRef.close('view' as DuplicateWarningResult);
  }

  continue(): void {
    this.dialogRef.close('continue' as DuplicateWarningResult);
  }

  cancel(): void {
    this.dialogRef.close('cancel' as DuplicateWarningResult);
  }

  formatStatus(status: string): string {
    return status.replace(/_/g, ' ');
  }

  statusClass(status: string): string {
    return 'status-badge status-' + status.toLowerCase().replace(/_/g, '-');
  }
}
