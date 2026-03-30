import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { DatePipe } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';

export interface OpsActivityItem {
  id: string | number;
  icon: string;
  label: string;
  detail?: string;
  timestamp: string | Date;
  actor?: string;
  tone?: 'neutral' | 'success' | 'warning' | 'critical' | 'info';
}

@Component({
  selector: 'app-ops-activity-feed',
  standalone: true,
  imports: [DatePipe, MatIconModule, MatButtonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="ops-activity" [attr.aria-label]="ariaLabel()">
      <header class="ops-activity__header">
        <div>
          <p class="ops-activity__eyebrow">{{ eyebrow() }}</p>
          <h3 class="ops-activity__title">{{ title() }}</h3>
        </div>
        @if (showViewAll()) {
          <button mat-button class="ops-activity__link" (click)="viewAll.emit()">
            <mat-icon>open_in_new</mat-icon>
            <span>{{ viewAllLabel() }}</span>
          </button>
        }
      </header>

      @if (visibleItems().length === 0) {
        <div class="ops-activity__empty">
          <p>{{ emptyLabel() }}</p>
        </div>
      } @else {
        <ol class="ops-activity__list">
          @for (item of visibleItems(); track item.id) {
            <li class="ops-activity__item">
              <span class="ops-activity__dot" [attr.data-tone]="item.tone ?? 'neutral'">
                <mat-icon class="ops-activity__icon">{{ item.icon }}</mat-icon>
              </span>
              <div class="ops-activity__body">
                <p class="ops-activity__label">{{ item.label }}</p>
                @if (item.detail) {
                  <p class="ops-activity__detail">{{ item.detail }}</p>
                }
                <p class="ops-activity__meta">
                  @if (item.actor) {
                    <span>{{ item.actor }}</span>
                    <span class="ops-activity__sep">&middot;</span>
                  }
                  <time [attr.datetime]="item.timestamp">{{ item.timestamp | date:'MMM d, y, h:mm a' }}</time>
                </p>
              </div>
            </li>
          }
        </ol>
      }
    </section>
  `,
  styles: [`
    .ops-activity {
      background: var(--ops-card, #fff);
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: var(--ops-radius-md, 10px);
      padding: 22px;
    }

    .ops-activity__header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 18px;
    }

    .ops-activity__eyebrow {
      margin: 0;
      color: var(--ops-ink-subtle, #908d87);
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      text-transform: uppercase;
    }

    .ops-activity__title {
      margin: 4px 0 0;
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--ops-ink, var(--color-text-primary, #37352F));
    }

    .ops-activity__link {
      color: var(--ops-ink-subtle, #908d87);
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;

      mat-icon {
        font-size: 16px;
        width: 16px;
        height: 16px;
      }
    }

    .ops-activity__empty {
      padding: 24px;
      border-radius: var(--ops-radius-md, 10px);
      background: var(--ops-section, #fbfaf7);
      color: var(--ops-ink-muted, var(--color-text-secondary, #787774));
      text-align: center;
      font-size: 0.92rem;
      line-height: 1.6;

      p { margin: 0; }
    }

    .ops-activity__list {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 0;
    }

    .ops-activity__item {
      display: grid;
      grid-template-columns: 32px 1fr;
      gap: 12px;
      padding: 12px 0;
      border-bottom: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      position: relative;
    }

    .ops-activity__item:last-child {
      border-bottom: none;
      padding-bottom: 0;
    }

    .ops-activity__item:first-child {
      padding-top: 0;
    }

    /* Timeline connector line */
    .ops-activity__item:not(:last-child)::before {
      content: '';
      position: absolute;
      left: 15px;
      top: 36px;
      bottom: 0;
      width: 1px;
      background: var(--ops-outline, rgba(55, 53, 47, 0.08));
    }

    .ops-activity__item:first-child:not(:last-child)::before {
      top: 24px;
    }

    .ops-activity__dot {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      border-radius: 50%;
      background: var(--ops-section, #fbfaf7);
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      flex-shrink: 0;
      position: relative;
      z-index: 1;
    }

    .ops-activity__dot[data-tone="success"] {
      background: #edf7ef;
      border-color: rgba(40, 106, 54, 0.18);
      color: #286a36;
    }

    .ops-activity__dot[data-tone="warning"] {
      background: #fff4de;
      border-color: rgba(138, 89, 0, 0.18);
      color: #8a5900;
    }

    .ops-activity__dot[data-tone="critical"] {
      background: #ffedea;
      border-color: rgba(166, 41, 29, 0.18);
      color: #a6291d;
    }

    .ops-activity__dot[data-tone="info"] {
      background: #eef4ff;
      border-color: rgba(23, 68, 127, 0.18);
      color: #17447f;
    }

    .ops-activity__icon {
      font-size: 16px;
      width: 16px;
      height: 16px;
      color: inherit;
    }

    .ops-activity__body {
      min-width: 0;
      padding-top: 4px;
    }

    .ops-activity__label {
      margin: 0;
      font-size: 0.92rem;
      font-weight: 600;
      color: var(--ops-ink, var(--color-text-primary, #37352F));
      line-height: 1.4;
    }

    .ops-activity__detail {
      margin: 4px 0 0;
      color: var(--ops-ink-muted, var(--color-text-secondary, #787774));
      font-size: 0.85rem;
      line-height: 1.55;
    }

    .ops-activity__meta {
      margin: 6px 0 0;
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--ops-ink-subtle, #908d87);
      font-size: 0.75rem;
    }

    .ops-activity__sep {
      opacity: 0.5;
    }

    @media (prefers-reduced-motion: reduce) {
      .ops-activity__item { transition: none; }
    }

    @media (max-width: 520px) {
      .ops-activity { padding: 16px; }

      .ops-activity__item {
        grid-template-columns: 26px 1fr;
        gap: 10px;
      }

      .ops-activity__dot {
        width: 26px;
        height: 26px;
      }

      .ops-activity__icon {
        font-size: 14px;
        width: 14px;
        height: 14px;
      }
    }
  `],
})
export class OpsActivityFeedComponent {
  readonly items = input<readonly OpsActivityItem[]>([]);
  readonly maxItems = input(10);
  readonly title = input('Recent activity');
  readonly eyebrow = input('Timeline');
  readonly emptyLabel = input('No activity recorded yet.');
  readonly ariaLabel = input('Activity feed');
  readonly showViewAll = input(false);
  readonly viewAllLabel = input('View All');

  readonly viewAll = output<void>();

  readonly visibleItems = computed(() => {
    const max = this.maxItems();
    return this.items().slice(0, max);
  });
}
