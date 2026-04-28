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
    { field: 'inventory_id', label: 'Inventory ID', type: 'number', hint: 'Legacy inventory identifier for the stock row being maintained.', group: 'Basic Information' },
    { field: 'item_id', label: 'Item ID', type: 'number', hint: 'Item this inventory row counts for stock monitoring and replenishment.', group: 'Basic Information' },
    { field: 'uom_code', label: 'UOM', type: 'text', hint: 'Unit of measure used to count this inventory row.', placeholder: 'CASE', group: 'Basic Information' },
    { field: 'status_code', label: 'Status', type: 'select',
      hint: 'Active inventory is counted in stock views; inactive inventory stays for history.',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Basic Information' },

    { field: 'usable_qty', label: 'Usable Quantity', type: 'number', hint: 'Quantity available for allocation and dispatch.', group: 'Quantity' },
    { field: 'reserved_qty', label: 'Reserved Quantity', type: 'number', hint: 'Quantity already held for approved or pending response work.', group: 'Quantity' },
    { field: 'defective_qty', label: 'Defective Quantity', type: 'number', hint: 'Quantity on hand but not suitable for dispatch.', group: 'Quantity' },
    { field: 'expired_qty', label: 'Expired Quantity', type: 'number', hint: 'Quantity expired and unavailable for relief distribution.', group: 'Quantity' },
    { field: 'reorder_qty', label: 'Reorder Quantity', type: 'number', hint: 'Quantity threshold that signals replenishment should be considered.', group: 'Quantity' },

    { field: 'last_verified_by', label: 'Last Verified By', type: 'text', hint: 'User or team that last confirmed this stock count.', placeholder: 'KEMAR_BROWN', group: 'Verification' },
    { field: 'last_verified_date', label: 'Last Verified Date', type: 'date', hint: 'Date this inventory count was last checked.', placeholder: '2026-07-05', group: 'Verification' },
    { field: 'comments_text', label: 'Comments', type: 'textarea', hint: 'Notes that explain stock condition, count exceptions, or audit context.', placeholder: 'Cycle count adjusted after warehouse check', colspan: 2, group: 'Verification' },
  ],
};
