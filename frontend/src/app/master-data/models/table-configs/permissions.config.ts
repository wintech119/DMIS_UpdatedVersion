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
    { field: 'resource', label: 'Resource', type: 'text', hint: 'System area this permission controls for roles and access checks.', placeholder: '(set on creation; locked once saved)', required: true, maxLength: 40, readonlyOnEdit: true, group: 'Definition', colspan: 2 },
    { field: 'action', label: 'Action', type: 'text', required: true, maxLength: 32, readonlyOnEdit: true,
      hint: 'Action this permission grants within the selected resource.',
      placeholder: '(set on creation; locked once saved)',
      group: 'Definition', colspan: 2 },
  ],
};
