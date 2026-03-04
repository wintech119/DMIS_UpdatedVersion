import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';

import { AuthRbacService } from '../../../replenishment/services/auth-rbac.service';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import {
  MASTER_DOMAIN_DEFINITIONS,
  MasterDomainDefinition,
  MasterDomainId,
  isMasterDomainId,
} from '../../models/master-domain-map';

interface ImplementedCard {
  kind: 'implemented';
  routePath: string;
  label: string;
  icon: string;
  readOnly: boolean;
  note?: string;
}

interface PlannedCard {
  kind: 'planned';
  tableName: string;
  label: string;
}

type DomainCard = ImplementedCard | PlannedCard;

@Component({
  selector: 'dmis-master-home',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatButtonModule,
    MatCardModule,
    MatIconModule,
  ],
  templateUrl: './master-home.component.html',
  styleUrl: './master-home.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterHomeComponent {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private destroyRef = inject(DestroyRef);
  private authRbac = inject(AuthRbacService);

  requestedDomain = signal<MasterDomainId>('catalogs');
  selectedDomain = signal<MasterDomainId>('catalogs');

  private readonly tableNotes: Record<string, string> = {
    inventory: 'Read-only for now. Manage source transactions and policies via operational workflows.',
    locations: 'No locations found yet. Create locations before running item-location assignment tests.',
  };

  isSystemAdmin = computed(() =>
    this.authRbac.roles().some((role) => String(role).trim().toUpperCase() === 'SYSTEM_ADMINISTRATOR'),
  );

  domains = computed(() =>
    MASTER_DOMAIN_DEFINITIONS.filter(
      (domain) => !domain.sysadminOnly || this.isSystemAdmin(),
    ),
  );

  activeDomain = computed<MasterDomainDefinition | null>(() => {
    const available = this.domains();
    if (!available.length) return null;
    return available.find((domain) => domain.id === this.selectedDomain()) ?? available[0];
  });

  showRestrictedDomainNotice = computed(() => {
    const requested = this.requestedDomain();
    const requestedDomain = MASTER_DOMAIN_DEFINITIONS.find((domain) => domain.id === requested);
    return Boolean(requestedDomain?.sysadminOnly && !this.isSystemAdmin());
  });

  activeCards = computed<DomainCard[]>(() => {
    const domain = this.activeDomain();
    if (!domain) return [];

    const implemented: ImplementedCard[] = domain.implementedRoutePaths
      .map((routePath) => {
        const config = ALL_TABLE_CONFIGS[routePath];
        if (!config) return null;
        const card: ImplementedCard = {
          kind: 'implemented',
          routePath,
          label: config.displayName,
          icon: config.icon,
          readOnly: Boolean(config.readOnly),
          note: this.tableNotes[routePath],
        };
        return card;
      })
      .filter((card): card is ImplementedCard => card != null);

    const planned: DomainCard[] = domain.plannedTables.map((tableName) => ({
      kind: 'planned',
      tableName,
      label: this.formatTableName(tableName),
    }));

    return [...implemented, ...planned];
  });

  constructor() {
    this.authRbac.load();
    this.route.queryParamMap.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((query) => {
      const requested = query.get('domain');
      if (isMasterDomainId(requested)) {
        this.requestedDomain.set(requested);
        this.selectedDomain.set(requested);
      } else {
        this.requestedDomain.set('catalogs');
        this.selectedDomain.set('catalogs');
      }
    });
  }

  setDomain(domainId: MasterDomainId): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { domain: domainId },
      queryParamsHandling: 'merge',
    });
  }

  createLink(routePath: string): string[] {
    return ['/master-data', routePath, 'new'];
  }

  listLink(routePath: string): string[] {
    return ['/master-data', routePath];
  }

  formatTableName(value: string): string {
    return value
      .split('_')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }
}
