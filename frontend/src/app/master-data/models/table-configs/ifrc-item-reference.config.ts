import { MasterTableConfig } from '../master-data.models';

export const IFRC_ITEM_REFERENCE_CONFIG: MasterTableConfig = {
  tableKey: 'ifrc_item_references',
  displayName: 'IFRC Item References',
  icon: 'qr_code_2',
  pkField: 'ifrc_item_ref_id',
  routePath: 'ifrc-item-references',
  formMode: 'dialog',
  searchPlaceholder: 'Search by IFRC code, description, or spec attributes...',
  columns: [
    { field: 'ifrc_item_ref_id', header: 'ID', type: 'number', sortable: true, hideMobile: true },
    { field: 'ifrc_code', header: 'IFRC Code', type: 'text', sortable: true },
    { field: 'reference_desc', header: 'Reference Description', type: 'text', sortable: true },
    { field: 'category_label', header: 'Category Label', type: 'text', sortable: true, hideMobile: true },
    { field: 'spec_segment', header: 'Spec', type: 'text', sortable: true, hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    {
      field: 'ifrc_family_id',
      label: 'IFRC Family',
      type: 'lookup',
      required: true,
      lookupTable: 'ifrc_families',
    },
    { field: 'ifrc_code', label: 'IFRC Code', type: 'text', required: true, maxLength: 30, uppercase: true },
    { field: 'reference_desc', label: 'Reference Description', type: 'text', required: true, maxLength: 255 },
    { field: 'category_code', label: 'Reference Category Code', type: 'text', required: true, maxLength: 6, uppercase: true },
    { field: 'category_label', label: 'Reference Category Label', type: 'text', required: true, maxLength: 160 },
    { field: 'spec_segment', label: 'Spec Segment', type: 'text', maxLength: 7, uppercase: true },
    { field: 'size_weight', label: 'Size or Weight', type: 'text', maxLength: 40, uppercase: true },
    { field: 'form', label: 'Form', type: 'text', maxLength: 40, uppercase: true },
    { field: 'material', label: 'Material', type: 'text', maxLength: 40, uppercase: true },
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
