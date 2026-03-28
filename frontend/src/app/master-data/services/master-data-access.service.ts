import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

import { AppAccessService } from '../../core/app-access.service';
import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';
import { MASTER_DOMAIN_DEFINITIONS, MasterDomainDefinition, MasterDomainId } from '../models/master-domain-map';

@Injectable({
  providedIn: 'root',
})
export class MasterDataAccessService {
  private readonly auth = inject(AuthRbacService);
  private readonly access = inject(AppAccessService);

  constructor() {
    this.auth.load();
  }

  waitForAuthReady(): Observable<void> {
    return this.auth.ensureLoaded().pipe(map(() => void 0));
  }

  isSystemAdmin(): boolean {
    return this.access.isSystemAdministrator();
  }

  isGlobalGovernanceUser(): boolean {
    return this.access.canAccessMasterDomain('catalogs');
  }

  hasTenantScopedAccess(): boolean {
    return this.access.canAccessMasterDomain('operational');
  }

  canAccessDomain(domainId: MasterDomainId | null | undefined): boolean {
    return !!domainId && this.access.canAccessMasterDomain(domainId);
  }

  canAccessRoutePath(routePath: string | null | undefined): boolean {
    const normalizedRoutePath = this.normalizeRoutePath(routePath);
    if (!normalizedRoutePath) {
      return false;
    }
    return this.access.canAccessMasterRoutePath(normalizedRoutePath);
  }

  canCreateRoutePath(routePath: string | null | undefined, readOnly = false): boolean {
    const normalizedRoutePath = this.normalizeRoutePath(routePath);
    if (!normalizedRoutePath) {
      return false;
    }
    return this.access.canCreateMasterRoutePath(normalizedRoutePath, readOnly);
  }

  canEditRoutePath(routePath: string | null | undefined, readOnly = false): boolean {
    const normalizedRoutePath = this.normalizeRoutePath(routePath);
    if (!normalizedRoutePath) {
      return false;
    }
    return this.access.canEditMasterRoutePath(normalizedRoutePath, readOnly);
  }

  canToggleStatusRoutePath(
    routePath: string | null | undefined,
    isActive: boolean,
    readOnly = false,
  ): boolean {
    const normalizedRoutePath = this.normalizeRoutePath(routePath);
    if (!normalizedRoutePath) {
      return false;
    }
    return this.access.canToggleMasterStatus(normalizedRoutePath, isActive, readOnly);
  }

  isLegacyRoutePath(routePath: string | null | undefined): boolean {
    const normalizedRoutePath = this.normalizeRoutePath(routePath);
    if (!normalizedRoutePath) {
      return false;
    }
    return this.access.isLegacyMasterRoutePath(normalizedRoutePath);
  }

  getAccessibleDomains(): MasterDomainDefinition[] {
    return MASTER_DOMAIN_DEFINITIONS.filter((domain) => this.canAccessDomain(domain.id));
  }

  getDefaultAccessibleDomain(): MasterDomainId | null {
    return this.getAccessibleDomains()[0]?.id ?? null;
  }

  private normalizeRoutePath(routePath: string | null | undefined): string {
    const normalized = String(routePath ?? '').trim();
    if (!normalized) {
      return '';
    }

    return normalized.split('/')[0];
  }
}
