import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { Router, NavigationEnd, RouterLink, RouterOutlet } from '@angular/router';
import { Subscription, filter } from 'rxjs';

import { AuthSessionService } from './core/auth-session.service';
import { SidenavComponent } from './layout/sidenav/sidenav.component';
import { DmisLocalHarnessSwitcherComponent } from './local-harness-switcher.component';
import { getMasterDomainLabel } from './master-data/models/master-domain-map';
import { DmisDataFreshnessBannerComponent } from './replenishment/shared/dmis-data-freshness-banner/dmis-data-freshness-banner.component';
import { AuthRbacService } from './replenishment/services/auth-rbac.service';

interface BreadcrumbSegment {
  label: string;
  route?: string;
}

/** Maps URL patterns to breadcrumb trails: [section, sub-page] */
const ROUTE_BREADCRUMBS: { pattern: RegExp; crumbs: (match: RegExpMatchArray) => BreadcrumbSegment[] }[] = [
  { pattern: /^\/replenishment\/dashboard$/, crumbs: () => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Stock Status Dashboard' }] },
  { pattern: /^\/replenishment\/my-submissions$/, crumbs: () => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'My Drafts & Submissions' }] },
  { pattern: /^\/replenishment\/needs-list-wizard$/, crumbs: () => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Needs List Wizard' }] },
  { pattern: /^\/replenishment\/needs-list-review$/, crumbs: () => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Review Queue' }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/wizard$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Needs List Wizard' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/review$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Review Queue', route: '/replenishment/needs-list-review' }, { label: `Review #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/transfers$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Transfer Drafts' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/donations$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Donation Allocation' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/needs-list\/(.+)\/procurement$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Procurement' }, { label: `List #${m[1]}` }] },
  { pattern: /^\/replenishment\/procurement\/(.+)\/edit$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Procurement Orders' }, { label: `Edit #${m[1]}` }] },
  { pattern: /^\/replenishment\/procurement\/(.+)\/receive$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Procurement Orders' }, { label: `Receive #${m[1]}` }] },
  { pattern: /^\/replenishment\/procurement\/(.+)$/, crumbs: (m) => [{ label: 'Supply Replenishment', route: '/replenishment/dashboard' }, { label: 'Procurement Orders' }, { label: `Order #${m[1]}` }] },
  { pattern: /^\/replenishment/, crumbs: () => [{ label: 'Supply Replenishment' }] },
  { pattern: /^\/operations\/dashboard$/, crumbs: () => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Dashboard' }] },
  { pattern: /^\/operations\/tasks$/, crumbs: () => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Task Center' }] },
  { pattern: /^\/operations\/relief-requests\/new$/, crumbs: () => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Relief Requests', route: '/operations/relief-requests' }, { label: 'New' }] },
  { pattern: /^\/operations\/relief-requests\/(.+)\/edit$/, crumbs: (m) => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Relief Requests', route: '/operations/relief-requests' }, { label: `Request #${m[1]}`, route: `/operations/relief-requests/${m[1]}` }, { label: 'Edit' }] },
  { pattern: /^\/operations\/relief-requests\/(.+)$/, crumbs: (m) => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Relief Requests', route: '/operations/relief-requests' }, { label: `Request #${m[1]}` }] },
  { pattern: /^\/operations\/relief-requests$/, crumbs: () => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Relief Requests' }] },
  { pattern: /^\/operations\/eligibility-review\/(.+)$/, crumbs: (m) => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Eligibility Review', route: '/operations/eligibility-review' }, { label: `Review #${m[1]}` }] },
  { pattern: /^\/operations\/eligibility-review$/, crumbs: () => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Eligibility Review' }] },
  { pattern: /^\/operations\/package-fulfillment\/(.+)$/, crumbs: (m) => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Package Fulfillment', route: '/operations/package-fulfillment' }, { label: `Package #${m[1]}` }] },
  { pattern: /^\/operations\/package-fulfillment$/, crumbs: () => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Package Fulfillment' }] },
  { pattern: /^\/operations\/dispatch\/(.+)\/waybill$/, crumbs: (m) => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Dispatch', route: '/operations/dispatch' }, { label: `Package #${m[1]}`, route: `/operations/dispatch/${m[1]}` }, { label: 'Waybill' }] },
  { pattern: /^\/operations\/dispatch\/(.+)$/, crumbs: (m) => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Dispatch', route: '/operations/dispatch' }, { label: `Package #${m[1]}` }] },
  { pattern: /^\/operations\/dispatch$/, crumbs: () => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Dispatch' }] },
  { pattern: /^\/operations\/receipt-confirmation\/(.+)$/, crumbs: (m) => [{ label: 'Operations', route: '/operations/dashboard' }, { label: 'Receipt Confirmation', route: '/operations/dispatch' }, { label: `Package #${m[1]}` }] },
  { pattern: /^\/operations/, crumbs: () => [{ label: 'Operations' }] },
  { pattern: /^\/master-data\/([^/]+)\/new$/, crumbs: (m) => [{ label: 'Master Data', route: '/master-data' }, { label: formatRoutePath(m[1]), route: `/master-data/${m[1]}` }, { label: 'New' }] },
  { pattern: /^\/master-data\/([^/]+)\/([^/]+)\/edit$/, crumbs: (m) => [{ label: 'Master Data', route: '/master-data' }, { label: formatRoutePath(m[1]), route: `/master-data/${m[1]}` }, { label: `#${m[2]}`, route: `/master-data/${m[1]}/${m[2]}` }, { label: 'Edit' }] },
  { pattern: /^\/master-data\/([^/]+)\/([^/]+)$/, crumbs: (m) => [{ label: 'Master Data', route: '/master-data' }, { label: formatRoutePath(m[1]), route: `/master-data/${m[1]}` }, { label: `#${m[2]}` }] },
  { pattern: /^\/master-data\/([^/]+)$/, crumbs: (m) => [{ label: 'Master Data', route: '/master-data' }, { label: formatRoutePath(m[1]) }] },
  { pattern: /^\/master-data/, crumbs: () => [{ label: 'Master Data' }] },
];

function formatRoutePath(path: string): string {
  return path.replace(/-/g, ' ').replace(/\b\w/g, (value) => value.toUpperCase());
}

function buildBreadcrumbs(url: string): BreadcrumbSegment[] {
  let normalized = String(url || '').trim();
  if (!normalized) {
    normalized = '/';
  } else if (!normalized.startsWith('/')) {
    normalized = `/${normalized}`;
  }

  const [path, queryString = ''] = normalized.replace(/#.*$/, '').split('?');
  if (path === '/master-data') {
    const query = new URLSearchParams(queryString);
    const domainLabel = getMasterDomainLabel(query.get('domain'));
    if (domainLabel) {
      return [
        { label: 'Master Data', route: '/master-data' },
        { label: domainLabel },
      ];
    }
    return [{ label: 'Master Data' }];
  }

  for (const entry of ROUTE_BREADCRUMBS) {
    const match = path.match(entry.pattern);
    if (match) {
      return entry.crumbs(match);
    }
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
    DmisLocalHarnessSwitcherComponent,
    SidenavComponent,
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit, OnDestroy {
  private readonly router = inject(Router);
  private readonly authSession = inject(AuthSessionService);
  private readonly authRbac = inject(AuthRbacService);
  private routerSub!: Subscription;

  readonly currentUser = computed(() => this.authRbac.currentUserRef() ?? this.authRbac.actorRef() ?? 'Unknown');
  readonly userRoles = computed(() => this.authRbac.roles());
  readonly userRole = computed(() => this.userRoles()[0] ?? '');
  private readonly currentUrl = signal(this.normalizeUrl(this.router.url));

  readonly breadcrumbs = computed(() => buildBreadcrumbs(this.currentUrl()));
  readonly showShellChrome = computed(() => !this.currentUrl().startsWith('/auth/'));
  readonly showLogout = computed(() => this.showShellChrome() && this.authSession.logoutAvailable());

  ngOnInit(): void {
    this.routerSub = this.router.events
      .pipe(filter((event): event is NavigationEnd => event instanceof NavigationEnd))
      .subscribe((event) => this.currentUrl.set(this.normalizeUrl(event.urlAfterRedirects)));
  }

  ngOnDestroy(): void {
    this.routerSub?.unsubscribe();
  }

  async signOut(): Promise<void> {
    await this.authSession.logout();
  }

  private normalizeUrl(url: string): string {
    const normalized = String(url ?? '').trim();
    if (!normalized) {
      return '/';
    }
    return normalized.startsWith('/') ? normalized : `/${normalized}`;
  }
}
