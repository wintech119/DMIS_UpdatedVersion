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
    { field: 'country_name', label: 'Country Name', type: 'text', hint: 'Country name used for donor, supplier, and procurement records.', placeholder: 'Jamaica', required: true, maxLength: 80 },
    { field: 'currency_code', label: 'Currency', type: 'lookup', hint: 'Default currency teams expect when this country is selected.', lookupTable: 'currencies' },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      hint: 'Active countries appear in lookups; inactive countries stay for existing records.',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ] },
  ],
};
