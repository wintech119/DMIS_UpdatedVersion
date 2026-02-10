import { Injectable, inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { DmisErrorDialogComponent, ErrorDialogData } from '../shared/dmis-error-dialog/dmis-error-dialog.component';

@Injectable({ providedIn: 'root' })
export class DmisNotificationService {
  private snackBar = inject(MatSnackBar);
  private dialog = inject(MatDialog);

  showSuccess(message: string): void {
    this.snackBar.open(message, 'OK', {
      duration: 3000,
      panelClass: ['dmis-snackbar-success'],
      horizontalPosition: 'center',
      verticalPosition: 'bottom'
    });
  }

  showWarning(message: string): void {
    this.snackBar.open(message, 'OK', {
      duration: 5000,
      panelClass: ['dmis-snackbar-warning'],
      horizontalPosition: 'center',
      verticalPosition: 'bottom'
    });
  }

  showNetworkError(message: string, retryFn: () => void): void {
    const ref = this.snackBar.open(message, 'Retry', {
      duration: 8000,
      panelClass: ['dmis-snackbar-error'],
      horizontalPosition: 'center',
      verticalPosition: 'bottom'
    });

    ref.onAction().subscribe(() => {
      retryFn();
    });
  }

  showServerError(title: string, message: string, details?: string): void {
    const data: ErrorDialogData = {
      title,
      message,
      details,
      showReport: true
    };

    this.dialog.open(DmisErrorDialogComponent, {
      data,
      width: '480px',
      autoFocus: false
    });
  }

  showPartialFailure(message: string, retryFn: () => void): void {
    const ref = this.snackBar.open(message, 'Retry Failed', {
      duration: 0, // No auto-dismiss
      panelClass: ['dmis-snackbar-partial'],
      horizontalPosition: 'center',
      verticalPosition: 'bottom'
    });

    ref.onAction().subscribe(() => {
      retryFn();
    });
  }
}
