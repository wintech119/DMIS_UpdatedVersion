import { MasterTableConfig } from '../master-data.models';

export const IFRC_FAMILY_CONFIG: MasterTableConfig = {
  tableKey: 'ifrc_families',
  displayName: 'IFRC Families',
  icon: 'account_tree',
  pkField: 'ifrc_family_id',
  routePath: 'ifrc-families',
  formMode: 'dialog',
  formDescription:
    'IFRC Families are Level 2 product groupings within a Level 1 category. ' +
    'Each family has a short Group Code (the broad area, e.g. "F" for Food) and a ' +
    'Family Code (the specific sub-group, e.g. "GRAIN"). Items are classified under ' +
    'a family before selecting a Level 3 reference.',
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
      hint: 'The DMIS business category this family belongs to (e.g. Medical Supplies, Food).',
    },
    {
      field: 'group_code',
      label: 'Group Code',
      type: 'text',
      required: true,
      maxLength: 4,
      uppercase: true,
      hint: 'Short 1-4 letter code for the broad product area. Examples: F (Food), W (Water), M (Medical), S (Shelter).',
    },
    {
      field: 'group_label',
      label: 'Group Label',
      type: 'text',
      required: true,
      maxLength: 120,
      hint: 'Human-readable name for the group. Examples: "Food and Nutrition", "Water and Sanitation".',
    },
    {
      field: 'family_code',
      label: 'Family Code',
      type: 'text',
      required: true,
      maxLength: 6,
      uppercase: true,
      hint: 'Short code for this specific family within the group. Examples: GRAIN, DAIRY, WTRPUR, TARP.',
    },
    {
      field: 'family_label',
      label: 'Family Label',
      type: 'text',
      required: true,
      maxLength: 160,
      hint: 'Descriptive name shown in dropdowns. Examples: "Grains and Cereals", "Water Purification".',
    },
    {
      field: 'source_version',
      label: 'Source Version',
      type: 'text',
      maxLength: 80,
      hint: 'Optional. The IFRC catalog version this entry was sourced from (e.g. "IFRC-2024-v3").',
    },
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
      hint: 'Set to Inactive to hide from item classification dropdowns without deleting.',
    },
  ],
};
