import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';

@Component({
  selector: 'dmis-empty-state',
  standalone: true,
  imports: [CommonModule, MatIconModule, MatButtonModule],
  template: `
    <div class="empty-state-container">
      <mat-icon class="empty-icon">{{ icon }}</mat-icon>
      <h3 class="empty-title">{{ title }}</h3>
      <p class="empty-message">{{ message }}</p>
      <button
        *ngIf="actionLabel"
        mat-stroked-button
        class="empty-action"
        (click)="action.emit()"
      >
        <mat-icon *ngIf="actionIcon">{{ actionIcon }}</mat-icon>
        {{ actionLabel }}
      </button>
    </div>
  `,
  styleUrl: './dmis-empty-state.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DmisEmptyStateComponent {
  @Input() icon = 'info';
  @Input() title = '';
  @Input() message = '';
  @Input() actionLabel = '';
  @Input() actionIcon = '';

  @Output() action = new EventEmitter<void>();
}
