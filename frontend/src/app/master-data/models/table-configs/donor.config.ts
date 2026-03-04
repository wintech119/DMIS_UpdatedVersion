import { MasterTableConfig } from '../master-data.models';

export const DONOR_CONFIG: MasterTableConfig = {
  tableKey: 'donors',
  displayName: 'Donors',
  icon: 'handshake',
  pkField: 'donor_id',
  routePath: 'donors',
  formMode: 'page',
  hasStatus: false,
  searchPlaceholder: 'Search by code or name...',
  columns: [
    { field: 'donor_code', header: 'Code', type: 'text', sortable: true },
    { field: 'donor_name', header: 'Name', type: 'text', sortable: true },
    { field: 'org_type_desc', header: 'Org Type', type: 'text', sortable: true, hideMobile: true },
    { field: 'phone_no', header: 'Phone', type: 'text', hideMobile: true },
  ],
  formFields: [
    { field: 'donor_code', label: 'Donor Code', type: 'text', required: true, maxLength: 16, uppercase: true,
      readonlyOnEdit: true, group: 'Basic Information' },
    { field: 'donor_name', label: 'Donor Name', type: 'text', required: true, maxLength: 255, uppercase: true,
      group: 'Basic Information' },
    { field: 'org_type_desc', label: 'Organization Type', type: 'text', maxLength: 30,
      group: 'Basic Information' },

    { field: 'address1_text', label: 'Address Line 1', type: 'text', required: true, maxLength: 255,
      group: 'Address' },
    { field: 'address2_text', label: 'Address Line 2', type: 'text', maxLength: 255,
      group: 'Address' },
    { field: 'country_id', label: 'Country', type: 'lookup', required: true, lookupTable: 'countries', defaultValue: 388,
      group: 'Address' },

    { field: 'phone_no', label: 'Phone', type: 'phone', required: true, maxLength: 20,
      pattern: '^\\+1 \\(\\d{3}\\) \\d{3}-\\d{4}$', patternMessage: 'Format: +1 (XXX) XXX-XXXX',
      group: 'Contact' },
    { field: 'email_text', label: 'Email', type: 'email', maxLength: 100,
      group: 'Contact' },
  ],
};
