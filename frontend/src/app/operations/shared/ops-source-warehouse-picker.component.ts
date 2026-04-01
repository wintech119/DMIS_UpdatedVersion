import {
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
  output,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatSelectModule } from '@angular/material/select';
import { LookupItem } from '../../master-data/models/master-data.models';

@Component({
  selector: 'app-ops-source-warehouse-picker',
  standalone: true,
  imports: [
    FormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatSelectModule,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="ops-warehouse-picker"
      role="region"
      aria-label="Source warehouse selection">

      <div class="ops-warehouse-picker__main">
        <!-- Left: icon + selected warehouse name -->
        <div class="ops-warehouse-picker__identity">
          <span class="ops-warehouse-picker__icon-wrap" aria-hidden="true">
            <mat-icon>warehouse</mat-icon>
          </span>
          <span class="ops-warehouse-picker__name" aria-live="polite">
            {{ selectedLabel() }}
          </span>
        </div>

        <!-- Center: helper text -->
        <p class="ops-warehouse-picker__helper">
          Default source &mdash; applies to all items unless overridden
        </p>

        <!-- Right: select + override badge -->
        <div class="ops-warehouse-picker__actions">
          <mat-form-field
            class="ops-warehouse-picker__field"
            appearance="outline"
            subscriptSizing="dynamic">
            <mat-label>Source warehouse</mat-label>
            <mat-select
              [ngModel]="selectedId()"
              (ngModelChange)="onWarehouseChange($event)"
              [disabled]="disabled()"
              aria-label="Select default source warehouse">
              @for (option of warehouseOptions(); track option.value) {
                <mat-option [value]="'' + option.value">{{ option.label }}</mat-option>
              }
            </mat-select>
          </mat-form-field>

          @if (overrideCount() > 0) {
            <span
              class="ops-warehouse-picker__badge"
              [attr.aria-label]="overrideCount() + ' items use a different warehouse'">
              {{ overrideCount() }}
            </span>
          }
        </div>
      </div>

      <!-- Override summary row -->
      @if (overrideCount() > 0) {
        <div class="ops-warehouse-picker__override-row">
          <span class="ops-warehouse-picker__chip">
            <mat-icon class="ops-warehouse-picker__chip-icon">info_outline</mat-icon>
            {{ overrideCount() }} {{ overrideCount() === 1 ? 'item' : 'items' }} overridden
          </span>
          <button
            mat-button
            type="button"
            class="ops-warehouse-picker__reset-btn"
            [disabled]="disabled()"
            (click)="onClearOverrides()">
            <mat-icon>restart_alt</mat-icon>
            Reset all to default
          </button>
        </div>
      }
    </section>
  `,
  styles: [`
    :host {
      display: block;
    }

    /* ── Container ── */

    .ops-warehouse-picker {
      background: var(--color-surface-container-lowest, #ffffff);
      border: 1px solid rgba(55, 53, 47, 0.14);
      border-radius: var(--ops-radius-md, 10px);
      padding: 16px 20px;
      box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
      transition: box-shadow 0.15s ease;
    }

    /* ── Main row (desktop: horizontal, mobile: stacked) ── */

    .ops-warehouse-picker__main {
      display: flex;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
    }

    /* ── Identity: icon + warehouse name ── */

    .ops-warehouse-picker__identity {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }

    .ops-warehouse-picker__icon-wrap {
      display: grid;
      place-items: center;
      width: 40px;
      height: 40px;
      border-radius: 10px;
      background: #eef4ff;
      color: #17447f;
    }

    .ops-warehouse-picker__icon-wrap mat-icon {
      width: 22px;
      height: 22px;
      font-size: 22px;
    }

    .ops-warehouse-picker__name {
      font-size: 1.05rem;
      font-weight: 600;
      color: #37352F;
      letter-spacing: -0.01em;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 260px;
    }

    /* ── Helper text ── */

    .ops-warehouse-picker__helper {
      margin: 0;
      flex: 1 1 auto;
      color: var(--color-text-secondary, #787774);
      font-size: 0.85rem;
      line-height: 1.45;
      min-width: 180px;
    }

    /* ── Actions: select + badge ── */

    .ops-warehouse-picker__actions {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-shrink: 0;
    }

    .ops-warehouse-picker__field {
      width: 220px;
    }

    .ops-warehouse-picker__field .mat-mdc-form-field-subscript-wrapper {
      display: none;
    }

    .ops-warehouse-picker__badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 24px;
      height: 24px;
      padding: 0 8px;
      border-radius: 12px;
      background: #fde8b1;
      color: #6e4200;
      font-size: 0.78rem;
      font-weight: 700;
      line-height: 1;
    }

    /* ── Override row ── */

    .ops-warehouse-picker__override-row {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid rgba(55, 53, 47, 0.08);
      flex-wrap: wrap;
    }

    .ops-warehouse-picker__chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      border-radius: 16px;
      background: #fde8b1;
      color: #6e4200;
      font-size: 0.82rem;
      font-weight: 600;
      line-height: 1.4;
    }

    .ops-warehouse-picker__chip-icon {
      width: 16px;
      height: 16px;
      font-size: 16px;
    }

    .ops-warehouse-picker__reset-btn {
      font-size: 0.82rem;
      font-weight: 600;
      letter-spacing: 0;
    }

    /* ── Focus ring for interactive elements ── */

    .ops-warehouse-picker__reset-btn:focus-visible,
    .ops-warehouse-picker__field:focus-within {
      outline: 2px solid var(--color-primary, #1a73e8);
      outline-offset: 2px;
      border-radius: 6px;
    }

    /* ── Reduced motion ── */

    @media (prefers-reduced-motion: reduce) {
      .ops-warehouse-picker {
        transition: none;
      }
    }

    /* ── Responsive: tablet and mobile (<900px) ── */

    @media (max-width: 900px) {
      .ops-warehouse-picker__main {
        flex-direction: column;
        align-items: stretch;
      }

      .ops-warehouse-picker__identity {
        justify-content: flex-start;
      }

      .ops-warehouse-picker__name {
        max-width: 100%;
      }

      .ops-warehouse-picker__helper {
        min-width: 0;
      }

      .ops-warehouse-picker__actions {
        flex-wrap: wrap;
      }

      .ops-warehouse-picker__field {
        width: 100%;
      }

      .ops-warehouse-picker__override-row {
        flex-direction: column;
        align-items: flex-start;
      }
    }
  `],
})
export class OpsSourceWarehousePickerComponent {
  /** Available warehouses to choose from. */
  readonly warehouseOptions = input<LookupItem[]>([]);

  /** Currently selected default warehouse ID. */
  readonly selectedId = input<string>('');

  /** Count of items that use a warehouse different from the default. */
  readonly overrideCount = input<number>(0);

  /** Total items using the default warehouse. */
  readonly itemCount = input<number>(0);

  /** Whether the picker controls are disabled. */
  readonly disabled = input<boolean>(false);

  /** Emits the new warehouse ID string when the user changes the default. */
  readonly warehouseChange = output<string>();

  /** Emits when the user clicks "Reset all to default". */
  readonly clearOverrides = output<void>();

  /** Resolved display label for the currently selected warehouse. */
  readonly selectedLabel = computed(() => {
    const id = this.selectedId();
    const options = this.warehouseOptions();
    if (!id || options.length === 0) {
      return 'No warehouse selected';
    }
    const match = options.find(
      (o) => String(o.value) === String(id),
    );
    return match?.label ?? 'Unknown warehouse';
  });

  onWarehouseChange(newId: unknown): void {
    this.warehouseChange.emit(newId == null ? '' : String(newId));
  }

  onClearOverrides(): void {
    this.clearOverrides.emit();
  }
}
