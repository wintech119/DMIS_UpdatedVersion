import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { RouterOutlet } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { DmisDataFreshnessBannerComponent } from './replenishment/shared/dmis-data-freshness-banner/dmis-data-freshness-banner.component';

interface DevUser {
  user_id: string;
  username: string;
  email?: string | null;
  roles: string[];
}

const DEV_USER_STORAGE_KEY = 'dmis_dev_user';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, MatToolbarModule, DmisDataFreshnessBannerComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit {
  private readonly http = inject(HttpClient);

  title = 'dmis-frontend';
  readonly currentUser = signal('Unknown');
  readonly devUsers = signal<DevUser[]>([]);
  readonly selectedDevUser = signal('');
  readonly canSwitchDevUser = computed(() => this.devUsers().length > 0);

  ngOnInit(): void {
    this.loadWhoAmI();
    this.loadDevUsers();
  }

  switchDevUser(requestedUsername: string): void {
    const normalized = String(requestedUsername || '').trim();
    if (!normalized) {
      localStorage.removeItem(DEV_USER_STORAGE_KEY);
    } else {
      localStorage.setItem(DEV_USER_STORAGE_KEY, normalized);
    }
    window.location.reload();
  }

  clearDevUser(): void {
    localStorage.removeItem(DEV_USER_STORAGE_KEY);
    this.selectedDevUser.set('');
    window.location.reload();
  }

  formatDevUserLabel(user: DevUser): string {
    const primaryRole = user.roles[0];
    return primaryRole ? `${user.username} (${primaryRole})` : user.username;
  }

  private loadWhoAmI(): void {
    this.http
      .get<{ user_id?: string | null; username?: string | null }>('/api/v1/auth/whoami/')
      .subscribe({
        next: (data) => {
          const display = String(data.username ?? data.user_id ?? '').trim();
          this.currentUser.set(display || 'Unknown');
        },
        error: () => {
          this.currentUser.set('Unknown');
        }
      });
  }

  private loadDevUsers(): void {
    this.http.get<{ users?: DevUser[] }>('/api/v1/auth/dev-users/').subscribe({
      next: (data) => {
        const users = (data.users ?? []).filter((user) => !!user?.username).map((user) => ({
          user_id: String(user.user_id ?? '').trim(),
          username: String(user.username ?? '').trim(),
          email: user.email ?? null,
          roles: Array.isArray(user.roles) ? user.roles.map((role) => String(role).trim()).filter(Boolean) : []
        }));
        this.devUsers.set(users);

        const stored = String(localStorage.getItem(DEV_USER_STORAGE_KEY) ?? '').trim();
        if (!stored) {
          this.selectedDevUser.set('');
          return;
        }

        const exists = users.some((user) => user.username === stored);
        if (!exists) {
          localStorage.removeItem(DEV_USER_STORAGE_KEY);
          this.selectedDevUser.set('');
          return;
        }
        this.selectedDevUser.set(stored);
      },
      error: () => {
        this.devUsers.set([]);
        this.selectedDevUser.set('');
      }
    });
  }
}
