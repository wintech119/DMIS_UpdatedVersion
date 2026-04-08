import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { PackageLockConflict } from '../models/operations.model';

const FORCE_RELEASE_ROLE_CODES: ReadonlySet<string> = new Set([
  'LOGISTICS_MANAGER',
  'TST_LOGISTICS_MANAGER',
  'ODPEM_LOGISTICS_MANAGER',
  'SYSTEM_ADMINISTRATOR',
]);

const ROLE_LABELS: Record<string, string> = {
  LOGISTICS_MANAGER: 'Logistics Manager',
  TST_LOGISTICS_MANAGER: 'Logistics Manager',
  ODPEM_LOGISTICS_MANAGER: 'Logistics Manager',
  LOGISTICS_OFFICER: 'Logistics Officer',
  TST_LOGISTICS_OFFICER: 'Logistics Officer',
  SYSTEM_ADMINISTRATOR: 'System Administrator',
  AGENCY_DISTRIBUTOR: 'Agency Distributor',
  EXECUTIVE: 'Executive',
};

@Component({
  selector: 'app-ops-package-lock-state',
  standalone: true,
  imports: [MatButtonModule, MatIconModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="ops-package-lock" role="status" aria-live="polite">
      <div class="ops-package-lock__icon" aria-hidden="true">
        <mat-icon>lock</mat-icon>
      </div>

      <div class="ops-package-lock__body">
        <p class="ops-package-lock__eyebrow">Fulfillment safeguard</p>
        <h2 class="ops-package-lock__title">{{ title }}</h2>
        <p class="ops-package-lock__summary">{{ summary() }}</p>

        <dl class="ops-package-lock__facts" aria-label="Package lock details">
          <div class="ops-package-lock__fact">
            <dt>Held by</dt>
            <dd>{{ ownerLabel() }}</dd>
          </div>
          <div class="ops-package-lock__fact">
            <dt>Role</dt>
            <dd>{{ roleLabel() }}</dd>
          </div>
          <div class="ops-package-lock__fact">
            <dt>Lock expires</dt>
            <dd>
              {{ expiresLabel() }}
              @if (expiresRelative()) {
                <span class="ops-package-lock__fact-meta">({{ expiresRelative() }})</span>
              }
            </dd>
          </div>
        </dl>

        <div class="ops-package-lock__guidance">
          <strong>Next step</strong>
          <p>{{ guidance() }}</p>
        </div>

        <div class="ops-package-lock__actions">
          <button
            mat-stroked-button
            type="button"
            [disabled]="refreshing() || unlocking()"
            (click)="refresh.emit()">
            <mat-icon>refresh</mat-icon>
            Refresh
          </button>
          @if (isOwner()) {
            <button
              mat-flat-button
              color="primary"
              type="button"
              [disabled]="unlocking() || refreshing()"
              (click)="releaseOwn.emit()">
              <mat-icon>{{ unlocking() ? 'hourglass_top' : 'lock_open' }}</mat-icon>
              {{ unlocking() ? 'Releasing...' : 'Release my lock' }}
            </button>
          } @else if (canForceRelease()) {
            <button
              mat-stroked-button
              color="warn"
              type="button"
              [disabled]="unlocking() || refreshing()"
              (click)="forceRelease.emit()">
              <mat-icon>{{ unlocking() ? 'hourglass_top' : 'lock_open' }}</mat-icon>
              {{ unlocking() ? 'Releasing...' : 'Take over package' }}
            </button>
          }
        </div>
      </div>
    </section>
  `,
  styles: [`
    :host {
      display: block;
    }

    .ops-package-lock {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 16px;
      padding: 22px;
      border-radius: var(--ops-radius-md, 10px);
      border: 1px solid #e4a93c;
      background:
        linear-gradient(180deg, #fff8ec 0%, #ffffff 100%);
      box-shadow: 0 1px 3px rgba(55, 53, 47, 0.06);
      color: var(--ops-ink, var(--color-text-primary, #37352F));
    }

    .ops-package-lock__icon {
      display: grid;
      place-items: center;
      width: 48px;
      height: 48px;
      border-radius: 14px;
      background: #ffe7b3;
      color: #8a5900;
      flex-shrink: 0;
    }

    .ops-package-lock__icon mat-icon {
      width: 24px;
      height: 24px;
      font-size: 24px;
    }

    .ops-package-lock__body {
      min-width: 0;
    }

    .ops-package-lock__eyebrow {
      margin: 0 0 6px;
      color: var(--ops-ink-subtle, #908d87);
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.2em;
      text-transform: uppercase;
    }

    .ops-package-lock__title {
      margin: 0;
      font-size: clamp(1rem, 1.5vw, 1.2rem);
      font-weight: 700;
      letter-spacing: -0.02em;
      color: var(--ops-ink, var(--color-text-primary, #37352F));
    }

    .ops-package-lock__summary,
    .ops-package-lock__guidance p {
      margin: 10px 0 0;
      color: var(--ops-ink-muted, var(--color-text-secondary, #787774));
      font-size: 0.92rem;
      line-height: 1.58;
    }

    .ops-package-lock__facts {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin: 16px 0 0;
    }

    .ops-package-lock__fact {
      padding: 12px 14px;
      border-radius: 10px;
      border: 1px solid var(--ops-outline, rgba(55, 53, 47, 0.08));
      background: color-mix(in srgb, var(--ops-section, #fbfaf7) 78%, white);
    }

    .ops-package-lock__fact dt {
      margin: 0 0 4px;
      color: var(--ops-ink-subtle, #908d87);
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }

    .ops-package-lock__fact dd {
      margin: 0;
      color: var(--ops-ink, var(--color-text-primary, #37352F));
      font-size: 0.95rem;
      font-weight: 600;
      overflow-wrap: anywhere;
    }

    .ops-package-lock__fact-meta {
      display: inline-block;
      margin-left: 6px;
      color: var(--ops-ink-subtle, #908d87);
      font-weight: 500;
      font-size: 0.82rem;
    }

    .ops-package-lock__guidance {
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: 10px;
      background: #eef4ff;
      color: #17447f;
    }

    .ops-package-lock__guidance strong {
      display: block;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    .ops-package-lock__guidance p {
      color: inherit;
    }

    .ops-package-lock__actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }

    @media (prefers-reduced-motion: reduce) {
      .ops-package-lock {
        transition: none;
      }
    }

    @media (max-width: 760px) {
      .ops-package-lock {
        grid-template-columns: 1fr;
        padding: 18px;
      }

      .ops-package-lock__facts {
        grid-template-columns: 1fr;
      }

      .ops-package-lock__actions button {
        width: 100%;
      }
    }
  `],
})
export class OpsPackageLockStateComponent {
  readonly conflict = input.required<PackageLockConflict>();
  readonly currentUserRef = input<string | null>(null);
  readonly currentUserRoles = input<readonly string[]>([]);
  readonly unlocking = input<boolean>(false);
  readonly refreshing = input<boolean>(false);

  readonly refresh = output<void>();
  readonly releaseOwn = output<void>();
  readonly forceRelease = output<void>();

  readonly title = 'Package is locked by another actor';

  /**
   * Best-effort owner detection. The backend prefers user_id, the frontend prefers
   * username — in most deployments they are the same string, but a false negative
   * simply downgrades the UI from "Release my lock" to "Take over package", which is
   * still functional and still backend-enforced.
   */
  readonly isOwner = computed(() => {
    const ref = (this.currentUserRef() ?? '').trim();
    const ownerId = (this.conflict().lock_owner_user_id ?? '').trim();
    return !!ref && !!ownerId && ref === ownerId;
  });

  readonly canForceRelease = computed(() => {
    const roles = this.currentUserRoles() ?? [];
    return roles.some((role) => FORCE_RELEASE_ROLE_CODES.has(role));
  });

  readonly ownerLabel = computed(() => {
    const ownerId = (this.conflict().lock_owner_user_id ?? '').trim();
    return ownerId || 'Another fulfillment actor';
  });

  readonly roleLabel = computed(() => {
    const code = (this.conflict().lock_owner_role_code ?? '').trim();
    if (!code) {
      return 'Unknown role';
    }
    return ROLE_LABELS[code] ?? code;
  });

  readonly expiresAtMs = computed(() => {
    const raw = this.conflict().lock_expires_at;
    if (!raw) {
      return null;
    }
    const ts = Date.parse(raw);
    return Number.isFinite(ts) ? ts : null;
  });

  readonly expiresLabel = computed(() => {
    const ms = this.expiresAtMs();
    if (ms == null) {
      return 'Not set';
    }
    try {
      return new Intl.DateTimeFormat('en-JM', {
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(new Date(ms));
    } catch {
      return new Date(ms).toISOString();
    }
  });

  readonly expiresRelative = computed(() => {
    const ms = this.expiresAtMs();
    if (ms == null) {
      return '';
    }
    const diffMinutes = Math.round((ms - Date.now()) / 60_000);
    if (diffMinutes === 0) {
      return 'expiring now';
    }
    if (diffMinutes > 0) {
      if (diffMinutes >= 60) {
        const hours = Math.round(diffMinutes / 60);
        return `in ${hours} ${hours === 1 ? 'hour' : 'hours'}`;
      }
      return `in ${diffMinutes} min`;
    }
    const elapsed = Math.abs(diffMinutes);
    if (elapsed >= 60) {
      const hours = Math.round(elapsed / 60);
      return `expired ${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
    }
    return `expired ${elapsed} min ago`;
  });

  readonly summary = computed(() => {
    if (this.isOwner()) {
      return 'You already hold this lock. Release it when you are done editing so another actor can pick up the package.';
    }
    return `This package is currently held by ${this.ownerLabel()} (${this.roleLabel()}). Reservation changes will resume once they release it or the lock expires.`;
  });

  readonly guidance = computed(() => {
    if (this.isOwner()) {
      return 'Release your own lock when you are done editing, or click Refresh to re-check the package state.';
    }
    if (this.canForceRelease()) {
      return 'If this is urgent, you can take over the package. The current owner will be notified. Otherwise wait for them to release it.';
    }
    return 'Wait for the current owner to release the lock, or ask a Logistics Manager to take over the package.';
  });
}
