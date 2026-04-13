import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { AuthRbacService, OperationsCapabilities, TenantContextSummary } from '../replenishment/services/auth-rbac.service';
import { AppAccessService } from './app-access.service';

describe('AppAccessService', () => {
  function buildTenantContext(overrides: Partial<TenantContextSummary> = {}): TenantContextSummary {
    return {
      requested_tenant_id: null,
      active_tenant_id: 20,
      active_tenant_code: 'FFP',
      active_tenant_type: 'DIST',
      is_neoc: false,
      can_read_all_tenants: false,
      can_act_cross_tenant: false,
      memberships: [
        {
          tenant_id: 20,
          tenant_code: 'FFP',
          tenant_name: 'FFP',
          tenant_type: 'DIST',
          is_primary: true,
          access_level: 'ADMIN',
        },
      ],
      ...overrides,
    };
  }

  function buildOperationsCapabilities(
    overrides: Partial<OperationsCapabilities> = {},
  ): OperationsCapabilities {
    return {
      can_create_relief_request: false,
      can_create_relief_request_on_behalf: false,
      relief_request_submission_mode: null,
      default_requesting_tenant_id: null,
      allowed_origin_modes: [],
      ...overrides,
    };
  }

  function setup(options: {
    roles?: string[];
    permissions?: string[];
    tenantContext?: TenantContextSummary | null;
    operationsCapabilities?: OperationsCapabilities | null;
  } = {}) {
    TestBed.resetTestingModule();

    const auth = {
      roles: signal(options.roles ?? []),
      permissions: signal((options.permissions ?? []).map((permission) => permission.toLowerCase())),
      tenantContext: signal(
        options.tenantContext === undefined ? buildTenantContext() : options.tenantContext,
      ),
      operationsCapabilities: signal(
        options.operationsCapabilities === undefined
          ? buildOperationsCapabilities()
          : options.operationsCapabilities,
      ),
      hasPermission(permission: string) {
        return this.permissions().includes(permission.toLowerCase());
      },
    };

    TestBed.configureTestingModule({
      providers: [
        AppAccessService,
        { provide: AuthRbacService, useValue: auth },
      ],
    });

    return TestBed.inject(AppAccessService);
  }

  it('allows governed catalog access only for governance roles with masterdata.view', () => {
    const allowed = setup({
      roles: ['ODPEM_DG'],
      permissions: ['masterdata.view'],
      tenantContext: null,
    });

    expect(allowed.canAccessMasterDomain('catalogs')).toBeTrue();
    expect(allowed.canAccessMasterRoutePath('items')).toBeTrue();

    const denied = setup({
      roles: ['AGENCY_DISTRIBUTOR'],
      permissions: ['masterdata.view'],
      tenantContext: buildTenantContext(),
    });

    expect(denied.canAccessMasterDomain('catalogs')).toBeFalse();
    expect(denied.canAccessMasterRoutePath('items')).toBeFalse();
  });

  it('requires tenant scope for operational masters unless the user is a system administrator', () => {
    const tenantScoped = setup({
      roles: ['LOGISTICS_MANAGER'],
      permissions: ['masterdata.view'],
      tenantContext: buildTenantContext(),
    });

    expect(tenantScoped.canAccessMasterDomain('operational')).toBeTrue();
    expect(tenantScoped.canAccessMasterRoutePath('warehouses')).toBeTrue();

    const noTenantScope = setup({
      roles: ['LOGISTICS_MANAGER'],
      permissions: ['masterdata.view'],
      tenantContext: null,
    });

    expect(noTenantScope.canAccessMasterDomain('operational')).toBeFalse();
    expect(noTenantScope.canAccessMasterRoutePath('warehouses')).toBeFalse();

    const sysadmin = setup({
      roles: ['SYSTEM_ADMINISTRATOR'],
      permissions: ['masterdata.view', 'masterdata.create', 'masterdata.edit'],
      tenantContext: null,
    });

    expect(sysadmin.canAccessMasterDomain('operational')).toBeTrue();
    expect(sysadmin.canAccessMasterRoutePath('warehouses')).toBeTrue();
  });

  it('keeps legacy custodians inside operational masters while gating create/edit by RBAC', () => {
    const access = setup({
      roles: ['LOGISTICS_MANAGER'],
      permissions: ['masterdata.view', 'masterdata.create'],
      tenantContext: buildTenantContext(),
    });

    expect(access.canAccessMasterRoutePath('custodians')).toBeTrue();
    expect(access.isLegacyMasterRoutePath('custodians')).toBeTrue();
    expect(access.canCreateMasterRoutePath('custodians')).toBeTrue();
    expect(access.canEditMasterRoutePath('custodians')).toBeFalse();
  });

  it('uses operations capabilities to expose the relief-request navigation lane', () => {
    const access = setup({
      permissions: [],
      operationsCapabilities: buildOperationsCapabilities({
        can_create_relief_request: true,
        relief_request_submission_mode: 'self',
      }),
    });

    expect(access.canAccessNavKey('operations.relief-requests')).toBeTrue();
    expect(access.canAccessNavKey('operations.dashboard')).toBeTrue();
  });

  it('uses backend eligibility permissions to expose the eligibility lane without a frontend role allowlist', () => {
    const directorAccess = setup({
      roles: ['ODPEM_DIR_PEOD'],
      permissions: ['operations.eligibility.review'],
    });

    expect(directorAccess.canAccessNavKey('operations.eligibility')).toBeTrue();

    const compatibilityAccess = setup({
      roles: ['ODPEM_DIR_PEOD'],
      permissions: ['operations.eligibility.*'],
    });

    expect(compatibilityAccess.canAccessNavKey('operations.eligibility')).toBeTrue();

    const compatibilitySinglePermissionAccess = setup({
      roles: ['ODPEM_DIR_PEOD'],
      permissions: ['operations.eligibility'],
    });

    expect(compatibilitySinglePermissionAccess.canAccessNavKey('operations.eligibility')).toBeTrue();

    const logisticsAccess = setup({
      roles: ['LOGISTICS_MANAGER'],
      permissions: ['operations.eligibility.review'],
    });

    expect(logisticsAccess.canAccessNavKey('operations.eligibility')).toBeTrue();

    const roleWithoutPermission = setup({
      roles: ['ODPEM_DIR_PEOD'],
      permissions: [],
    });

    expect(roleWithoutPermission.canAccessNavKey('operations.eligibility')).toBeFalse();
  });

  it('allows system administrators into the eligibility lane when backend RBAC grants the permission', () => {
    const sysadminAccess = setup({
      roles: ['SYSTEM_ADMINISTRATOR'],
      permissions: ['operations.eligibility.review'],
    });

    expect(sysadminAccess.canAccessNavKey('operations.eligibility')).toBeTrue();
  });

  it('maps replenishment execution and procurement lanes to the backend RBAC permissions', () => {
    const access = setup({
      permissions: [
        'replenishment.needs_list.execute',
        'replenishment.procurement.view',
        'replenishment.procurement.edit',
      ],
    });

    expect(access.canAccessNavKey('replenishment.execution')).toBeTrue();
    expect(access.canAccessNavKey('replenishment.procurement.view')).toBeTrue();
    expect(access.canAccessNavKey('replenishment.procurement.edit')).toBeTrue();
    expect(access.canAccessNavKey('replenishment.procurement.receive')).toBeFalse();
  });
});
