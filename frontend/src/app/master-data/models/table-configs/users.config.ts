import { MasterTableConfig } from '../master-data.models';

const STATUS_TONES = [
  { value: 'A', label: 'Active', tone: 'success', icon: 'check_circle' },
  { value: 'I', label: 'Inactive', tone: 'neutral', icon: 'radio_button_unchecked' },
  { value: 'L', label: 'Locked', tone: 'critical', icon: 'lock' },
] as const;

export const USERS_CONFIG: MasterTableConfig = {
  tableKey: 'user',
  displayName: 'Users',
  icon: 'manage_accounts',
  pkField: 'user_id',
  routePath: 'users',
  domain: 'advanced',
  formMode: 'page',
  searchPlaceholder: 'Search by username, email, or full name',
  emptyState: {
    icon: 'person_off',
    title: 'No users yet',
    message: 'Users are auto-provisioned on first Keycloak login.',
    actionIcon: 'add',
    actionLabel: 'Add User',
  },
  columns: [
    { field: 'username', header: 'Username', type: 'text', sortable: true, monospace: true },
    { field: 'full_name', header: 'Full Name', type: 'text', sortable: true },
    { field: 'agency_id', header: 'Agency', type: 'text', sortable: true, hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true, toneMap: STATUS_TONES },
  ],
  formFields: [
    { field: 'username', label: 'Username', type: 'text', required: true, maxLength: 60, readonlyOnEdit: true,
      hint: 'External Keycloak identity. Cannot rename.', group: 'Identity', colspan: 2 },
    { field: 'email', label: 'Email', type: 'email', required: true, maxLength: 200, group: 'Identity', colspan: 2 },
    { field: 'first_name', label: 'First Name', type: 'text', maxLength: 100, group: 'Identity' },
    { field: 'last_name', label: 'Last Name', type: 'text', maxLength: 100, group: 'Identity' },
    { field: 'full_name', label: 'Full Name', type: 'text', maxLength: 200, group: 'Identity', colspan: 2 },
    { field: 'assigned_warehouse_id', label: 'Assigned Warehouse', type: 'lookup', lookupTable: 'warehouses',
      group: 'Operational' },
    { field: 'agency_id', label: 'Agency', type: 'lookup', lookupTable: 'agencies', group: 'Operational' },
    { field: 'is_active', label: 'Active', type: 'boolean', defaultValue: true, group: 'Operational' },
    { field: 'phone', label: 'Phone', type: 'phone', maxLength: 50,
      hint: 'Mobile preferred for SURGE alerts', group: 'Locale' },
    { field: 'timezone', label: 'Timezone', type: 'text', required: true, maxLength: 50,
      defaultValue: 'America/Jamaica', group: 'Locale' },
    { field: 'language', label: 'Language', type: 'text', required: true, maxLength: 10, defaultValue: 'en',
      group: 'Locale' },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: STATUS_TONES.map(({ value, label }) => ({ value, label })),
      valueHints: [{ value: 'L', hint: 'Locked accounts cannot log in. Reset password to unlock.' }],
      group: 'Status', editOnly: true },
  ],
};
