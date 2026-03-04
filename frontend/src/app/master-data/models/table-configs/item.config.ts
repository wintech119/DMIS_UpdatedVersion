import { MasterTableConfig } from '../master-data.models';

export const ITEM_CONFIG: MasterTableConfig = {
  tableKey: 'items',
  displayName: 'Items',
  icon: 'category',
  pkField: 'item_id',
  routePath: 'items',
  formMode: 'page',
  searchPlaceholder: 'Search by code, name, or SKU...',
  columns: [
    { field: 'item_code', header: 'Code', type: 'text', sortable: true },
    { field: 'item_name', header: 'Name', type: 'text', sortable: true },
    { field: 'sku_code', header: 'SKU', type: 'text', sortable: true, hideMobile: true },
    { field: 'category_id', header: 'Category', type: 'text', sortable: true, hideMobile: true },
    { field: 'default_uom_code', header: 'UOM', type: 'text', sortable: true, hideMobile: true },
    { field: 'issuance_order', header: 'Issuance', type: 'text', sortable: true, hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    // Basic Info
    { field: 'item_code', label: 'Item Code', type: 'text', required: true, maxLength: 16, uppercase: true,
      pattern: '^[A-Z0-9\\-_\\.]+$', patternMessage: 'Only uppercase letters, digits, hyphens, underscores, dots',
      group: 'Basic Information' },
    { field: 'item_name', label: 'Item Name', type: 'text', required: true, maxLength: 60, uppercase: true,
      group: 'Basic Information' },
    { field: 'sku_code', label: 'SKU Code', type: 'text', required: true, maxLength: 30, uppercase: true,
      group: 'Basic Information' },
    { field: 'category_id', label: 'Category', type: 'lookup', required: true, lookupTable: 'item_categories',
      group: 'Basic Information' },
    { field: 'item_desc', label: 'Description', type: 'textarea', required: true, colspan: 2,
      group: 'Basic Information' },

    // Inventory Settings
    { field: 'default_uom_code', label: 'Default UOM', type: 'lookup', required: true, lookupTable: 'uom',
      group: 'Inventory Settings' },
    { field: 'reorder_qty', label: 'Reorder Quantity', type: 'number', required: true,
      group: 'Inventory Settings' },
    { field: 'issuance_order', label: 'Issuance Order', type: 'select', required: true, defaultValue: 'FIFO',
      options: [
        { value: 'FIFO', label: 'FIFO (First In, First Out)' },
        { value: 'FEFO', label: 'FEFO (First Expired, First Out)' },
        { value: 'LIFO', label: 'LIFO (Last In, First Out)' },
      ],
      group: 'Inventory Settings' },
    { field: 'baseline_burn_rate', label: 'Baseline Burn Rate', type: 'number', defaultValue: 0,
      group: 'Inventory Settings' },
    { field: 'min_stock_threshold', label: 'Min Stock Threshold', type: 'number', defaultValue: 0,
      group: 'Inventory Settings' },
    { field: 'criticality_level', label: 'Criticality Level', type: 'select', defaultValue: 'NORMAL',
      options: [
        { value: 'NORMAL', label: 'Normal' },
        { value: 'HIGH', label: 'High' },
        { value: 'CRITICAL', label: 'Critical' },
      ],
      group: 'Inventory Settings' },

    // Tracking Flags
    { field: 'is_batched_flag', label: 'Batch Tracked', type: 'boolean', defaultValue: true,
      group: 'Tracking' },
    { field: 'can_expire_flag', label: 'Can Expire', type: 'boolean', defaultValue: false,
      group: 'Tracking' },
    { field: 'units_size_vary_flag', label: 'Units Size Vary', type: 'boolean', defaultValue: false,
      group: 'Tracking' },

    // Additional Info
    { field: 'usage_desc', label: 'Usage Description', type: 'textarea', maxLength: 300, colspan: 2,
      group: 'Additional Information' },
    { field: 'storage_desc', label: 'Storage Description', type: 'textarea', maxLength: 300, colspan: 2,
      group: 'Additional Information' },
    { field: 'comments_text', label: 'Comments', type: 'textarea', maxLength: 300, colspan: 2,
      group: 'Additional Information' },

    // Status
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Status' },
  ],
};
