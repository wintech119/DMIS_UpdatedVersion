// UX-only gate. Backend re-validates duplicates at submission.
// This dialog must not be relied on for data integrity.
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { DatePipe } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { NeedsListDuplicateSummary } from '../../services/replenishment.service';

export interface DuplicateGuardDialogData {
  duplicates: NeedsListDuplicateSummary[];
  warehouseName: string;
  phase: string;
}

export type DuplicateGuardDialogResult =
  | { action: 'open'; needsListId: string }
  | { action: 'create-anyway' }
  | undefined;

@Component({
  selector: 'app-duplicate-guard-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, DatePipe],
  template: `
    <h2 mat-dialog-title>
      <mat-icon class="duplicate-icon" aria-hidden="true">assignment_late</mat-icon>
      Active needs list already exists
    </h2>
    <div mat-dialog-content>
      <p class="duplicate-intro">
        <strong>{{ data.warehouseName }}</strong> already has
        {{ data.duplicates.length }} active needs list{{ data.duplicates.length === 1 ? '' : 's' }}
        for phase <strong>{{ data.phase }}</strong>.
      </p>
      <ul class="duplicate-list" role="list">
        @for (dup of data.duplicates; track dup.needs_list_id) {
          <li class="duplicate-item">
            <div class="duplicate-header">
              <span class="duplicate-ref">{{ dup.needs_list_no }}</span>
              <span class="duplicate-status">{{ dup.status }}</span>
            </div>
            <div class="duplicate-meta">
              Created by {{ dup.created_by || 'unknown' }}
              · {{ dup.created_at | date:'medium' }}
              · {{ dup.items_count }} item{{ dup.items_count === 1 ? '' : 's' }}
            </div>
            <button
              matButton="outlined"
              type="button"
              class="duplicate-open-btn"
              (click)="openExisting(dup.needs_list_id)">
              Open this list
            </button>
          </li>
        }
      </ul>
      <p class="duplicate-footnote">
        Creating another may cause duplicate fulfillment. Continue only if necessary.
      </p>
    </div>
    <div mat-dialog-actions align="end">
      <button mat-button type="button" (click)="cancel()">Cancel</button>
      <button matButton="filled" color="warn" type="button" (click)="createAnyway()">
        Create anyway
      </button>
    </div>
  `,
  styles: [`
    .duplicate-icon {
      color: var(--color-warning, #d97706);
      vertical-align: middle;
      margin-right: 8px;
    }
    .duplicate-intro {
      margin: 0 0 12px;
    }
    .duplicate-list {
      list-style: none;
      padding: 0;
      margin: 0 0 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .duplicate-item {
      padding: 12px;
      border: 1px solid var(--color-border, #d6d3ce);
      border-radius: var(--radius-md, 8px);
      background: var(--color-surface-alt, #faf9f7);
    }
    .duplicate-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-weight: var(--weight-semibold, 600);
      margin-bottom: 4px;
    }
    .duplicate-status {
      font-size: var(--text-xs, 11px);
      padding: 2px 8px;
      border-radius: 999px;
      background: var(--color-bg-accent, #ecebe8);
      color: var(--color-text-primary, #37352f);
    }
    .duplicate-meta {
      font-size: var(--text-xs, 11px);
      color: var(--color-text-secondary, #666);
      margin-bottom: 8px;
    }
    .duplicate-footnote {
      font-size: var(--text-sm, 13px);
      color: var(--color-text-secondary, #666);
      font-style: italic;
    }
  `]
})
export class DuplicateGuardDialogComponent {
  private dialogRef = inject<MatDialogRef<DuplicateGuardDialogComponent, DuplicateGuardDialogResult>>(MatDialogRef);
  data = inject<DuplicateGuardDialogData>(MAT_DIALOG_DATA);

  openExisting(needsListId: string): void {
    this.dialogRef.close({ action: 'open', needsListId });
  }

  createAnyway(): void {
    this.dialogRef.close({ action: 'create-anyway' });
  }

  cancel(): void {
    this.dialogRef.close();
  }
}
