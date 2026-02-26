import { Component, OnInit, computed, inject, signal, OnDestroy } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router, NavigationEnd, RouterOutlet, RouterLink } from '@angular/router';
import { Subscription, filter } from 'rxjs';
import { DmisDataFreshnessBannerComponent } from './replenishment/shared/dmis-data-freshness-banner/dmis-data-freshness-banner.component';
import { SidenavComponent } from './layout/sidenav/sidenav.component';

export interface DevUser {
  user_id: string;
  username: string;
  email?: string | null;
  roles: string[];
}

const DEV_USER_STORAGE_KEY = 'dmis_dev_user';

interface BreadcrumbSegment {
  label: string;
  route?: string;
}

/** Maps URL patterns to breadcrumb trails: [section, sub-page] */
const ROUTE_BREADCRUMBS: { pattern: RegExp; crumbs: (match: RegExpMatchArray) => BreadcrumbSegment[] }[] = [
  // Replenishment sub-pages
  { pattern: /^\/replenishment\/dashboard$/,              crumbs: () => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Stock Status Dashboard' }] },
  { pattern: /^\/replenishment\/my-submissions$/,         crumbs: () => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'My Drafts & Submissions' }] },
  { pattern: /^\/replenishment\/needs-list-wizard$/,      crumbs: () => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Needs List Wizard' }] },
  { pattern: /^\/replenishment\/needs-list-review$/,      crumbs: () => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Review Queue' }] },
  { pattern: /^\/replenishment\/needs-list-review\/(.+)$/,crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Review Queue', route: '/replenishment/needs-list-review' }, { label: `Review #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/wizard$/,crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Needs List Wizard' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/review$/,crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Review Queue', route: '/replenishment/needs-list-review' }, { label: `Review #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/track$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Fulfillment Tracker' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/history$/,crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'History' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/transfers$/,crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Transfer Drafts' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/donations$/,crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Donation Allocation' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/procurement$/,crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Procurement' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/procurement\/new$/,       crumbs: () => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Procurement Orders' }, { label: 'New Order' }] },
  { pattern: /^\/replenishment\/procurement\/(.+)\/edit$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Procurement Orders' }, { label: `Edit #${m[1]}` }] },
  { pattern: /^\/replenishment\/procurement\/(.+)\/receive$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Procurement Orders' }, { label: `Receive #${m[1]}` }] },
  { pattern: /^\/replenishment\/procurement\/(.+)$/,      crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Procurement Orders' }, { label: `Order #${m[1]}` }] },
  // Catch-all for replenishment
  { pattern: /^\/replenishment/,                          crumbs: () => [{ label: 'Supply Replenishment' }] },
  // Future sections
  { pattern: /^\/inventory/,                              crumbs: () => [{ label: 'Inventory' }] },
  { pattern: /^\/operations/,                             crumbs: () => [{ label: 'Operations' }] },
  { pattern: /^\/management/,                             crumbs: () => [{ label: 'Management' }] },
];

function buildBreadcrumbs(url: string): BreadcrumbSegment[] {
  for (const entry of ROUTE_BREADCRUMBS) {
    const match = url.match(entry.pattern);
    if (match) return entry.crumbs(match);
  }
  return [{ label: 'Home' }];
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    RouterOutlet,
    RouterLink,
    DmisDataFreshnessBannerComponent,
    SidenavComponent,
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit, OnDestroy {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private routerSub!: Subscription;

  title = 'dmis-frontend';
  readonly currentUser = signal('Unknown');
  readonly userRole = signal('');
  readonly devUsers = signal<DevUser[]>([]);
  readonly selectedDevUser = signal('');
  readonly canSwitchDevUser = computed(() => this.devUsers().length > 0);

  private readonly currentUrl = signal('/');

  readonly breadcrumbs = computed(() => {
    const url = this.currentUrl();
    return buildBreadcrumbs(url);
  });

  ngOnInit(): void {
    this.loadWhoAmI();
    this.loadDevUsers();

    this.routerSub = this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => this.currentUrl.set(e.urlAfterRedirects));
  }

  ngOnDestroy(): void {
    this.routerSub?.unsubscribe();
  }

  onNavItemClicked(): void {
    // Could close a mobile drawer here in the future
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
      .get<{ user_id?: string | null; username?: string | null; roles?: string[] }>('/api/v1/auth/whoami/')
      .subscribe({
        next: (data) => {
          const display = String(data.username ?? data.user_id ?? '').trim();
          this.currentUser.set(display || 'Unknown');
          const roles = data.roles ?? [];
          this.userRole.set(roles[0] ?? '');
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
