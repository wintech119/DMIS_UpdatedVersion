import { MasterTableConfig } from '../master-data.models';

export const PARISH_CONFIG: MasterTableConfig = {
  tableKey: 'parishes',
  displayName: 'Parishes',
  icon: 'location_on',
  pkField: 'parish_code',
  routePath: 'parishes',
  formMode: 'dialog',
  readOnly: true,
  hasStatus: false,
  searchPlaceholder: 'Search by code or name...',
  columns: [
    { field: 'parish_code', header: 'Code', type: 'text', sortable: true },
    { field: 'parish_name', header: 'Parish Name', type: 'text', sortable: true },
  ],
  formFields: [],
};
