import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';

import { formatPackageStatus } from '../models/operations-status.util';
import { PackageSplitChild } from '../models/operations.model';
import { getOperationsPackageTone, mapOperationsToneToChipTone } from '../operations-display.util';
import { OpsStatusChipComponent } from './ops-status-chip.component';

@Component({
  selector: 'app-ops-split-banner',
  standalone: true,
  imports: [RouterLink, MatIconModule, OpsStatusChipComponent],
  template: `
    @if (parent(); as parentRef) {
      <aside class="ops-split ops-split--parent" role="note"
        aria-label="Parent package reference">
        <mat-icon aria-hidden="true">call_merge</mat-icon>
        <div class="ops-split__body">
          <strong>Split from parent package</strong>
          <p>
            This package was created when
            <a [routerLink]="['/operations/package-fulfillment', parentRef.id]">
              {{ parentRef.no || ('#' + parentRef.id) }}
            </a>
            was partially released.
          </p>
        </div>
      </aside>
    }

    @if (children().length) {
      <aside class="ops-split ops-split--children" role="note"
        aria-label="Split child packages">
        <mat-icon aria-hidden="true">call_split</mat-icon>
        <div class="ops-split__body">
          <strong>Partial release children</strong>
          <ul class="ops-split__list">
            @for (child of children(); track child.package_id) {
              <li class="ops-split__item">
                <a [routerLink]="['/operations/package-fulfillment', child.package_id]">
                  {{ child.package_no || ('Package #' + child.package_id) }}
                </a>
                <app-ops-status-chip
                  [label]="childLabel(child)"
                  [tone]="childTone(child)" />
              </li>
            }
          </ul>
        </div>
      </aside>
    }
  `,
  styles: [`
    :host { display: block; }

    .ops-split {
      display: flex;
      align-items: flex-start;
      gap: 12px;
      padding: 14px 16px;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      border-radius: var(--ops-radius-md, 10px);
      background: var(--ops-card, #fbfaf7);
      margin-bottom: 12px;
    }

    .ops-split mat-icon {
      color: var(--ops-ink-muted, #787774);
      flex-shrink: 0;
    }

    .ops-split__body {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }

    .ops-split__body strong {
      font-size: 0.92rem;
      color: var(--ops-ink, #37352F);
    }

    .ops-split__body p {
      margin: 0;
      font-size: 0.85rem;
      color: var(--ops-ink-muted, #787774);
    }

    .ops-split__body a {
      color: var(--color-accent, #0f766e);
      font-weight: 600;
      text-decoration: none;
    }

    .ops-split__body a:hover,
    .ops-split__body a:focus-visible {
      text-decoration: underline;
    }

    .ops-split__list {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .ops-split__item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OpsSplitBannerComponent {
  readonly parent = input<{ id: number; no: string | null } | null>(null);
  readonly children = input<readonly PackageSplitChild[]>([]);

  childLabel(child: PackageSplitChild): string {
    return formatPackageStatus(child.status_code);
  }

  childTone(child: PackageSplitChild): ReturnType<typeof mapOperationsToneToChipTone> {
    return mapOperationsToneToChipTone(getOperationsPackageTone(child.status_code));
  }
}
