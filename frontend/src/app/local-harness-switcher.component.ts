import { HttpClient } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';

import { localAuthHarnessClientEnabled } from './core/dev-user.interceptor';

export interface DevUser {
  user_id: string;
  username: string;
  email?: string | null;
  roles: string[];
  memberships: {
    tenant_id: number | null;
    tenant_code: string | null;
    tenant_name: string | null;
    tenant_type: string | null;
    is_primary: boolean;
    access_level: string | null;
  }[];
}

interface LocalAuthHarnessResponse {
  enabled?: boolean;
  default_user?: string | null;
  users?: DevUser[];
  missing_usernames?: string[];
}

const LOCAL_HARNESS_STORAGE_KEY = 'dmis_local_harness_user';

@Component({
  selector: 'dmis-local-harness-switcher',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (canSwitchLocalHarnessUser()) {
      <label for="dev-user-select" class="dev-user-label">Local test mode</label>
      <select
        id="dev-user-select"
        class="dev-user-select"
        [value]="selectedLocalHarnessUser()"
        (change)="switchLocalHarnessUser($any($event.target).value)">
        <option value="">{{ localHarnessDefaultLabel() }}</option>
        @for (user of localHarnessUsers(); track user.username) {
          <option [value]="user.username">
            {{ formatLocalHarnessUserLabel(user) }}
          </option>
        }
      </select>
      <button
        type="button"
        class="dev-user-clear"
        [disabled]="!selectedLocalHarnessUser()"
        (click)="clearLocalHarnessUser()">
        Reset
      </button>
    }
  `,
  styles: [`
    :host {
      display: flex;
      align-items: center;
      gap: 0.625rem;
    }

    .dev-user-label {
      color: var(--color-text-secondary);
      font-size: var(--text-xs);
    }

    .dev-user-select {
      min-width: 200px;
      max-width: 300px;
      border-radius: 6px;
      border: 1px solid var(--color-border);
      background: var(--color-surface);
      color: var(--color-text-primary);
      padding: 0.25rem 0.5rem;
      font-size: var(--text-xs);
    }

    .dev-user-select:focus {
      outline: none;
      border-color: var(--color-accent);
      box-shadow: 0 0 0 1px var(--color-accent-shadow);
    }

    .dev-user-clear {
      border: 1px solid var(--color-border);
      border-radius: 6px;
      background: var(--color-surface);
      color: var(--color-text-primary);
      padding: 0.25rem 0.625rem;
      font-size: var(--text-xs);
      cursor: pointer;
      transition: background 0.12s ease;
    }

    .dev-user-clear:hover {
      background: var(--color-hover);
    }

    .dev-user-clear:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }

    @media (width <= 900px) {
      :host {
        gap: 0.375rem;
      }

      .dev-user-select {
        min-width: 150px;
      }
    }
  `],
})
export class DmisLocalHarnessSwitcherComponent implements OnInit {
  private readonly http = inject(HttpClient);

  readonly localHarnessUsers = signal<DevUser[]>([]);
  readonly selectedLocalHarnessUser = signal('');
  readonly defaultLocalHarnessUser = signal<string | null>(null);
  readonly localHarnessMissingUsers = signal<string[]>([]);
  readonly localHarnessClientEnabled = localAuthHarnessClientEnabled();
  readonly canSwitchLocalHarnessUser = computed(
    () => this.localHarnessClientEnabled && this.localHarnessUsers().length > 0
  );

  ngOnInit(): void {
    if (this.localHarnessClientEnabled) {
      this.loadLocalAuthHarness();
      return;
    }
    this.resetLocalHarnessState();
  }

  switchLocalHarnessUser(requestedUsername: string): void {
    const normalized = String(requestedUsername || '').trim();
    if (!normalized) {
      localStorage.removeItem(LOCAL_HARNESS_STORAGE_KEY);
    } else {
      localStorage.setItem(LOCAL_HARNESS_STORAGE_KEY, normalized);
    }
    window.location.reload();
  }

  clearLocalHarnessUser(): void {
    localStorage.removeItem(LOCAL_HARNESS_STORAGE_KEY);
    this.selectedLocalHarnessUser.set('');
    window.location.reload();
  }

  formatLocalHarnessUserLabel(user: DevUser): string {
    const identity = String(user.email ?? '').trim() || user.username;
    const primaryRole = user.roles[0];
    const primaryMembership = user.memberships.find((membership) => membership.is_primary) ?? user.memberships[0];
    const tenantRef = primaryMembership?.tenant_code ?? primaryMembership?.tenant_name ?? '';
    const descriptor = [primaryRole, tenantRef].filter(Boolean).join(' - ');
    return descriptor ? `${identity} (${descriptor})` : identity;
  }

  localHarnessDefaultLabel(): string {
    const defaultUser = this.defaultLocalHarnessUser();
    return defaultUser ? `Default local user (${defaultUser})` : 'Default local user';
  }

  private loadLocalAuthHarness(): void {
    this.http.get<LocalAuthHarnessResponse>('/api/v1/auth/local-harness/').subscribe({
      next: (data) => {
        if (!data.enabled) {
          this.resetLocalHarnessState();
          return;
        }

        const users = (data.users ?? []).filter((user) => !!user?.username).map((user) => ({
          user_id: String(user.user_id ?? '').trim(),
          username: String(user.username ?? '').trim(),
          email: user.email ?? null,
          roles: Array.isArray(user.roles) ? user.roles.map((role) => String(role).trim()).filter(Boolean) : [],
          memberships: Array.isArray(user.memberships)
            ? user.memberships.map((membership) => ({
              tenant_id: membership?.tenant_id != null ? Number(membership.tenant_id) : null,
              tenant_code: String(membership?.tenant_code ?? '').trim() || null,
              tenant_name: String(membership?.tenant_name ?? '').trim() || null,
              tenant_type: String(membership?.tenant_type ?? '').trim() || null,
              is_primary: Boolean(membership?.is_primary),
              access_level: String(membership?.access_level ?? '').trim() || null,
            }))
            : [],
        }));
        this.localHarnessUsers.set(users);
        this.defaultLocalHarnessUser.set(String(data.default_user ?? '').trim() || null);
        this.localHarnessMissingUsers.set(
          Array.isArray(data.missing_usernames)
            ? data.missing_usernames.map((value) => String(value).trim()).filter(Boolean)
            : []
        );

        const stored = String(localStorage.getItem(LOCAL_HARNESS_STORAGE_KEY) ?? '').trim();
        if (!stored) {
          this.selectedLocalHarnessUser.set('');
          return;
        }

        const exists = users.some((user) => user.username === stored);
        if (!exists) {
          localStorage.removeItem(LOCAL_HARNESS_STORAGE_KEY);
          this.selectedLocalHarnessUser.set('');
          return;
        }
        this.selectedLocalHarnessUser.set(stored);
      },
      error: () => {
        this.resetLocalHarnessState();
      }
    });
  }

  private resetLocalHarnessState(): void {
    this.localHarnessUsers.set([]);
    this.defaultLocalHarnessUser.set(null);
    this.localHarnessMissingUsers.set([]);
    this.selectedLocalHarnessUser.set('');
    localStorage.removeItem(LOCAL_HARNESS_STORAGE_KEY);
  }
}
