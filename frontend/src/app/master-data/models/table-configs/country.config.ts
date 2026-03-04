import { MasterTableConfig } from '../master-data.models';

export const COUNTRY_CONFIG: MasterTableConfig = {
  tableKey: 'countries',
  displayName: 'Countries',
  icon: 'public',
  pkField: 'country_id',
  routePath: 'countries',
  formMode: 'dialog',
  searchPlaceholder: 'Search by name...',
  columns: [
    { field: 'country_id', header: 'ID', type: 'number', sortable: true, hideMobile: true },
    { field: 'country_name', header: 'Country Name', type: 'text', sortable: true },
    { field: 'currency_code', header: 'Currency', type: 'text', sortable: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'country_name', label: 'Country Name', type: 'text', required: true, maxLength: 80 },
    { field: 'currency_code', label: 'Currency', type: 'lookup', lookupTable: 'currencies' },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ] },
  ],
};
