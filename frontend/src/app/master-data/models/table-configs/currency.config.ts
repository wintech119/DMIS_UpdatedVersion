import { MasterTableConfig } from '../master-data.models';

export const CURRENCY_CONFIG: MasterTableConfig = {
  tableKey: 'currencies',
  displayName: 'Currencies',
  icon: 'payments',
  pkField: 'currency_code',
  routePath: 'currencies',
  formMode: 'dialog',
  searchPlaceholder: 'Search by code or name...',
  columns: [
    { field: 'currency_code', header: 'Code', type: 'text', sortable: true },
    { field: 'currency_name', header: 'Currency Name', type: 'text', sortable: true },
    { field: 'currency_sign', header: 'Sign', type: 'text' },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'currency_code', label: 'Currency Code', type: 'text', required: true, maxLength: 10, uppercase: true, readonlyOnEdit: true },
    { field: 'currency_name', label: 'Currency Name', type: 'text', required: true, maxLength: 60 },
    { field: 'currency_sign', label: 'Sign', type: 'text', maxLength: 6 },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ] },
  ],
};
