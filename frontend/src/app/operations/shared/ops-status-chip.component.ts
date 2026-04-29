import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

/**
 * Size variants for the operations status chip.
 *
 * - `sm` — dense table cells / inline metadata (future; reserved).
 * - `md` — default; matches the historical chip rendering exactly so all
 *   existing call sites keep their visual treatment without passing
 *   `size`. The `.ops-chip--size-md` selector intentionally declares NO
 *   property overrides so it inherits the global `.ops-chip` cascade
 *   defined in `operations-theme.scss` (loaded globally via
 *   `frontend/src/styles.scss`).
 * - `lg` — relief-request wizard urgency picker (44 px touch-target per
 *   WCAG 2.2 AA 2.5.5; pairs status colour with a leading `check_circle`
 *   icon when `checkmark` is true to satisfy the "status colour always
 *   paired with text + icon" rule from
 *   `frontend/src/lib/prompts/generation.ts` §"Status chips".
 */
export type OpsStatusChipSize = 'sm' | 'md' | 'lg';

@Component({
  selector: 'app-ops-status-chip',
  standalone: true,
  imports: [MatIconModule],
  template: `
    <span [attr.class]="'ops-chip ' + chipClass()">
      @if (size() === 'lg' && checkmark()) {
        <mat-icon class="ops-chip__check" aria-hidden="true">check_circle</mat-icon>
      }
      @if (showDot()) {
        <span class="ops-chip__dot"></span>
      }
      {{ label() }}
    </span>
  `,
  styles: [`
    /* Default dot — matches historical 'md' rendering. */
    .ops-chip__dot {
      width: 5px;
      height: 5px;
      border-radius: 50%;
      background: currentColor;
      flex-shrink: 0;
    }

    /* 'md' is the no-op branch: no rule overrides so existing call sites
       inherit the global '.ops-chip' cascade verbatim. */

    /* 'sm' — denser variant for table cells. Reserved for future use. */
    .ops-chip--size-sm {
      gap: 4px;
      min-height: 18px;
      padding: 1px 6px;
      font-size: var(--text-xs);
      line-height: var(--leading-tight);
    }

    /* 'lg' — wizard urgency picker. 44 px tap target, 16 px label, mixed
       case (no uppercase forcing), softer letter-spacing. The leading
       check_circle icon (when 'checkmark' is true) provides the icon
       backup paired with the tone colour. */
    .ops-chip--size-lg {
      gap: 6px;
      min-height: 44px;
      padding: 8px 14px;
      font-size: var(--text-sm);
      font-weight: var(--weight-semibold);
      letter-spacing: var(--tracking-tight);
      line-height: var(--leading-tight);
      text-transform: none;
      white-space: normal;
    }

    .ops-chip--size-lg .ops-chip__dot {
      width: 8px;
      height: 8px;
    }

    .ops-chip__check {
      font-size: 18px;
      width: 18px;
      height: 18px;
      line-height: 18px;
      flex-shrink: 0;
      color: currentColor;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsStatusChipComponent {
  readonly label = input.required<string>();
  readonly tone = input<'neutral' | 'soft' | 'critical' | 'warning' | 'success' | 'info' | 'outline'>('neutral');
  readonly showDot = input(true);
  readonly size = input<OpsStatusChipSize>('md');
  readonly checkmark = input(false);

  readonly chipClass = computed(() => `ops-chip--${this.tone()} ops-chip--size-${this.size()}`);
}
