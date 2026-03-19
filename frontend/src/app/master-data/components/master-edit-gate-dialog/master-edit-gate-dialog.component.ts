import { Component, ChangeDetectionStrategy, inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';

export interface EditGateDialogData {
  /** Record display name, e.g. "Rice - 25kg Bag" */
  recordName: string;
  /** Table display name, e.g. "Items" */
  tableName: string;
  /** Table icon from config */
  tableIcon: string;
  /** Warning text shown in the alert banner */
  warningText: string;
  /** Whether this is a governed catalog table (IFRC families/references) */
  isGoverned: boolean;
  /** Human-readable labels of fields that cannot be edited */
  lockedFields: string[];
  /** Module names that depend on this table */
  impactModules: string[];
  /** Short description of change propagation */
  impactDescription: string;
}

@Component({
  selector: 'dmis-master-edit-gate-dialog',
  standalone: true,
  imports: [MatDialogModule, MatIconModule, MatButtonModule, MatChipsModule],
  template: `
    <div class="gate-dialog">
      <!-- Header -->
      <div class="gate-header">
        <div class="gate-header__badge">
          <mat-icon class="gate-header__icon" aria-hidden="true">
            {{ data.isGoverned ? 'verified_user' : 'edit_note' }}
          </mat-icon>
        </div>
        <div class="gate-header__text">
          <span class="gate-header__label">
            {{ data.isGoverned ? 'GOVERNANCE PROTOCOL' : 'EDIT CONFIRMATION' }}
          </span>
          <button mat-icon-button [mat-dialog-close]="false" class="gate-close-btn"
            aria-label="Close dialog">
            <mat-icon>close</mat-icon>
          </button>
        </div>
        <h2 id="gate-dialog-title" mat-dialog-title class="gate-title">
          {{ data.isGoverned ? 'Governed Catalog Edit' : 'Edit ' + data.tableName }}
        </h2>
        <p class="gate-subtitle">{{ data.recordName }}</p>
      </div>

      <mat-dialog-content class="gate-body">
        <!-- Warning Banner -->
        <div class="gate-warning" role="alert">
          <div class="gate-warning__icon-wrap">
            <mat-icon class="gate-warning__icon" aria-hidden="true">warning_amber</mat-icon>
          </div>
          <div class="gate-warning__content">
            <span class="gate-warning__title">Review Policy Restrictions</span>
            <span class="gate-warning__text">{{ data.warningText }}</span>
          </div>
        </div>

        <!-- Impact Card -->
        @if (data.impactModules.length > 0) {
          <div class="gate-card">
            <div class="gate-card__header">
              <mat-icon class="gate-card__icon" aria-hidden="true">hub</mat-icon>
              <span class="gate-card__title">Impact</span>
            </div>
            <div class="gate-card__tabs">
              <span class="gate-card__tab">Downstream Deps</span>
              <span class="gate-card__tab gate-card__tab--active">
                {{ data.impactModules.length }}
                {{ data.impactModules.length === 1 ? 'Module' : 'Modules' }}
              </span>
            </div>
            <div class="gate-card__module-list">
              @for (mod of data.impactModules; track mod) {
                <span class="gate-module-chip">
                  <mat-icon class="gate-module-chip__icon" aria-hidden="true">
                    {{ getModuleIcon(mod) }}
                  </mat-icon>
                  {{ mod }}
                </span>
              }
            </div>
            <p class="gate-card__description">{{ data.impactDescription }}</p>
          </div>
        }

        <!-- Locked Fields Card -->
        @if (data.lockedFields.length > 0) {
          <div class="gate-card gate-card--locked">
            <div class="gate-card__header">
              <mat-icon class="gate-card__icon gate-card__icon--locked" aria-hidden="true">lock</mat-icon>
              <span class="gate-card__title">Locked Fields</span>
            </div>
            <div class="gate-chip-group">
              @for (field of data.lockedFields; track field) {
                <span class="gate-locked-chip">{{ field }}</span>
              }
            </div>
            <p class="gate-card__note">
              <em>Immutable fields protected by
                {{ data.isGoverned ? 'the Governance Authority.' : 'system policy.' }}
              </em>
            </p>
          </div>
        }
      </mat-dialog-content>

      <!-- Actions -->
      <div class="gate-actions">
        <button
          mat-flat-button
          class="gate-continue-btn"
          [mat-dialog-close]="true"
          cdkFocusInitial>
          <mat-icon aria-hidden="true">edit</mat-icon>
          Continue to Edit
        </button>
        <button
          mat-button
          class="gate-cancel-btn"
          [mat-dialog-close]="false">
          Cancel
        </button>
      </div>
    </div>
  `,
  styleUrl: './master-edit-gate-dialog.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterEditGateDialogComponent {
  data = inject<EditGateDialogData>(MAT_DIALOG_DATA);

  getModuleIcon(moduleName: string): string {
    const icons: Record<string, string> = {
      'Replenishment': 'sync_alt',
      'Needs Lists': 'checklist',
      'Transfers': 'swap_horiz',
      'Procurement': 'shopping_cart',
      'Donations': 'volunteer_activism',
      'Stock Monitoring': 'monitoring',
      'Burn Rate': 'local_fire_department',
      'Inventory': 'inventory_2',
      'Warehouses': 'warehouse',
      'Events': 'event',
      'Agencies': 'business',
      'Items': 'category',
      'Classification': 'account_tree',
    };
    return icons[moduleName] || 'extension';
  }
}
