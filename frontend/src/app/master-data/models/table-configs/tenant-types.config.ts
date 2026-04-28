import { MasterTableConfig } from '../master-data.models';

const STATUS_TONES = [
  { value: 'A', label: 'Active', tone: 'success', icon: 'check_circle' },
  { value: 'I', label: 'Inactive', tone: 'neutral', icon: 'radio_button_unchecked' },
] as const;

const BASELINE_TENANT_TYPE_OPTIONS = [
  { value: 'NATIONAL', label: 'National Coordination' },
  { value: 'MILITARY', label: 'Military' },
  { value: 'SOCIAL_SERVICES', label: 'Social Services' },
  { value: 'PARISH', label: 'Parish' },
  { value: 'COMMUNITY', label: 'Community' },
  { value: 'NGO', label: 'NGO' },
  { value: 'UTILITY', label: 'Utility' },
  { value: 'SHELTER_OPERATOR', label: 'Shelter Operator' },
  { value: 'PARTNER', label: 'Partner' },
];

export const TENANT_TYPES_CONFIG: MasterTableConfig = {
  tableKey: 'tenant_types',
  displayName: 'Tenant Types',
  icon: 'category',
  pkField: 'tenant_type_code',
  routePath: 'tenant-types',
  domain: 'advanced',
  formMode: 'page',
  searchPlaceholder: 'Search by code, name, or description',
  emptyState: {
    icon: 'category',
    title: 'No tenant types configured',
    message: 'Create the approved baseline tenant type rows before assigning tenant classifications.',
    actionIcon: 'add',
    actionLabel: 'Add Tenant Type',
  },
  columns: [
    { field: 'tenant_type_code', header: 'Code', type: 'text', sortable: true, monospace: true, semibold: true },
    { field: 'tenant_type_name', header: 'Name', type: 'text', sortable: true },
    { field: 'description', header: 'Description', type: 'text', sortable: false, hideMobile: true },
    { field: 'display_order', header: 'Order', type: 'number', sortable: true, hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true, toneMap: STATUS_TONES },
  ],
  formFields: [
    { field: 'tenant_type_code', label: 'Tenant Type Code', type: 'select', required: true,
      hint: 'Approved baseline code used by tenant records, access policy, and reporting.',
      options: BASELINE_TENANT_TYPE_OPTIONS,
      readonlyOnEdit: true, group: 'Identity' },
    { field: 'tenant_type_name', label: 'Name', type: 'text', required: true, maxLength: 120,
      hint: 'Readable name administrators see when classifying tenants.',
      placeholder: 'Shelter Operator',
      group: 'Identity' },
    { field: 'description', label: 'Description', type: 'textarea', maxLength: 500,
      hint: 'Operational purpose for this tenant classification.',
      placeholder: 'Organizations directly managing shelters.',
      group: 'Identity', colspan: 4 },
    { field: 'display_order', label: 'Display Order', type: 'number', defaultValue: 90,
      hint: 'Order used in tenant-type dropdowns and maintenance lists.',
      group: 'Display' },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      hint: 'Active tenant types can be selected; inactive rows remain for history.',
      options: STATUS_TONES.map(({ value, label }) => ({ value, label })),
      group: 'Status' },
  ],
};
