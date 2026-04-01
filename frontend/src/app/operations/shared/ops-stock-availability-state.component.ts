import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';

export type OpsStockAvailabilityKind = 'missing-warehouse' | 'no-candidates';
export type OpsStockAvailabilityScope = 'request' | 'item';

@Component({
  selector: 'app-ops-stock-availability-state',
  standalone: true,
  imports: [DecimalPipe, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section
      class="ops-stock-state"
      [attr.aria-label]="ariaLabel()"
      [attr.role]="scope() === 'request' ? 'status' : 'note'">
      <div class="ops-stock-state__icon" aria-hidden="true">
        <mat-icon>{{ iconName() }}</mat-icon>
      </div>

      <div class="ops-stock-state__body">
        <p class="ops-stock-state__eyebrow">Warehouse availability</p>
        <h3 class="ops-stock-state__title">{{ title() }}</h3>
        <p class="ops-stock-state__summary">{{ summary() }}</p>

        <dl class="ops-stock-state__facts" aria-label="Availability details">
          <div class="ops-stock-state__fact">
            <dt>Impact</dt>
            <dd>{{ impactLabel() }}</dd>
          </div>
          @if (showRemainingQty()) {
            <div class="ops-stock-state__fact">
              <dt>Still needed</dt>
              <dd>{{ remainingQty() | number:'1.0-4' }}</dd>
            </div>
          }
        </dl>

        <div class="ops-stock-state__guidance">
          <strong>Next step</strong>
          <p>{{ guidance() }}</p>
        </div>

        @if (detailText()) {
          <p class="ops-stock-state__detail">{{ detailText() }}</p>
        }
      </div>
    </section>
  `,
  styles: [`
    :host {
      display: block;
    }

    .ops-stock-state {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 16px;
      padding: 22px;
      border-radius: var(--ops-radius-md, 10px);
      border: 1px solid var(--ops-outline-strong, rgba(55, 53, 47, 0.14));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--ops-section, #fbfaf7) 72%, white) 0%, #ffffff 100%);
      box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
      color: var(--ops-ink, var(--color-text-primary, #37352F));
    }

    .ops-stock-state__icon {
      display: grid;
      place-items: center;
      width: 48px;
      height: 48px;
      border-radius: 14px;
      background: #fff4de;
      color: #8a5900;
      flex-shrink: 0;
    }

    .ops-stock-state__icon mat-icon {
      width: 24px;
      height: 24px;
      font-size: 24px;
    }

    .ops-stock-state__body {
      min-width: 0;
    }

    .ops-stock-state__eyebrow {
      margin: 0 0 6px;
      color: var(--ops-ink-subtle, #908d87);
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      text-transform: uppercase;
    }

    .ops-stock-state__title {
      margin: 0;
      font-size: clamp(1rem, 1.5vw, 1.2rem);
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--ops-ink, var(--color-text-primary, #37352F));
    }

    .ops-stock-state__summary,
    .ops-stock-state__detail,
    .ops-stock-state__guidance p {
      margin: 10px 0 0;
      color: var(--ops-ink-muted, var(--color-text-secondary, #787774));
      font-size: 0.92rem;
      line-height: 1.58;
    }

    .ops-stock-state__facts {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 16px 0 0;
    }

    .ops-stock-state__fact {
      padding: 12px 14px;
      border-radius: 10px;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      background: color-mix(in srgb, var(--ops-section, #fbfaf7) 78%, white);
    }

    .ops-stock-state__fact dt {
      margin: 0 0 4px;
      color: var(--ops-ink-subtle, #908d87);
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }

    .ops-stock-state__fact dd {
      margin: 0;
      color: var(--ops-ink, var(--color-text-primary, #37352F));
      font-size: 0.95rem;
      font-weight: 600;
    }

    .ops-stock-state__guidance {
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: 10px;
      background: #eef4ff;
      color: #17447f;
    }

    .ops-stock-state__guidance strong {
      display: block;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    .ops-stock-state__guidance p {
      color: inherit;
    }

    .ops-stock-state__detail {
      padding-top: 12px;
      border-top: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      font-size: 0.82rem;
    }

    @media (prefers-reduced-motion: reduce) {
      .ops-stock-state {
        transition: none;
      }
    }

    @media (max-width: 760px) {
      .ops-stock-state {
        grid-template-columns: 1fr;
        padding: 18px;
      }

      .ops-stock-state__facts {
        grid-template-columns: 1fr;
      }
    }
  `],
})
export class OpsStockAvailabilityStateComponent {
  readonly kind = input.required<OpsStockAvailabilityKind>();
  readonly scope = input<OpsStockAvailabilityScope>('item');
  readonly itemName = input<string | null>(null);
  readonly remainingQty = input<number | string | null>(null);
  readonly detail = input<string | null>(null);

  readonly title = computed(() => {
    if (this.kind() === 'missing-warehouse') {
      return 'Warehouse setup is needed before stock can be reserved';
    }
    const itemName = this.itemName()?.trim();
    return itemName
      ? `${itemName} is not stocked in an available warehouse`
      : 'This item is not stocked in an available warehouse';
  });

  readonly summary = computed(() => {
    if (this.kind() === 'missing-warehouse') {
      return 'This request is ready for fulfillment, but the workspace does not yet know which source warehouse should supply it.';
    }
    return 'The allocation workspace loaded successfully, but there are no matching stock lines to reserve for the selected item right now.';
  });

  readonly guidance = computed(() => {
    if (this.kind() === 'missing-warehouse') {
      return 'Link the request to the correct source warehouse or complete the warehouse compatibility setup, then refresh the reservation workspace.';
    }
    return 'Choose another item, replenish stock in a valid warehouse, or return later once inventory for this item is available.';
  });

  readonly impactLabel = computed(() =>
    this.kind() === 'missing-warehouse'
      ? 'Request-level blocker'
      : 'Item-level blocker'
  );

  readonly iconName = computed(() =>
    this.kind() === 'missing-warehouse' ? 'domain_disabled' : 'inventory_2'
  );

  readonly ariaLabel = computed(() =>
    this.kind() === 'missing-warehouse'
      ? 'Warehouse setup required before stock can be reserved'
      : 'No warehouse stock available for the selected item'
  );

  readonly detailText = computed(() => this.detail()?.trim() || null);

  readonly showRemainingQty = computed(() => {
    const value = Number(this.remainingQty() ?? 0);
    return Number.isFinite(value) && value > 0;
  });
}
