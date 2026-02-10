import { Component, Inject, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';

export interface ErrorDialogData {
  title: string;
  message: string;
  details?: string;
  showReport?: boolean;
}

@Component({
  selector: 'dmis-error-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatIconModule, MatButtonModule],
  template: `
    <div class="error-dialog">
      <div class="error-dialog-header">
        <mat-icon class="error-dialog-icon" aria-hidden="true">error</mat-icon>
        <h2 mat-dialog-title>{{ data.title }}</h2>
      </div>

      <mat-dialog-content>
        <p class="error-dialog-message">{{ data.message }}</p>

        <details *ngIf="data.details" class="error-details">
          <summary>Technical Details</summary>
          <pre class="error-details-content">{{ data.details }}</pre>
        </details>
      </mat-dialog-content>

      <mat-dialog-actions align="end">
        <button
          *ngIf="data.showReport"
          mat-stroked-button
          color="warn"
          (click)="reportIssue()"
        >
          <mat-icon>bug_report</mat-icon>
          Report Issue
        </button>
        <button mat-flat-button color="primary" mat-dialog-close>Close</button>
      </mat-dialog-actions>
    </div>
  `,
  styleUrl: './dmis-error-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DmisErrorDialogComponent {
  constructor(
    @Inject(MAT_DIALOG_DATA) public data: ErrorDialogData,
    private dialogRef: MatDialogRef<DmisErrorDialogComponent>
  ) {}

  reportIssue(): void {
    // Placeholder: log for now, future integration with issue tracker
    console.error('[DMIS Report]', {
      title: this.data.title,
      message: this.data.message,
      details: this.data.details,
      timestamp: new Date().toISOString()
    });
    this.dialogRef.close('reported');
  }
}
