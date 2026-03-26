import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export interface OpsMetricStripItem {
  label: string;
  value: string;
  hint?: string;
}

@Component({
  selector: 'app-ops-metric-strip',
  standalone: true,
  template: `
    <div class="ops-flow-strip" role="list">
      @for (item of items(); track item.label) {
        <article class="ops-flow-strip__card" role="listitem">
          <span class="ops-flow-strip__label">{{ item.label }}</span>
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
}
