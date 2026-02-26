import { Component, ChangeDetectionStrategy, inject } from '@angular/core';

import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';

export interface SuccessDialogDetail {
  label: string;
  value: string;
  icon?: string;
}

export interface SuccessDialogAction {
  label: string;
  value: string;
  icon?: string;
  primary?: boolean;
}

export interface SuccessDialogData {
  title: string;
  message: string;
  details?: SuccessDialogDetail[];
  actions?: SuccessDialogAction[];
}

@Component({
  selector: 'dmis-success-dialog',
  standalone: true,
  imports: [MatDialogModule, MatIconModule, MatButtonModule],
  template: `
    <div class="success-dialog">
      <div class="success-dialog-header">
        <div class="success-icon-wrapper">
          <mat-icon class="success-dialog-icon" aria-hidden="true">check_circle</mat-icon>
        </div>
        <h2 mat-dialog-title>{{ data.title }}</h2>
      </div>
      <mat-dialog-content>
        <p class="success-dialog-message">{{ data.message }}</p>
        @if (data.details?.length) {
          <div class="success-dialog-details">
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
        @if (data.actions?.length) {
          @for (action of data.actions; track action.value) {
            @if (action.primary) {
              <button matButton="filled" color="primary" [mat-dialog-close]="action.value" cdkFocusInitial>
                @if (action.icon) {
                  <mat-icon aria-hidden="true">{{ action.icon }}</mat-icon>
                }
                {{ action.label }}
              </button>
            } @else {
              <button matButton="outlined" [mat-dialog-close]="action.value">
                @if (action.icon) {
                  <mat-icon aria-hidden="true">{{ action.icon }}</mat-icon>
                }
                {{ action.label }}
              </button>
            }
          }
        } @else {
          <button matButton="filled" color="primary" mat-dialog-close="close" cdkFocusInitial>
            Done
          </button>
        }
      </mat-dialog-actions>
    </div>
  `,
  styles: [`
    .success-dialog-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 8px;
    }
    .success-icon-wrapper {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 40px;
      height: 40px;
      border-radius: 50%;
      background: #f0fdf4;
      flex-shrink: 0;
    }
    .success-dialog-icon {
      color: #16a34a;
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
    .success-dialog-message {
      color: #6b7280;
      font-size: 14px;
      line-height: 1.5;
      margin: 0 0 4px;
    }
    .success-dialog-details {
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
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DmisSuccessDialogComponent {
  data = inject<SuccessDialogData>(MAT_DIALOG_DATA);
}
