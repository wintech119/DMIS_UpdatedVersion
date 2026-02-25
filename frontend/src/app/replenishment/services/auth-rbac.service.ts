import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';

interface WhoAmIResponse {
  user_id?: string | null;
  username?: string | null;
  roles?: string[];
  permissions?: string[];
}

@Injectable({
  providedIn: 'root'
})
export class AuthRbacService {
  private readonly http = inject(HttpClient);

  readonly roles = signal<string[]>([]);
  readonly permissions = signal<string[]>([]);
  readonly currentUserRef = signal<string | null>(null);
  readonly loading = signal(false);
  readonly loaded = signal(false);

  load(): void {
    if (this.loading() || this.loaded()) {
      return;
    }
    this.fetchWhoAmI();
  }

  refresh(): void {
    this.fetchWhoAmI();
  }

  hasPermission(permission: string): boolean {
    return this.permissions().includes(permission.toLowerCase());
  }

  private fetchWhoAmI(): void {
    this.loading.set(true);
    this.http.get<WhoAmIResponse>('/api/v1/auth/whoami/').subscribe({
      next: (data) => {
        const roles = [
          ...new Set((data.roles ?? []).map((role) => String(role).trim()).filter(Boolean))
        ];
        const permissions = [
          ...new Set(
            (data.permissions ?? [])
              .map((permission) => String(permission).trim().toLowerCase())
              .filter(Boolean)
          )
        ];
        const currentUserRef = String(data.username ?? data.user_id ?? '').trim();

        this.roles.set(roles);
        this.permissions.set(permissions);
        this.currentUserRef.set(currentUserRef || null);
        this.loaded.set(true);
        this.loading.set(false);
      },
      error: () => {
        this.roles.set([]);
        this.permissions.set([]);
        this.currentUserRef.set(null);
        this.loaded.set(true);
        this.loading.set(false);
      }
    });
  }
}
