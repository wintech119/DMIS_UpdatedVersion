import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

/**
 * Tone tokens for `.ops-flow-strip__card` and the optional top-right badge.
 * Mirrors the Package Fulfillment Queue palette (`--pfq-awaiting`,
 * `--pfq-drafts`, `--pfq-preparing`, `--pfq-ready`) plus a few extras
 * already used on `.ops-queue-row` so every operations queue page shares
 * the same color language across left-edge accent bar + badge pill.
 */
export type OpsMetricTileTone =
  | 'awaiting'
  | 'drafts'
  | 'preparing'
  | 'ready'
  | 'transit'
  | 'completed'
  | 'info'
  | 'neutral';

export interface OpsMetricStripItem {
  label: string;
  value: string;
  hint?: string;
  interactive?: boolean;
  /**
   * Drives the left-edge accent bar color via `--ops-queue-accent`. Use one
   * of `OpsMetricTileTone` for PFQ parity; any other string becomes a
   * CSS class suffix (`.ops-flow-strip__card--{token}`) callers can wire
   * up themselves.
   */
  token?: string;
  active?: boolean;
  icon?: string;
  ariaLabel?: string;
  /**
   * Optional top-right pill. Renders as `.ops-flow-strip__badge` with a
   * leading dot — matches `.pfq-metric__badge` structurally and visually.
   */
  badge?: {
    label: string;
    tone: OpsMetricTileTone;
  };
}

@Component({
  selector: 'app-ops-metric-strip',
  standalone: true,
  imports: [MatIconModule],
  template: `
    <div class="ops-flow-strip" [attr.role]="anyInteractive() ? 'group' : 'list'">
      @for (item of items(); track item.label) {
        <article
          class="ops-flow-strip__card"
          [class]="tileClass(item)"
          [class.ops-flow-strip__card--interactive]="item.interactive"
          [class.ops-flow-strip__card--active]="item.interactive && item.active"
          [attr.role]="item.interactive ? 'button' : 'listitem'"
          [attr.tabindex]="item.interactive ? 0 : null"
          [attr.aria-pressed]="item.interactive ? (item.active ? 'true' : 'false') : null"
          [attr.aria-label]="item.interactive ? (item.ariaLabel ?? item.label + ', ' + item.value) : null"
          (click)="onItemClick(item)"
          (keydown.enter)="onItemClick(item)"
          (keydown.space)="onItemClick(item); $event.preventDefault()">
          <div class="ops-flow-strip__top">
            <span class="ops-flow-strip__label">{{ item.label }}</span>
            @if (item.badge; as badge) {
              <span class="ops-flow-strip__badge" [class]="'ops-flow-strip__badge--' + badge.tone">
                <span class="ops-flow-strip__badge-dot" aria-hidden="true"></span>
                {{ badge.label }}
              </span>
            } @else if (item.icon) {
              <mat-icon class="ops-flow-strip__icon" aria-hidden="true">{{ item.icon }}</mat-icon>
            }
          </div>
          <strong class="ops-flow-strip__value">{{ item.value }}</strong>
          @if (item.hint) {
            <span class="ops-flow-strip__hint">{{ item.hint }}</span>
          }
        </article>
      }
    </div>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsMetricStripComponent {
  readonly items = input<readonly OpsMetricStripItem[]>([]);
  readonly itemClick = output<OpsMetricStripItem>();

  anyInteractive(): boolean {
    return this.items().some((item) => item.interactive);
  }

  tileClass(item: OpsMetricStripItem): string {
    return item.token ? `ops-flow-strip__card--${item.token}` : '';
  }

  onItemClick(item: OpsMetricStripItem): void {
    if (!item.interactive) {
      return;
    }
    this.itemClick.emit(item);
  }
}
