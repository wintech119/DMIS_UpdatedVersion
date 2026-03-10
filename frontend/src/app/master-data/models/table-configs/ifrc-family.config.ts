import { MasterTableConfig } from '../master-data.models';

export const IFRC_FAMILY_CONFIG: MasterTableConfig = {
  tableKey: 'ifrc_families',
  displayName: 'IFRC Families',
  icon: 'account_tree',
  pkField: 'ifrc_family_id',
  routePath: 'ifrc-families',
  formMode: 'dialog',
  searchPlaceholder: 'Search by group, family code, or family label...',
  columns: [
    { field: 'ifrc_family_id', header: 'ID', type: 'number', sortable: true, hideMobile: true },
    { field: 'group_code', header: 'Group Code', type: 'text', sortable: true },
    { field: 'group_label', header: 'Group Label', type: 'text', sortable: true, hideMobile: true },
    { field: 'family_code', header: 'Family Code', type: 'text', sortable: true },
    { field: 'family_label', header: 'Family Label', type: 'text', sortable: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    {
      field: 'category_id',
      label: 'Level 1 Category',
      type: 'lookup',
      required: true,
      lookupTable: 'item_categories',
    },
    { field: 'group_code', label: 'Group Code', type: 'text', required: true, maxLength: 4, uppercase: true },
    { field: 'group_label', label: 'Group Label', type: 'text', required: true, maxLength: 120 },
    { field: 'family_code', label: 'Family Code', type: 'text', required: true, maxLength: 6, uppercase: true },
    { field: 'family_label', label: 'Family Label', type: 'text', required: true, maxLength: 160 },
    { field: 'source_version', label: 'Source Version', type: 'text', maxLength: 80 },
    {
      field: 'status_code',
      label: 'Status',
      type: 'select',
      required: true,
      defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
    },
  ],
};
