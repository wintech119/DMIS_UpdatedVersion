import { Component, ChangeDetectionStrategy, output, input, inject, signal, OnInit, OnDestroy } from '@angular/core';
import { Router, NavigationEnd, RouterLink, RouterLinkActive } from '@angular/router';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatButtonModule } from '@angular/material/button';
import { Subscription, filter } from 'rxjs';
import { NAV_SECTIONS, NavSection, NavGroup } from './nav-config';
import { DevUser } from '../../app.component';

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
  private routerSub!: Subscription;

  readonly navSections: NavSection[] = NAV_SECTIONS;
  readonly navItemClicked = output<void>();
  readonly switchUser = output<string>();
  readonly clearUser = output<void>();
  readonly currentUrl = signal(this.normalizePath(this.router.url));
  // Inputs from parent
  readonly currentUser = input('Unknown');
  readonly userRole = input('');
  readonly devUsers = input<DevUser[]>([]);
  readonly selectedDevUser = input('');
  readonly canSwitchDevUser = input(false);

  readonly collapsed = signal(localStorage.getItem(COLLAPSED_STORAGE_KEY) === 'true');

  ngOnInit(): void {
    this.routerSub = this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe((e) => this.currentUrl.set(this.normalizePath(e.urlAfterRedirects)));
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
    const url = this.currentUrl();
    if (group.route) {
      return url === group.route || url.startsWith(group.route + '/');
    }
    return !!group.children?.some(
      (child) => child.route && (url === child.route || url.startsWith(child.route + '/'))
    );
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

  private normalizePath(url: string): string {
    const base = String(url ?? '').split('?')[0].split('#')[0].trim();
    if (!base) {
      return '/';
    }
    return base.startsWith('/') ? base : `/${base}`;
  }
}
