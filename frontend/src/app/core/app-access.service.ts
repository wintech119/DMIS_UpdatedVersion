import { Injectable, computed, inject } from '@angular/core';

import { MasterDomainId } from '../master-data/models/master-domain-map';
import { AuthRbacService } from '../replenishment/services/auth-rbac.service';

const PERM_MASTERDATA_VIEW = 'masterdata.view';
const PERM_MASTERDATA_CREATE = 'masterdata.create';
const PERM_MASTERDATA_EDIT = 'masterdata.edit';
const PERM_MASTERDATA_INACTIVATE = 'masterdata.inactivate';

const GLOBAL_MASTER_ROUTE_PATHS = new Set([
  'item-categories',
  'ifrc-families',
  'ifrc-item-references',
  'items',
  'uom',
  'countries',
  'currencies',
  'parishes',
  'events',
]);

const OPERATIONAL_MASTER_ROUTE_PATHS = new Set([
  'inventory',
  'locations',
  'warehouses',
  'agencies',
  'custodians',
  'donors',
  'suppliers',
]);

const LEGACY_MASTER_ROUTE_PATHS = new Set([
  'custodians',
]);

const GLOBAL_MASTER_ROLE_CODES = new Set([
  'SYSTEM_ADMINISTRATOR',
  'ODPEM_DDG',
  'ODPEM_DG',
  'ODPEM_DIR_PEOD',
  'DG',
  'DIR_PEOD',
  'DIRECTOR_GENERAL',
  'TST_DG',
  'TST_DIR_PEOD',
  'TST_READONLY',
]);

const OPERATIONAL_MASTER_ROLE_CODES = new Set([
  'SYSTEM_ADMINISTRATOR',
  'LOGISTICS_OFFICER',
  'TST_LOGISTICS_OFFICER',
  'LOGISTICS_MANAGER',
  'TST_LOGISTICS_MANAGER',
  'ODPEM_LOGISTICS_MANAGER',
  'INVENTORY_CLERK',
  'TST_READONLY',
]);

const REPLENISHMENT_ANY_PERMISSIONS = [
  'replenishment.needs_list.preview',
  'replenishment.needs_list.create_draft',
  'replenishment.needs_list.edit_lines',
  'replenishment.needs_list.submit',
  'replenishment.needs_list.return',
  'replenishment.needs_list.reject',
  'replenishment.needs_list.approve',
  'replenishment.needs_list.escalate',
  'replenishment.needs_list.execute',
  'replenishment.needs_list.cancel',
  'replenishment.needs_list.review_comments',
];

const REPLENISHMENT_REVIEW_PERMISSIONS = [
  'replenishment.needs_list.approve',
  'replenishment.needs_list.reject',
  'replenishment.needs_list.return',
  'replenishment.needs_list.escalate',
  'replenishment.needs_list.review_comments',
];

const OPERATIONS_ANY_PERMISSIONS = [
  'operations.request.create.self',
  'operations.request.create.for_subordinate',
  'operations.request.create.on_behalf_bridge',
  'operations.request.edit.draft',
  'operations.request.submit',
  'operations.request.cancel',
  'operations.eligibility',
  'operations.eligibility.*',
  'operations.eligibility.review',
  'operations.eligibility.approve',
  'operations.eligibility.reject',
  'operations.package.create',
  'operations.package.lock',
  'operations.package.allocate',
  'operations.package.override.request',
  'operations.package.override.approve',
  'operations.dispatch.prepare',
  'operations.dispatch.execute',
  'operations.receipt.confirm',
  'operations.waybill.view',
  'operations.notification.receive',
  'operations.queue.view',
];

const OPERATIONS_REQUEST_PERMISSIONS = [
  'operations.request.create.self',
  'operations.request.create.for_subordinate',
  'operations.request.create.on_behalf_bridge',
  'operations.request.edit.draft',
  'operations.request.submit',
  'operations.request.cancel',
];

const OPERATIONS_ELIGIBILITY_PERMISSIONS = [
  'operations.eligibility',
  'operations.eligibility.*',
  'operations.eligibility.review',
  'operations.eligibility.approve',
  'operations.eligibility.reject',
];

const OPERATIONS_FULFILLMENT_PERMISSIONS = [
  'operations.package.create',
  'operations.package.lock',
  'operations.package.allocate',
  'operations.package.override.request',
  'operations.package.override.approve',
  'replenishment.needs_list.execute',
  'replenishment.needs_list.approve',
];

