import { MasterTableConfig } from '../master-data.models';

const ACTION_TONES = [
  { values: ['VIEW', 'READ', 'LIST'], tone: 'neutral' },
  { values: ['CREATE', 'EDIT', 'UPDATE'], tone: 'info', icon: 'edit' },
  { values: ['DELETE', 'INACTIVATE', 'PURGE'], tone: 'critical', icon: 'delete_outline' },
  { values: ['APPROVE', 'DISPATCH', 'ACT_CROSS_TENANT'], tone: 'warning', icon: 'gavel' },
  { tone: 'neutral' },
] as const;

export const PERMISSIONS_CONFIG: MasterTableConfig = {
  tableKey: 'permission',
  displayName: 'Permissions',
  icon: 'key',
  pkField: 'perm_id',
  routePath: 'permissions',
  domain: 'advanced',
  formMode: 'page',
  hasStatus: false,
  searchPlaceholder: 'Search by resource or action (e.g. masterdata.advanced)',
  emptyState: {
    icon: 'key',
    title: 'No permissions defined',
    message: 'Permissions are seeded by migrations. Manual additions are rare.',
    actionIcon: 'add',
    actionLabel: 'Add Permission',
  },
  columns: [
    { field: 'resource', header: 'Resource', type: 'text', sortable: true },
    { field: 'action', header: 'Action', type: 'pill', sortable: true, toneMap: ACTION_TONES },
    { field: 'update_dtime', header: 'Updated', type: 'date', hideMobile: true },
  ],
  formFields: [
    { field: 'resource', label: 'Resource', type: 'text', required: true, maxLength: 40, readonlyOnEdit: true,
      hint: 'Dot-namespaced area, e.g. `masterdata.advanced`', group: 'Definition', colspan: 2 },
    { field: 'action', label: 'Action', type: 'text', required: true, maxLength: 32, readonlyOnEdit: true,
      hint: 'Verb. Common: view, create, edit, inactivate, approve, act_cross_tenant',
      group: 'Definition', colspan: 2 },
  ],
};
