import { MasterTableConfig } from '../master-data.models';

const STATUS_TONES = [
  { value: 'A', label: 'Active', tone: 'success', icon: 'check_circle' },
  { value: 'I', label: 'Inactive', tone: 'neutral', icon: 'radio_button_unchecked' },
] as const;
const TYPE_TONES = [
  { value: 'NEOC', tone: 'critical', icon: 'crisis_alert' },
  { value: 'NATIONAL_LEVEL', tone: 'warning', icon: 'account_balance' },
  { value: 'AGENCY', tone: 'info', icon: 'apartment' },
  { value: 'SHELTER', tone: 'success', icon: 'home' },
  { value: 'OTHER', tone: 'neutral' },
  { tone: 'neutral' },
] as const;
const TENANT_TYPES = ['NEOC', 'NATIONAL_LEVEL', 'AGENCY', 'SHELTER', 'OTHER'];

export const TENANTS_CONFIG: MasterTableConfig = {
  tableKey: 'tenant',
  displayName: 'Tenants',
  icon: 'domain',
  pkField: 'tenant_id',
  routePath: 'tenants',
  domain: 'advanced',
  formMode: 'page',
  searchPlaceholder: 'Search by code, name, or parent tenant',
  emptyState: {
    icon: 'domain',
    title: 'No tenants configured',
    message: 'At least one tenant is required for any user to operate. Start with the NEOC root tenant.',
    actionIcon: 'add',
    actionLabel: 'Add Tenant',
  },
  columns: [
    { field: 'tenant_code', header: 'Code', type: 'text', sortable: true, monospace: true, semibold: true },
    { field: 'tenant_name', header: 'Name', type: 'text', sortable: true, hideMobile: true },
    { field: 'tenant_type', header: 'Type', type: 'pill', sortable: true, toneMap: TYPE_TONES },
    { field: 'parent_tenant_id', header: 'Parent', type: 'text', prefixIcon: 'subdirectory_arrow_right',
      hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true, toneMap: STATUS_TONES },
  ],
  formFields: [
    { field: 'tenant_code', label: 'Tenant Code', type: 'text', required: true, maxLength: 20, uppercase: true,
      readonlyOnEdit: true, group: 'Identity', colspan: 4 },
    { field: 'tenant_name', label: 'Tenant Name', type: 'text', required: true, maxLength: 120, uppercase: true,
      group: 'Identity' },
    { field: 'tenant_type', label: 'Tenant Type', type: 'select', required: true,
      options: TENANT_TYPES.map((value) => ({ value, label: value.replace('_', ' ') })), group: 'Identity' },
    { field: 'parent_tenant_id', label: 'Parent Tenant', type: 'lookup', lookupTable: 'tenant',
      hint: 'Leave empty for top-level. Cycles will be rejected.', group: 'Identity' },
    { field: 'data_scope', label: 'Data Scope', type: 'select', defaultValue: 'OWN_DATA',
      options: ['OWN_DATA', 'PARISH_DATA', 'REGIONAL_DATA', 'NATIONAL_DATA'].map((value) => ({ value, label: value })),
      group: 'Data Governance' },
    { field: 'pii_access', label: 'PII Access', type: 'select', defaultValue: 'NONE',
      options: ['NONE', 'AGGREGATED', 'LIMITED', 'MASKED', 'FULL'].map((value) => ({ value, label: value })),
      group: 'Data Governance' },
    { field: 'offline_required', label: 'Offline Required', type: 'boolean', defaultValue: false,
      group: 'Data Governance' },
    { field: 'mobile_priority', label: 'Mobile Priority', type: 'boolean', defaultValue: false,
      group: 'Data Governance' },
    { field: 'address1_text', label: 'Address Line 1', type: 'text', maxLength: 255, group: 'Contact', colspan: 4 },
    { field: 'parish_code', label: 'Parish', type: 'lookup', lookupTable: 'parishes', group: 'Contact' },
    { field: 'contact_name', label: 'Contact Name', type: 'text', maxLength: 50, group: 'Contact' },
    { field: 'phone_no', label: 'Phone', type: 'phone', maxLength: 20, group: 'Contact' },
    { field: 'email_text', label: 'Email', type: 'email', maxLength: 100, group: 'Contact' },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: STATUS_TONES.map(({ value, label }) => ({ value, label })), group: 'Status', editOnly: true },
  ],
};
