import { Component, ChangeDetectionStrategy, inject } from '@angular/core';

import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';

export interface ConfirmDialogData {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
}

@Component({
  selector: 'dmis-confirm-dialog',
  standalone: true,
  imports: [MatDialogModule, MatIconModule, MatButtonModule],
  template: `
    <div class="confirm-dialog">
      <div class="confirm-dialog-header">
        <mat-icon class="confirm-dialog-icon" aria-hidden="true">help_outline</mat-icon>
        <h2 mat-dialog-title>{{ data.title }}</h2>
      </div>
      <mat-dialog-content>
        <p class="confirm-dialog-message">{{ data.message }}</p>
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-stroked-button [mat-dialog-close]="false">
          {{ data.cancelLabel || 'Cancel' }}
        </button>
        <button mat-flat-button color="warn" [mat-dialog-close]="true" cdkFocusInitial>
          {{ data.confirmLabel || 'Confirm' }}
        </button>
      </mat-dialog-actions>
    </div>
  `,
  styles: [`
    .confirm-dialog-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;
    }
    .confirm-dialog-icon {
      color: #f57f17;
      font-size: 28px;
      width: 28px;
      height: 28px;
    }
    .confirm-dialog-message {
      color: #475569;
      font-size: 14px;
      line-height: 1.5;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DmisConfirmDialogComponent {  data = inject<ConfirmDialogData>(MAT_DIALOG_DATA);

}
