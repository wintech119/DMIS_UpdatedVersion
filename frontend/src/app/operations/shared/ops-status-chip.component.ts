import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

@Component({
  selector: 'app-ops-status-chip',
  standalone: true,
  template: `
    <span [attr.class]="'ops-chip ' + chipClass()">
      @if (showDot()) {
        <span class="ops-chip__dot"></span>
      }
      {{ label() }}
    </span>
  `,
  styles: [`
    .ops-chip__dot {
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: currentColor;
      flex-shrink: 0;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsStatusChipComponent {
  readonly label = input.required<string>();
  readonly tone = input<'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline'>('neutral');
  readonly showDot = input(false);

  readonly chipClass = computed(() => `ops-chip--${this.tone()}`);
}
