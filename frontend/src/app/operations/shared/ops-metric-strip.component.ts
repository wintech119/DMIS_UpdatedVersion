import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

export interface OpsMetricStripItem {
  label: string;
  value: string;
  hint?: string;
  interactive?: boolean;
  token?: string;
  active?: boolean;
  icon?: string;
  ariaLabel?: string;
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
          [class.ops-flow-strip__card--interactive]="item.interactive"
          [class.ops-flow-strip__card--active]="item.interactive && item.active"
          [attr.role]="item.interactive ? 'button' : 'listitem'"
          [attr.tabindex]="item.interactive ? 0 : null"
          [attr.aria-pressed]="item.interactive ? (item.active ? 'true' : 'false') : null"
          [attr.aria-label]="item.interactive ? (item.ariaLabel ?? item.label + ', ' + item.value) : null"
          (click)="onItemClick(item)"
          (keydown.enter)="onItemClick(item)"
          (keydown.space)="onItemClick(item); $event.preventDefault()">
          <span class="ops-flow-strip__eyebrow">
            <span class="ops-flow-strip__label">{{ item.label }}</span>
            @if (item.icon) {
              <mat-icon class="ops-flow-strip__icon" aria-hidden="true">{{ item.icon }}</mat-icon>
            }
          </span>
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

  onItemClick(item: OpsMetricStripItem): void {
    if (!item.interactive) {
      return;
    }
    this.itemClick.emit(item);
  }
}
