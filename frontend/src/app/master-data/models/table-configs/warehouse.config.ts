import { MasterTableConfig } from '../master-data.models';

export const WAREHOUSE_CONFIG: MasterTableConfig = {
  tableKey: 'warehouses',
  displayName: 'Warehouses',
  icon: 'warehouse',
  pkField: 'warehouse_id',
  routePath: 'warehouses',
  formMode: 'page',
  formDescription:
    'Maintain warehouse and hub records used by stock visibility, needs-list routing, and controlled repackaging. ' +
    'Use the warehouse type to distinguish main hubs from downstream sub-hubs.',
  searchPlaceholder: 'Search by name or contact...',
  columns: [
    { field: 'warehouse_name', header: 'Name', type: 'text', sortable: true },
    { field: 'warehouse_type', header: 'Type', type: 'text', sortable: true },
    { field: 'parish_code', header: 'Parish', type: 'text', sortable: true, hideMobile: true },
    { field: 'contact_name', header: 'Contact', type: 'text', sortable: true, hideMobile: true },
    { field: 'phone_no', header: 'Phone', type: 'text', hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'warehouse_name', label: 'Warehouse Name', type: 'text', required: true, maxLength: 255,
      hint: 'Use the operational name that appears in stock dashboards and warehouse selection lists.',
      group: 'Basic Information' },
    { field: 'warehouse_type', label: 'Type', type: 'select', required: true,
      options: [
        { value: 'MAIN-HUB', label: 'Main Hub' },
        { value: 'SUB-HUB', label: 'Sub Hub' },
      ],
      hint: 'Main Hub is the primary warehouse. Sub Hub is a downstream logistics point that still participates in the same stock baseline.',
      tooltip: 'Sprint 07 keeps hub hierarchy within the warehouse master instead of introducing a separate hub module.',
      group: 'Basic Information' },
    { field: 'custodian_id', label: 'Custodian', type: 'lookup', required: true, lookupTable: 'custodians',
      hint: 'Assign the operational owner responsible for this warehouse or hub.',
      group: 'Basic Information' },
    { field: 'min_stock_threshold', label: 'Min Stock Threshold', type: 'number', defaultValue: 0,
      hint: 'Warehouse-level floor used by stock-health visibility when available for this site.',
      group: 'Basic Information' },

    { field: 'address1_text', label: 'Address Line 1', type: 'text', required: true, maxLength: 255,
      group: 'Address' },
    { field: 'address2_text', label: 'Address Line 2', type: 'text', maxLength: 255,
      group: 'Address' },
    { field: 'parish_code', label: 'Parish', type: 'lookup', required: true, lookupTable: 'parishes',
      hint: 'Use the physical parish for the warehouse or hub site.',
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
    { field: 'reason_desc', label: 'Reason', type: 'textarea', maxLength: 255,
      group: 'Status' },
  ],
};
