export type MasterDomainId =
  | 'catalogs'
  | 'operational'
  | 'policies'
  | 'tenant-access'
  | 'advanced';

export interface MasterDomainDefinition {
  id: MasterDomainId;
  label: string;
  icon: string;
  description: string;
  sysadminOnly?: boolean;
  implementedRoutePaths: string[];
  plannedTables: string[];
}

export const MASTER_DOMAIN_DEFINITIONS: MasterDomainDefinition[] = [
  {
    id: 'catalogs',
    label: 'Catalogs',
    icon: 'menu_book',
    description: 'Foundational reference data and item catalogs.',
    implementedRoutePaths: [
      'item-categories',
      'ifrc-families',
      'ifrc-item-references',
      'uom',
      'items',
      'countries',
      'currencies',
      'parishes',
      'events',
    ],
    plannedTables: [],
  },
  {
    id: 'operational',
    label: 'Operational Masters',
    icon: 'domain',
    description: 'Operational entities used by replenishment workflows.',
    implementedRoutePaths: [
      'inventory',
      'locations',
      'warehouses',
      'agencies',
      'custodians',
      'donors',
      'suppliers',
    ],
    plannedTables: ['lead_time_config'],
  },
  {
    id: 'policies',
    label: 'Policies',
    icon: 'policy',
    description: 'Approval, allocation, and workflow policy masters.',
    implementedRoutePaths: [],
    plannedTables: [
      'ref_event_phase',
      'ref_procurement_method',
      'ref_approval_tier',
      'reason_code_master',
      'approval_threshold_policy',
      'approval_authority_matrix',
      'workflow_transition_rule',
      'allocation_rule',
      'allocation_limit',
      'item_category_baseline_rate',
      'mpf_criteria_weight',
    ],
  },
  {
    id: 'tenant-access',
    label: 'Tenant & Access',
    icon: 'admin_panel_settings',
    description: 'Tenant structure and RBAC assignment masters.',
    implementedRoutePaths: [],
    plannedTables: [
      'ref_tenant_type',
      'tenant',
      'user_tenant_role',
    ],
  },
  {
    id: 'advanced',
    label: 'Advanced/System',
    icon: 'security',
    description: 'Restricted system and audit master/admin artifacts.',
    sysadminOnly: true,
    implementedRoutePaths: [],
    plannedTables: [
      'role_permission',
      'user_role',
      'user_warehouse',
      'event_phase_history',
      'warehouse_sync_log',
      'user',
      'role',
      'permission',
    ],
  },
];

const MASTER_DOMAIN_ID_SET = new Set<MasterDomainId>(
  MASTER_DOMAIN_DEFINITIONS.map((domain) => domain.id),
);

export function isMasterDomainId(value: string | null | undefined): value is MasterDomainId {
  if (!value) return false;
  return MASTER_DOMAIN_ID_SET.has(value as MasterDomainId);
}

export function getMasterDomainLabel(value: string | null | undefined): string | null {
  if (!isMasterDomainId(value)) return null;
  const domain = MASTER_DOMAIN_DEFINITIONS.find((entry) => entry.id === value);
  return domain?.label ?? null;
}
