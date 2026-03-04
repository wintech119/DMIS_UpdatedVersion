import { MasterTableConfig } from '../master-data.models';

export const UOM_CONFIG: MasterTableConfig = {
  tableKey: 'uom',
  displayName: 'Units of Measure',
  icon: 'straighten',
  pkField: 'uom_code',
  routePath: 'uom',
  formMode: 'dialog',
  searchPlaceholder: 'Search by code or description...',
  columns: [
    { field: 'uom_code', header: 'Code', type: 'text', sortable: true },
    { field: 'uom_desc', header: 'Description', type: 'text', sortable: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'uom_code', label: 'UOM Code', type: 'text', required: true, maxLength: 25, uppercase: true, readonlyOnEdit: true },
    { field: 'uom_desc', label: 'Description', type: 'text', required: true, maxLength: 60 },
    { field: 'comments_text', label: 'Comments', type: 'textarea', maxLength: 300 },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ] },
  ],
};
