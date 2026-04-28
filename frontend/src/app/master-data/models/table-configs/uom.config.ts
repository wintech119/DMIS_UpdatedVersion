import { MasterTableConfig } from '../master-data.models';

export const UOM_CONFIG: MasterTableConfig = {
  tableKey: 'uom',
  displayName: 'Units of Measure',
  icon: 'straighten',
  pkField: 'uom_code',
  routePath: 'uom',
  formMode: 'dialog',
  governanceNoteBody: 'UOM is how stock is counted or issued in operations. It may not match the IFRC product form.',
  governanceNoteCompact: true,
  searchPlaceholder: 'Search by code or description...',
  columns: [
    { field: 'uom_code', header: 'Code', type: 'text', sortable: true },
    { field: 'uom_desc', header: 'Description', type: 'text', sortable: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'uom_code', label: 'UOM Code', type: 'text', hint: 'Unit code used on inventory, item, and procurement records.', placeholder: '(set on creation; locked once saved)', required: true, maxLength: 25, uppercase: true, readonlyOnEdit: true },
    { field: 'uom_desc', label: 'Description', type: 'text', hint: 'Readable unit name shown in item and stock forms.', placeholder: 'Carton', required: true, maxLength: 60 },
    { field: 'comments_text', label: 'Comments', type: 'textarea', hint: 'Notes explaining when operators should use this unit.', placeholder: 'Use for sealed cartons of 24 tins', maxLength: 300 },
    {
      field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      hint: 'Active units appear in item lookups; inactive units stay for existing records.',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ] },
  ],
};
