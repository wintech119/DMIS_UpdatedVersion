import { MasterTableConfig } from '../master-data.models';

export const INVENTORY_CONFIG: MasterTableConfig = {
  tableKey: 'inventory',
  displayName: 'Inventory',
  icon: 'inventory_2',
  pkField: 'inventory_id',
  routePath: 'inventory',
  formMode: 'page',
  readOnly: true,
  searchPlaceholder: 'Search by inventory ID or item ID...',
  columns: [
    { field: 'inventory_id', header: 'Inventory ID', type: 'number', sortable: true },
    { field: 'item_id', header: 'Item ID', type: 'number', sortable: true },
    { field: 'usable_qty', header: 'Usable Qty', type: 'number', sortable: true },
    { field: 'uom_code', header: 'UOM', type: 'text', sortable: true, hideMobile: true },
    { field: 'reorder_qty', header: 'Reorder Qty', type: 'number', sortable: true, hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'inventory_id', label: 'Inventory ID', type: 'number', group: 'Basic Information' },
    { field: 'item_id', label: 'Item ID', type: 'number', group: 'Basic Information' },
    { field: 'uom_code', label: 'UOM', type: 'text', group: 'Basic Information' },
    { field: 'status_code', label: 'Status', type: 'select',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Basic Information' },

    { field: 'usable_qty', label: 'Usable Quantity', type: 'number', group: 'Quantity' },
    { field: 'reserved_qty', label: 'Reserved Quantity', type: 'number', group: 'Quantity' },
    { field: 'defective_qty', label: 'Defective Quantity', type: 'number', group: 'Quantity' },
    { field: 'expired_qty', label: 'Expired Quantity', type: 'number', group: 'Quantity' },
    { field: 'reorder_qty', label: 'Reorder Quantity', type: 'number', group: 'Quantity' },

    { field: 'last_verified_by', label: 'Last Verified By', type: 'text', group: 'Verification' },
    { field: 'last_verified_date', label: 'Last Verified Date', type: 'date', group: 'Verification' },
    { field: 'comments_text', label: 'Comments', type: 'textarea', colspan: 2, group: 'Verification' },
  ],
};
