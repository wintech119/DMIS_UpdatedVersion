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
import { MatIconModule } from '@angular/material/icon';

import { AuthRbacService } from '../../../replenishment/services/auth-rbac.service';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import {
  MasterDomainDefinition,
  MasterDomainId,
  isMasterDomainId,
} from '../../models/master-domain-map';
import { MasterDataAccessService } from '../../services/master-data-access.service';
import { MasterDataCardComponent } from '../master-data-card/master-data-card.component';

interface ImplementedCard {
  kind: 'implemented';
  routePath: string;
  label: string;
  icon: string;
  readOnly: boolean;
  canCreate: boolean;
  canEdit: boolean;
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
    MatIconModule,
    MasterDataCardComponent,
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
  private masterDataAccess = inject(MasterDataAccessService);

  requestedDomain = signal<MasterDomainId | null>(null);
  authLoaded = computed(() => this.authRbac.loaded());

  private readonly tableNotes: Record<string, string> = {
    'item-categories': 'Govern the Level 1 DMIS business categories used by item classification and reporting.',
    'ifrc-families': 'Maintain Level 2 IFRC families and keep each family aligned to one Level 1 category.',
    'ifrc-item-references': 'Maintain Level 3 IFRC references, including spec attributes used during match review.',
    inventory: 'Read-only for now. Manage source transactions and policies via operational workflows.',
    locations: 'No locations found yet. Create locations before running item-location assignment tests.',
    custodians: 'Legacy/deprecated master retained for compatibility with older operational workflows.',
  };

  domains = computed(() =>
    this.masterDataAccess.getAccessibleDomains(),
  );

  activeDomain = computed<MasterDomainDefinition | null>(() => {
    const available = this.domains();
    if (!available.length) return null;
    const requested = this.requestedDomain();
    if (requested) {
      const matched = available.find((domain) => domain.id === requested);
      if (matched) {
        return matched;
      }
    }
    return available[0];
  });

  accessNotice = computed(() => {
    if (!this.authLoaded()) {
      return null;
    }
    const requested = this.requestedDomain();
    if (!requested) {
      return null;
    }

    if (this.masterDataAccess.canAccessDomain(requested)) {
      return null;
    }

    switch (requested) {
      case 'advanced':
        return 'Advanced/System masters are restricted to System Administrator access. Showing the first accessible domain instead.';
      case 'catalogs':
      case 'policies':
      case 'tenant-access':
        return 'This governance domain is restricted to ODPEM/global governance access. Showing the first accessible domain instead.';
      default:
        return 'The requested master data domain is not available in your current tenant context. Showing the first accessible domain instead.';
    }
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
          canCreate: this.masterDataAccess.canCreateRoutePath(routePath, Boolean(config.readOnly)),
          canEdit: this.masterDataAccess.canEditRoutePath(routePath, Boolean(config.readOnly)),
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
      } else {
        this.requestedDomain.set(null);
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

  navigate(routePath: string): void {
    if (!this.masterDataAccess.canAccessRoutePath(routePath)) {
      return;
    }
    this.router.navigate(['/master-data', routePath]);
  }

  create(routePath: string): void {
    const config = ALL_TABLE_CONFIGS[routePath];
    if (!this.masterDataAccess.canCreateRoutePath(routePath, Boolean(config?.readOnly))) {
      return;
    }
    if (config?.formMode === 'dialog') {
      this.router.navigate(['/master-data', routePath], {
        queryParams: { open: 'new' },
      });
      return;
    }

    this.router.navigate(['/master-data', routePath, 'new']);
  }

  formatTableName(value: string): string {
    return value
      .split('_')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }
}
