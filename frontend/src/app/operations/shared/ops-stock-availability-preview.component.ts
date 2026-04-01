import { ChangeDetectionStrategy, Component } from '@angular/core';

import { OpsStockAvailabilityStateComponent } from './ops-stock-availability-state.component';

@Component({
  selector: 'app-ops-stock-availability-preview',
  standalone: true,
  imports: [OpsStockAvailabilityStateComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <main class="ops-stock-preview" aria-label="Stock availability preview gallery">
      <header class="ops-stock-preview__hero">
        <p class="ops-stock-preview__eyebrow">Prompt Validation Preview</p>
        <h1 class="ops-stock-preview__title">Warehouse availability states</h1>
        <p class="ops-stock-preview__summary">
          This page exercises the reusable empty and blocker states that the revised DMIS generation prompt
          should now produce for fulfillment workflows.
        </p>
      </header>

      <section class="ops-stock-preview__grid">
        <app-ops-stock-availability-state
          kind="missing-warehouse"
          scope="request"
          detail="The current request is missing a source warehouse link, so the allocation engine cannot produce stock lines yet." />

        <app-ops-stock-availability-state
          kind="no-candidates"
          scope="item"
          itemName="Portable Water Container"
          remainingQty="42"
          detail="No active warehouse has on-hand stock that matches the current allocation rules for this item." />
      </section>
    </main>
  `,
  styles: [`
    :host {
      display: block;
      min-height: 100%;
      background: var(--ops-page-bg, #f7f6f3);
    }

    .ops-stock-preview {
      display: grid;
      gap: 24px;
      padding: 28px;
    }

    .ops-stock-preview__hero {
      display: grid;
      gap: 8px;
      max-width: 54rem;
    }

    .ops-stock-preview__eyebrow {
      margin: 0;
      color: var(--ops-ink-subtle, #908d87);
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      text-transform: uppercase;
    }

    .ops-stock-preview__title {
      margin: 0;
      font-size: clamp(1.65rem, 2.5vw, 2.2rem);
      font-weight: 800;
      letter-spacing: -0.04em;
      color: var(--ops-ink, var(--color-text-primary, #37352F));
    }

    .ops-stock-preview__summary {
      margin: 0;
      max-width: 46rem;
      color: var(--ops-ink-muted, var(--color-text-secondary, #787774));
      font-size: 0.96rem;
      line-height: 1.62;
    }

    .ops-stock-preview__grid {
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    @media (max-width: 900px) {
      .ops-stock-preview {
        padding: 20px;
      }

      .ops-stock-preview__grid {
        grid-template-columns: 1fr;
      }
    }
  `],
})
export class OpsStockAvailabilityPreviewComponent {}
