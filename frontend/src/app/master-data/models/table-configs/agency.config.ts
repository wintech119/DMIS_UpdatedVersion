import { MasterTableConfig } from '../master-data.models';

export const AGENCY_CONFIG: MasterTableConfig = {
  tableKey: 'agencies',
  displayName: 'Agencies',
  icon: 'corporate_fare',
  pkField: 'agency_id',
  routePath: 'agencies',
  formMode: 'page',
  formDescription:
    'Maintain agency and downstream distribution-point records that depend on the approved warehouse baseline. ' +
    'Keep each agency tied to the operational warehouse or hub it draws from when applicable.',
  searchPlaceholder: 'Search by name or contact...',
  columns: [
    { field: 'agency_name', header: 'Name', type: 'text', sortable: true },
    { field: 'agency_type', header: 'Type', type: 'text', sortable: true },
    { field: 'parish_code', header: 'Parish', type: 'text', sortable: true, hideMobile: true },
    { field: 'contact_name', header: 'Contact', type: 'text', sortable: true, hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'agency_name', label: 'Agency Name', type: 'text', required: true, maxLength: 120, uppercase: true,
      hint: 'Use the operational name shown in logistics workflows and downstream coordination.',
      group: 'Basic Information' },
    { field: 'agency_type', label: 'Type', type: 'select', required: true,
      options: [
        { value: 'SHELTER', label: 'Shelter' },
        { value: 'DISTRIBUTOR', label: 'Distributor' },
      ],
      hint: 'Shelter is a service point. Distributor is a downstream fulfillment or issue point.',
      group: 'Basic Information' },
    { field: 'warehouse_id', label: 'Warehouse', type: 'lookup', lookupTable: 'warehouses',
      hint: 'Link the agency to the warehouse or hub that typically fulfills its stock needs.',
      group: 'Basic Information' },
    { field: 'agency_priority', label: 'Priority', type: 'number',
      hint: 'Optional operational priority used by later allocation and dispatch planning.',
      group: 'Basic Information' },
    { field: 'ineligible_event_id', label: 'Ineligible Event', type: 'lookup', lookupTable: 'events',
      group: 'Basic Information' },

    { field: 'address1_text', label: 'Address Line 1', type: 'text', required: true, maxLength: 255,
      group: 'Address' },
    { field: 'address2_text', label: 'Address Line 2', type: 'text', maxLength: 255,
      group: 'Address' },
    { field: 'parish_code', label: 'Parish', type: 'lookup', required: true, lookupTable: 'parishes',
      hint: 'Use the parish where the agency or service point operates.',
      group: 'Address' },

    { field: 'contact_name', label: 'Contact Name', type: 'text', required: true, maxLength: 50, uppercase: true,
      group: 'Contact' },
    { field: 'phone_no', label: 'Phone', type: 'phone', required: true, maxLength: 20,
      pattern: '^\\+1 \\(\\d{3}\\) \\d{3}-\\d{4}$', patternMessage: 'Format: +1 (XXX) XXX-XXXX',
      group: 'Contact' },
    { field: 'email_text', label: 'Email', type: 'email', maxLength: 100,
      group: 'Contact' },

    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Status' },
  ],
};
