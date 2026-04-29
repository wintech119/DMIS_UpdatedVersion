import { MasterTableConfig } from '../master-data.models';

export const LOCATION_CONFIG: MasterTableConfig = {
  tableKey: 'locations',
  displayName: 'Locations',
  icon: 'place',
  pkField: 'location_id',
  routePath: 'locations',
  formMode: 'page',
  searchPlaceholder: 'Search by location description...',
  columns: [
    { field: 'location_id', header: 'Location ID', type: 'number', sortable: true },
    { field: 'inventory_id', header: 'Inventory ID', type: 'number', sortable: true },
    { field: 'location_desc', header: 'Description', type: 'text', sortable: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    { field: 'inventory_id', label: 'Inventory', type: 'lookup', required: true, lookupTable: 'inventory',
      hint: 'Inventory record this physical storage location belongs to.',
      group: 'Basic Information' },
    { field: 'location_desc', label: 'Location Description', type: 'text', required: true, maxLength: 255,
      hint: 'Bin, room, or bay name warehouse teams use when picking stock.',
      placeholder: 'Aisle 3, Bay B',
      group: 'Basic Information' },
    { field: 'comments_text', label: 'Comments', type: 'textarea', maxLength: 255, colspan: 2,
      hint: 'Notes that help warehouse teams find or manage this location.',
      placeholder: 'Keep heavy items on lower shelf',
      group: 'Details' },
    { field: 'status_code', label: 'Status', type: 'select', required: true, defaultValue: 'A',
      hint: 'Active locations can hold stock; inactive locations remain for history.',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Status' },
  ],
};
