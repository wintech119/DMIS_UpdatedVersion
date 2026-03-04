import { MasterTableConfig } from '../master-data.models';

export const CUSTODIAN_CONFIG: MasterTableConfig = {
  tableKey: 'custodians',
  displayName: 'Custodians',
  icon: 'badge',
  pkField: 'custodian_id',
  routePath: 'custodians',
  formMode: 'page',
  hasStatus: false,
  searchPlaceholder: 'Search by name or contact...',
  columns: [
    { field: 'custodian_name', header: 'Name', type: 'text', sortable: true },
    { field: 'parish_code', header: 'Parish', type: 'text', sortable: true, hideMobile: true },
    { field: 'contact_name', header: 'Contact', type: 'text', sortable: true, hideMobile: true },
    { field: 'phone_no', header: 'Phone', type: 'text', hideMobile: true },
  ],
  formFields: [
    { field: 'custodian_name', label: 'Custodian Name', type: 'text', required: true, maxLength: 120, uppercase: true,
      group: 'Basic Information' },

    { field: 'address1_text', label: 'Address Line 1', type: 'text', required: true, maxLength: 255,
      group: 'Address' },
    { field: 'address2_text', label: 'Address Line 2', type: 'text', maxLength: 255,
      group: 'Address' },
    { field: 'parish_code', label: 'Parish', type: 'lookup', required: true, lookupTable: 'parishes',
      group: 'Address' },

    { field: 'contact_name', label: 'Contact Name', type: 'text', required: true, maxLength: 50, uppercase: true,
      group: 'Contact' },
    { field: 'phone_no', label: 'Phone', type: 'phone', required: true, maxLength: 20,
      pattern: '^\\+1 \\(\\d{3}\\) \\d{3}-\\d{4}$', patternMessage: 'Format: +1 (XXX) XXX-XXXX',
      group: 'Contact' },
    { field: 'email_text', label: 'Email', type: 'email', maxLength: 100,
      group: 'Contact' },
  ],
};
