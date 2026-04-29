import { MasterTableConfig } from '../master-data.models';

const ROLE_TONES = [
  { value: 'SYSTEM_ADMINISTRATOR', tone: 'warning', icon: 'shield' },
  { startsWith: 'NATIONAL_', tone: 'info', icon: 'language' },
  { tone: 'neutral' },
] as const;

export const ROLES_CONFIG: MasterTableConfig = {
  tableKey: 'role',
  displayName: 'Roles',
  icon: 'assignment_ind',
  pkField: 'id',
  routePath: 'roles',
  domain: 'advanced',
  formMode: 'page',
  hasStatus: false,
  searchPlaceholder: 'Search by code or name',
  emptyState: {
    icon: 'assignment_ind',
    title: 'No roles defined',
    message: 'Roles bundle permissions. Create one before assigning users.',
    actionIcon: 'add',
    actionLabel: 'Add Role',
  },
  columns: [
    { field: 'code', header: 'Code', type: 'pill', sortable: true, monospace: true, toneMap: ROLE_TONES },
    { field: 'name', header: 'Name', type: 'text', sortable: true },
    { field: 'description', header: 'Description', type: 'text', truncate: 80, hideMobile: true },
  ],
  formFields: [
    { field: 'code', label: 'Code', type: 'text', required: true, maxLength: 50, uppercase: true,
      hint: 'Canonical role key used by RBAC and route access checks.',
      placeholder: '(set on creation; locked once saved)',
      readonlyOnEdit: true, pattern: '^[A-Z_][A-Z0-9_]*$',
      patternMessage: 'Only uppercase letters, digits, and underscores are allowed.', group: 'Identity', colspan: 2 },
    { field: 'name', label: 'Name', type: 'text', required: true, maxLength: 100,
      hint: 'Readable role name shown to administrators when assigning access.',
      placeholder: 'Logistics Manager',
      group: 'Identity', colspan: 2 },
    { field: 'description', label: 'Description', type: 'textarea', hint: 'Operational scope this role grants, for access review.', placeholder: 'Approves needs lists and manages warehouse stock', group: 'Identity', colspan: 4 },
  ],
};
