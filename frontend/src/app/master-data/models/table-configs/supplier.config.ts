import { MasterTableConfig } from '../master-data.models';

export const SUPPLIER_CONFIG: MasterTableConfig = {
  tableKey: 'suppliers',
  displayName: 'Suppliers',
  icon: 'local_shipping',
  pkField: 'supplier_id',
  routePath: 'suppliers',
  formMode: 'page',
  searchPlaceholder: 'Search by code, name, or contact...',
  columns: [
    { field: 'supplier_code', header: 'Code', type: 'text', sortable: true },
    { field: 'supplier_name', header: 'Name', type: 'text', sortable: true },
    { field: 'contact_name', header: 'Contact', type: 'text', sortable: true, hideMobile: true },
    { field: 'default_lead_time_days', header: 'Lead Time', type: 'number', sortable: true, hideMobile: true },
    { field: 'is_framework_supplier', header: 'Framework', type: 'boolean', hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'supplier_code', label: 'Supplier Code', type: 'text', required: true, maxLength: 20, uppercase: true,
      group: 'Basic Information' },
    { field: 'supplier_name', label: 'Supplier Name', type: 'text', required: true, maxLength: 120,
      group: 'Basic Information' },
    { field: 'trn_no', label: 'TRN', type: 'text', maxLength: 30,
      group: 'Basic Information' },
    { field: 'tcc_no', label: 'TCC', type: 'text', maxLength: 30,
      group: 'Basic Information' },

    { field: 'contact_name', label: 'Contact Name', type: 'text', maxLength: 80,
      group: 'Contact' },
    { field: 'phone_no', label: 'Phone', type: 'phone', maxLength: 20,
      group: 'Contact' },
    { field: 'email_text', label: 'Email', type: 'email', maxLength: 100,
      group: 'Contact' },

    { field: 'address_text', label: 'Address', type: 'textarea', maxLength: 255,
      group: 'Address' },
    { field: 'parish_code', label: 'Parish', type: 'lookup', lookupTable: 'parishes',
      group: 'Address' },
    { field: 'country_id', label: 'Country', type: 'lookup', lookupTable: 'countries',
      group: 'Address' },

    { field: 'default_lead_time_days', label: 'Default Lead Time (days)', type: 'number', defaultValue: 14,
      group: 'Procurement' },
    { field: 'is_framework_supplier', label: 'Framework Supplier', type: 'boolean', defaultValue: false,
      group: 'Procurement' },
    { field: 'framework_contract_no', label: 'Framework Contract No.', type: 'text', maxLength: 50,
      group: 'Procurement' },
    { field: 'framework_expiry_date', label: 'Framework Expiry Date', type: 'date',
      group: 'Procurement' },

    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Status' },
  ],
};