const OPERATIONS_DISPATCH_PERMISSIONS = [
  'operations.dispatch.prepare',
  'operations.dispatch.execute',
  'operations.receipt.confirm',
  'operations.waybill.view',
];

type NavAccessKey =
  | 'replenishment.dashboard'
  | 'replenishment.submissions'
  | 'replenishment.wizard'
  | 'replenishment.review'
  | 'replenishment.execution'
  | 'replenishment.procurement.view'
  | 'replenishment.procurement.edit'
  | 'replenishment.procurement.receive'
  | 'operations.dashboard'
  | 'operations.relief-requests'
  | 'operations.relief-requests.create'
  | 'operations.relief-requests.edit'
  | 'operations.eligibility'
  | 'operations.fulfillment'
  | 'operations.dispatch'
  | 'operations.tasks'
  | 'master.any'
  | 'master.catalogs'
  | 'master.operational'
  | 'master.advanced';

@Injectable({
  providedIn: 'root',
})
export class AppAccessService {
  private readonly auth = inject(AuthRbacService);

  readonly normalizedRoles = computed(() =>
    this.auth.roles().map((role) => this.normalizeToken(role)).filter(Boolean)
  );

  readonly isSystemAdministrator = computed(() => this.hasRole('SYSTEM_ADMINISTRATOR'));

  hasPermission(permission: string): boolean {
    return this.auth.hasPermission(permission);
  }

  hasRole(roleCode: string): boolean {
    const normalized = this.normalizeToken(roleCode);
    if (!normalized) {
      return false;
    }
    return this.normalizedRoles().includes(normalized);
  }

  canAccessNavKey(accessKey?: string): boolean {
    if (!accessKey) {
      return true;
    }

    switch (accessKey as NavAccessKey) {
      case 'replenishment.dashboard':
        return true;
      case 'replenishment.submissions':
        return this.hasAnyPermission(REPLENISHMENT_ANY_PERMISSIONS);
      case 'replenishment.wizard':
        return this.hasAnyPermission([
          'replenishment.needs_list.create_draft',
          'replenishment.needs_list.edit_lines',
          'replenishment.needs_list.submit',
        ]);
      case 'replenishment.review':
        return this.hasPermission('replenishment.needs_list.preview')
          && this.hasAnyPermission(REPLENISHMENT_REVIEW_PERMISSIONS);
      case 'replenishment.execution':
        return this.hasPermission('replenishment.needs_list.execute');
      case 'replenishment.procurement.view':
        return this.hasPermission('replenishment.procurement.view');
      case 'replenishment.procurement.edit':
        return this.hasPermission('replenishment.procurement.view')
          && this.hasPermission('replenishment.procurement.edit');
      case 'replenishment.procurement.receive':
        return this.hasPermission('replenishment.procurement.view')
          && this.hasPermission('replenishment.procurement.receive');
      case 'operations.dashboard':
        return this.canAccessAnyOperations();
      case 'operations.relief-requests':
        return this.canAccessReliefRequests();
      case 'operations.relief-requests.create':
        return this.canCreateReliefRequest();
      case 'operations.relief-requests.edit':
        return this.canEditReliefRequestDraft();
      case 'operations.eligibility':
        return this.canAccessEligibility();
      case 'operations.fulfillment':
        return this.hasAnyPermission(OPERATIONS_FULFILLMENT_PERMISSIONS);
      case 'operations.dispatch':
        return this.hasAnyPermission(OPERATIONS_DISPATCH_PERMISSIONS);
      case 'operations.tasks':
        return this.hasAnyPermission([
          'operations.notification.receive',
          'operations.queue.view',
        ]);
      case 'master.any':
        return this.canAccessAnyMasterData();
      case 'master.catalogs':
        return this.canAccessMasterDomain('catalogs');
      case 'master.operational':
        return this.canAccessMasterDomain('operational');
      case 'master.advanced':
        return this.isSystemAdministrator();
      default:
        return false;
    }
  }

  canAccessMasterDomain(domainId: MasterDomainId): boolean {
    switch (domainId) {
      case 'catalogs':
        return this.canAccessGlobalMasters();
      case 'operational':
        return this.canAccessOperationalMasters();
      case 'advanced':
        return this.isSystemAdministrator();
      case 'policies':
      case 'tenant-access':
        return false;
      default:
        return false;
    }
  }

  canAccessMasterRoutePath(routePath: string): boolean {
    if (GLOBAL_MASTER_ROUTE_PATHS.has(routePath)) {
      return this.canAccessGlobalMasters();
    }
    if (OPERATIONAL_MASTER_ROUTE_PATHS.has(routePath)) {
      return this.canAccessOperationalMasters();
    }
    return this.isSystemAdministrator();
  }

