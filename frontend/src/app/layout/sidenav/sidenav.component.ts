import { ChangeDetectorRef, Component, ChangeDetectionStrategy, output, input, inject, signal, OnInit, OnDestroy } from '@angular/core';
import { Router, NavigationEnd, RouterLink, RouterLinkActive } from '@angular/router';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatButtonModule } from '@angular/material/button';
import { Subscription, filter } from 'rxjs';
import { NAV_SECTIONS, NavSection, NavGroup, NavItem } from './nav-config';
import { DevUser } from '../../app.component';
import { AppAccessService } from '../../core/app-access.service';
import { MasterDataAccessService } from '../../master-data/services/master-data-access.service';

const COLLAPSED_STORAGE_KEY = 'dmis_sidenav_collapsed';

@Component({
  selector: 'app-sidenav',
  standalone: true,
  imports: [
    RouterLink,
    RouterLinkActive,
    MatExpansionModule,
    MatListModule,
    MatIconModule,
    MatTooltipModule,
    MatButtonModule,
  ],
  templateUrl: './sidenav.component.html',
  styleUrl: './sidenav.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SidenavComponent implements OnInit, OnDestroy {
  private readonly router = inject(Router);
  private readonly cdr = inject(ChangeDetectorRef);
  private readonly appAccess = inject(AppAccessService);
  private readonly masterDataAccess = inject(MasterDataAccessService);
  private routerSub!: Subscription;

  readonly navSections: NavSection[] = NAV_SECTIONS;
  readonly navItemClicked = output<void>();
  readonly switchUser = output<string>();
  readonly clearUser = output<void>();
  readonly currentUrl = signal(this.normalizeUrl(this.router.url));
  // Inputs from parent
  readonly currentUser = input('Unknown');
  readonly userRole = input('');
  readonly userRoles = input<string[]>([]);
  readonly devUsers = input<DevUser[]>([]);
  readonly selectedDevUser = input('');
  readonly canSwitchDevUser = input(false);

  readonly collapsed = signal(localStorage.getItem(COLLAPSED_STORAGE_KEY) === 'true');

  ngOnInit(): void {
    this.routerSub = this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => {
        this.currentUrl.set(this.normalizeUrl(e.urlAfterRedirects));
        this.cdr.markForCheck();
      });
  }

  ngOnDestroy(): void {
    this.routerSub?.unsubscribe();
  }

  toggleCollapsed(): void {
    const next = !this.collapsed();
    this.collapsed.set(next);
    localStorage.setItem(COLLAPSED_STORAGE_KEY, String(next));
  }

  isGroupActive(group: NavGroup): boolean {
    if (group.route && this.isRouteActive(group.route, group.queryParams)) {
      return true;
    }
    if (group.href && this.isHrefActive(group.href)) {
      return true;
    }
    return this.visibleChildren(group).some(
      (child) => (child.route && this.isRouteActive(child.route, child.queryParams))
        || (child.href && this.isHrefActive(child.href))
    );
  }

  visibleGroups(section: NavSection): NavGroup[] {
    return section.groups.filter((group) => {
      if (!this.canViewAccessKey(group.accessKey)) {
        return false;
      }
      if (!this.canViewSysadminOnly(group.sysadminOnly)) {
        return false;
      }
      if (!group.children?.length) {
        return true;
      }
      return this.visibleChildren(group).length > 0;
    });
  }

  visibleChildren(group: NavGroup) {
    return (group.children ?? []).filter((child) => this.canViewNavItem(child));
  }

  firstVisibleChild(group: NavGroup) {
    return this.visibleChildren(group).find((child) => !child.disabled && (!!child.route || !!child.href)) ?? null;
  }

  isRouteActive(route: string, queryParams?: Record<string, string | number | boolean>): boolean {
    const { path, params } = this.parseUrlParts(this.currentUrl());
    if (queryParams && Object.keys(queryParams).length > 0) {
      if (path !== route) return false;
      for (const [key, value] of Object.entries(queryParams)) {
        if (params.get(key) !== String(value)) {
          return false;
        }
      }
      return true;
    }
    return path === route || path.startsWith(route + '/');
  }

  isHrefActive(href: string): boolean {
    const { path } = this.parseUrlParts(this.currentUrl());
    return path === href || path.startsWith(href + '/');
  }

  onItemClick(): void {
    this.navItemClicked.emit();
  }

  onSwitchUser(username: string): void {
    this.switchUser.emit(username);
  }

  onClearUser(): void {
    this.clearUser.emit();
  }

  getGroupTooltip(group: NavGroup): string {
    return group.disabled ? `${group.label} (Coming Soon)` : group.label;
  }

  getChildTooltip(child: NavItem): string {
    return child.disabled ? `${child.label} (Coming Soon)` : child.label;
  }

  private canViewSysadminOnly(sysadminOnly?: boolean): boolean {
    if (!sysadminOnly) return true;
    return this.masterDataAccess.isSystemAdmin();
  }

  private canViewNavItem(item: NavItem): boolean {
    if (!this.canViewAccessKey(item.accessKey)) {
      return false;
    }
    if (!this.canViewSysadminOnly(item.sysadminOnly)) {
      return false;
    }
    if (item.masterDomain) {
      return this.masterDataAccess.canAccessDomain(item.masterDomain);
    }
    return true;
  }

  private canViewAccessKey(accessKey?: string): boolean {
    if (!accessKey) {
      return true;
    }
    return this.appAccess.canAccessNavKey(accessKey);
  }

  private normalizeUrl(url: string): string {
    const base = String(url ?? '').split('#')[0].trim();
    if (!base) {
      return '/';
    }
    return base.startsWith('/') ? base : `/${base}`;
  }

  private parseUrlParts(url: string): { path: string; params: URLSearchParams } {
    const [pathPart, queryPart = ''] = String(url ?? '').split('?');
    const path = pathPart || '/';
    return { path, params: new URLSearchParams(queryPart) };
  }
}
