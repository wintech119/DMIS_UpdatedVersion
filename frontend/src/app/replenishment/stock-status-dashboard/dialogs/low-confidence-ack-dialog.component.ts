// UX-only acknowledgement. Backend does not gate on confidence.
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';

export interface LowConfidenceAckDialogData {
  warehouseName: string;
  reasons: string[];
}

@Component({
  selector: 'app-low-confidence-ack-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MatDialogModule, MatButtonModule, MatIconModule],
  template: `
    <h2 mat-dialog-title>
      <mat-icon class="lowconf-icon" aria-hidden="true">error_outline</mat-icon>
      Low-confidence calculation
    </h2>
    <div mat-dialog-content>
      <p class="lowconf-intro">
        The stock calculation for <strong>{{ data.warehouseName }}</strong>
        has <strong>LOW</strong> confidence. Proceeding may produce a needs list
        based on incomplete or stale data.
      </p>
      @if (data.reasons.length > 0) {
        <div class="lowconf-reasons">
          <h3 class="lowconf-reasons-title">Reasons</h3>
          <ul>
            @for (reason of data.reasons; track reason) {
              <li>{{ reason }}</li>
            }
          </ul>
        </div>
      }
      <p class="lowconf-recommendation">
        Consider refreshing inventory data before generating a needs list.
      </p>
    </div>
    <div mat-dialog-actions align="end">
      <button mat-button type="button" (click)="cancel()">Cancel</button>
      <button matButton="filled" color="warn" type="button" (click)="proceed()">
        Proceed anyway
      </button>
    </div>
  `,
  styles: [`
    .lowconf-icon {
      color: var(--color-warning, #d97706);
      vertical-align: middle;
      margin-right: 8px;
    }
    .lowconf-intro {
      margin: 0 0 12px;
    }
    .lowconf-reasons {
      background: var(--color-surface-alt, #faf9f7);
      padding: 12px 16px;
      border-radius: var(--radius-md, 8px);
      margin: 0 0 16px;
    }
    .lowconf-reasons-title {
      margin: 0 0 8px;
      font-size: var(--text-sm, 13px);
      font-weight: var(--weight-semibold, 600);
      color: var(--color-text-primary, #37352f);
    }
    .lowconf-reasons ul {
      margin: 0;
      padding-left: 18px;
      color: var(--color-text-secondary, #666);
      font-size: var(--text-sm, 13px);
    }
    .lowconf-recommendation {
      font-size: var(--text-sm, 13px);
      color: var(--color-text-secondary, #666);
      font-style: italic;
      margin: 0;
    }
  `]
})
export class LowConfidenceAckDialogComponent {
  private dialogRef = inject<MatDialogRef<LowConfidenceAckDialogComponent, boolean>>(MatDialogRef);
  data = inject<LowConfidenceAckDialogData>(MAT_DIALOG_DATA);

  proceed(): void {
    this.dialogRef.close(true);
  }

  cancel(): void {
    this.dialogRef.close(false);
  }
}
