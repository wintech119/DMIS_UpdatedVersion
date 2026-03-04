import { MasterTableConfig } from '../master-data.models';

export const ITEM_CATEGORY_CONFIG: MasterTableConfig = {
  tableKey: 'item_categories',
  displayName: 'Item Categories',
  icon: 'folder_open',
  pkField: 'category_id',
  routePath: 'item-categories',
  formMode: 'dialog',
  searchPlaceholder: 'Search by code or description...',
  columns: [
    { field: 'category_id', header: 'ID', type: 'number', sortable: true, hideMobile: true },
    { field: 'category_code', header: 'Code', type: 'text', sortable: true },
    { field: 'category_desc', header: 'Description', type: 'text', sortable: true },
    { field: 'category_type', header: 'Type', type: 'text', sortable: true, hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'category_code', label: 'Code', type: 'text', required: true, maxLength: 30, uppercase: true },
    { field: 'category_desc', label: 'Description', type: 'text', required: true, maxLength: 60 },
    { field: 'category_type', label: 'Type', type: 'select', required: false, defaultValue: 'GOODS',
      options: [
        { value: 'GOODS', label: 'Goods' },
        { value: 'FUNDS', label: 'Funds' },
      ] },
    { field: 'comments_text', label: 'Comments', type: 'textarea', maxLength: 300 },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ] },
  ],
};