  canCreateMasterRoutePath(routePath: string, readOnly = false): boolean {
    if (readOnly) {
      return false;
    }
    return this.canAccessMasterRoutePath(routePath) && this.hasPermission(PERM_MASTERDATA_CREATE);
  }

  canEditMasterRoutePath(routePath: string, readOnly = false): boolean {
    if (readOnly) {
      return false;
    }
    return this.canAccessMasterRoutePath(routePath) && this.hasPermission(PERM_MASTERDATA_EDIT);
  }

  canToggleMasterStatus(routePath: string, isActive: boolean, readOnly = false): boolean {
    if (readOnly || !this.canAccessMasterRoutePath(routePath)) {
      return false;
    }
    if (isActive) {
      return this.hasPermission(PERM_MASTERDATA_INACTIVATE);
    }
    return this.hasPermission(PERM_MASTERDATA_EDIT);
  }

  isLegacyMasterRoutePath(routePath: string): boolean {
    return LEGACY_MASTER_ROUTE_PATHS.has(routePath);
  }

  private canAccessAnyOperations(): boolean {
    return this.canAccessReliefRequests() || this.hasAnyPermission(OPERATIONS_ANY_PERMISSIONS);
  }

  private canAccessReliefRequests(): boolean {
    const capabilities = this.auth.operationsCapabilities();
    return Boolean(capabilities?.can_create_relief_request)
      || Boolean(capabilities?.can_create_relief_request_on_behalf)
      || this.hasAnyPermission(OPERATIONS_REQUEST_PERMISSIONS)
      || this.hasPermission('operations.queue.view');
  }

  private canCreateReliefRequest(): boolean {
    // Backend RBAC is the source of truth. These checks only shape UX for the
    // create route so read-only viewers aren't deep-linked into the wizard.
    const capabilities = this.auth.operationsCapabilities();
    return Boolean(capabilities?.can_create_relief_request)
      || Boolean(capabilities?.can_create_relief_request_on_behalf)
      || this.hasAnyPermission([
        'operations.request.create.self',
        'operations.request.create.for_subordinate',
        'operations.request.create.on_behalf_bridge',
      ]);
  }

  canEditReliefRequestDraft(): boolean {
    return this.hasPermission('operations.request.edit.draft');
  }

  canSubmitReliefRequest(): boolean {
    return this.hasPermission('operations.request.submit');
  }

  canCancelReliefRequest(): boolean {
    return this.hasPermission('operations.request.cancel');
  }

  private canAccessEligibility(): boolean {
    // Backend RBAC is the source of truth for eligibility visibility. Do not
    // add frontend-only role allowlists here because they can drift from the
    // permissions returned by `/auth/whoami/`.
    // TODO(dmis-auth-contract): If eligibility lane shaping needs more than
    // permission-based gating, expose that policy from the backend contract.
    return this.hasAnyPermission(OPERATIONS_ELIGIBILITY_PERMISSIONS);
  }

  private canAccessAnyMasterData(): boolean {
    return this.canAccessGlobalMasters()
      || this.canAccessOperationalMasters()
      || this.isSystemAdministrator();
  }

  private canAccessGlobalMasters(): boolean {
    return this.hasPermission(PERM_MASTERDATA_VIEW)
      && this.hasAnyRole(GLOBAL_MASTER_ROLE_CODES);
  }

  private canAccessOperationalMasters(): boolean {
    if (this.isSystemAdministrator()) {
      return this.hasPermission(PERM_MASTERDATA_VIEW);
    }
    return this.hasPermission(PERM_MASTERDATA_VIEW)
      && this.hasAnyRole(OPERATIONAL_MASTER_ROLE_CODES)
      && this.hasOperationalTenantScope();
  }

  private hasOperationalTenantScope(): boolean {
    const context = this.auth.tenantContext();
    if (!context) {
      return false;
    }
    return context.active_tenant_id != null
      || context.memberships.length > 0
      || context.can_act_cross_tenant
      || context.can_read_all_tenants;
  }

  private hasAnyPermission(permissions: readonly string[]): boolean {
    return permissions.some((permission) => this.hasPermission(permission));
  }

  private hasAnyRole(roleCodes: ReadonlySet<string>): boolean {
    const roles = this.normalizedRoles();
    return roles.some((role) => roleCodes.has(role));
  }

  private normalizeToken(value: unknown): string {
    return String(value ?? '').trim().toUpperCase();
  }
}
