import { MasterTableConfig } from '../master-data.models';

export const LOCATION_CONFIG: MasterTableConfig = {
  tableKey: 'locations',
  displayName: 'Locations',
  icon: 'place',
  pkField: 'location_id',
  routePath: 'locations',
  formMode: 'page',
  formDescription:
    'Maintain the scoped storage locations already used by item-location assignment. Sprint 07 keeps location scope narrow and aligned to the existing warehouse storage model.',
  searchPlaceholder: 'Search by location description...',
  columns: [
    { field: 'location_id', header: 'Location ID', type: 'number', sortable: true },
    { field: 'inventory_id', header: 'Inventory ID', type: 'number', sortable: true },
    { field: 'location_desc', header: 'Description', type: 'text', sortable: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'inventory_id', label: 'Inventory', type: 'lookup', required: true, lookupTable: 'inventory',
      hint: 'Choose the inventory record whose stock can be stored at this location.',
      group: 'Basic Information' },
    { field: 'location_desc', label: 'Location Description', type: 'text', required: true, maxLength: 255,
      hint: 'Describe the scoped shelf, room, bay, or storage area used during assignment.',
      group: 'Basic Information' },
    { field: 'comments_text', label: 'Comments', type: 'textarea', maxLength: 255, colspan: 2,
      hint: 'Use comments for handling or storage context, not for broader location redesign.',
      group: 'Details' },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Status' },
  ],
};
