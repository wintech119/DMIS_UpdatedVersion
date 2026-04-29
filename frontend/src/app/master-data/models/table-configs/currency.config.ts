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
    { field: 'currency_code', label: 'Currency Code', type: 'text', hint: 'Short currency code finance teams use on country and supplier records.', placeholder: '(set on creation; locked once saved)', required: true, maxLength: 10, uppercase: true, readonlyOnEdit: true },
    { field: 'currency_name', label: 'Currency Name', type: 'text', hint: 'Full currency name shown wherever this currency is selected.', placeholder: 'Jamaican Dollar', required: true, maxLength: 60 },
    { field: 'currency_sign', label: 'Sign', type: 'text', hint: 'Symbol printed beside amounts for this currency.', placeholder: 'J$', maxLength: 6 },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      hint: 'Active currencies appear in lookups; inactive currencies stay for existing records.',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ] },
  ],
};
