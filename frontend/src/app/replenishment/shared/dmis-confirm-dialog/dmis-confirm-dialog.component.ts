import { Component, ChangeDetectionStrategy, inject } from '@angular/core';

import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';

export interface ConfirmDialogDetail {
  label: string;
  value: string;
  icon?: string;
}

export interface ConfirmDialogData {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  icon?: string;
  iconColor?: string;
  confirmColor?: 'primary' | 'accent' | 'warn';
  details?: ConfirmDialogDetail[];
}

@Component({
  selector: 'dmis-confirm-dialog',
  standalone: true,
  imports: [MatDialogModule, MatIconModule, MatButtonModule],
  template: `
    <div class="confirm-dialog">
      <div class="confirm-dialog-header">
        <mat-icon
          class="confirm-dialog-icon"
          [style.color]="data.iconColor || null"
          aria-hidden="true">{{ data.icon || 'help_outline' }}</mat-icon>
        <h2 mat-dialog-title>{{ data.title }}</h2>
      </div>
      <mat-dialog-content>
        <p class="confirm-dialog-message">{{ data.message }}</p>
        @if (data.details?.length) {
          <div class="confirm-dialog-details">
            @for (detail of data.details; track detail.label) {
              <div class="detail-row">
                @if (detail.icon) {
                  <mat-icon class="detail-icon" aria-hidden="true">{{ detail.icon }}</mat-icon>
                }
                <span class="detail-label">{{ detail.label }}</span>
                <span class="detail-value">{{ detail.value }}</span>
              </div>
            }
          </div>
        }
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button matButton="outlined" [mat-dialog-close]="false">
          {{ data.cancelLabel || 'Cancel' }}
        </button>
        <button matButton="filled" class="confirm-action-btn" [color]="data.confirmColor || 'primary'" [mat-dialog-close]="true" cdkFocusInitial>
          <mat-icon aria-hidden="true">check_circle</mat-icon>
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
      color: var(--mat-sys-tertiary);
      font-size: 28px;
      width: 28px;
      height: 28px;
    }
    .confirm-dialog-message {
      color: var(--mat-sys-on-surface-variant);
      font-size: 14px;
      line-height: 1.5;
      margin: 0 0 4px;
    }
    .confirm-dialog-details {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 12px;
      padding: 12px;
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
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
    .confirm-action-btn {
      --mdc-filled-button-container-color: var(--mat-sys-primary);
      --mdc-filled-button-label-text-color: var(--mat-sys-on-primary);
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DmisConfirmDialogComponent {
  data = inject<ConfirmDialogData>(MAT_DIALOG_DATA);
}
