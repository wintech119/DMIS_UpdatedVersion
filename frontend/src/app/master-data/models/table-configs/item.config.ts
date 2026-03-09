import { AbstractControl, ValidationErrors } from '@angular/forms';

import { MasterTableConfig } from '../master-data.models';

/**
 * Cross-field validator for item forms:
 * FEFO and expiration tracking must stay bidirectionally aligned.
 */
export function validateFefoRequiresExpiry(control: AbstractControl): ValidationErrors | null {
  const issuanceOrder = String(control.get('issuance_order')?.value ?? '').toUpperCase();
  const canExpireFlag = control.get('can_expire_flag')?.value;
  const errors: ValidationErrors = {};

  if (issuanceOrder === 'FEFO' && canExpireFlag !== true) {
    errors['fefoRequiresExpiry'] = true;
  }

  if (canExpireFlag === true && issuanceOrder !== 'FEFO') {
    errors['expiryRequiresFefo'] = true;
  }

  return Object.keys(errors).length ? errors : null;
}

export const ITEM_CONFIG: MasterTableConfig = {
  tableKey: 'items',
  displayName: 'Items',
  icon: 'category',
  pkField: 'item_id',
  routePath: 'items',
  formMode: 'page',
  searchPlaceholder: 'Search by local code, name, SKU, category, IFRC family, description, or IFRC code...',
  columns: [
    { field: 'item_code', header: 'Local Code', type: 'text', sortable: true },
    { field: 'item_name', header: 'Item Name', type: 'text', sortable: true },
    { field: 'sku_code', header: 'SKU', type: 'text', sortable: true, hideMobile: true },
    { field: 'category_desc', header: 'Level 1 Category', type: 'text', sortable: true, hideMobile: true },
    { field: 'ifrc_family_label', header: 'Level 2 IFRC Family', type: 'text', sortable: true, hideMobile: true },
    { field: 'ifrc_reference_desc', header: 'Level 3 IFRC Reference', type: 'text', sortable: false, hideMobile: true },
    { field: 'default_uom_code', header: 'UOM', type: 'text', sortable: true, hideMobile: true },
    { field: 'criticality_level', header: 'Criticality', type: 'text', sortable: true, hideMobile: true },
    { field: 'status_code', header: 'Status', type: 'status', sortable: true },
  ],
  formFields: [
    {
      field: 'item_code',
      label: 'Local Item Code',
      type: 'text',
      required: true,
      maxLength: 30,
      uppercase: true,
      pattern: '^[A-Z0-9\\-_\\.]+$',
      patternMessage: 'Only uppercase letters, digits, hyphens, underscores, and dots are allowed.',
      group: 'Item Identity',
      hint: 'Keep the local DMIS code. IFRC suggestions do not overwrite this field.',
    },
    {
      field: 'item_name',
      label: 'Item Name',
      type: 'text',
      required: true,
      maxLength: 60,
      uppercase: true,
      group: 'Item Identity',
      hint: 'Display name shown across dashboards and reports.',
    },
    {
      field: 'sku_code',
      label: 'SKU Code (Optional)',
      type: 'text',
      maxLength: 30,
      uppercase: true,
      group: 'Item Identity',
      hint: 'Inventory or procurement system reference, if one exists.',
    },

    {
      field: 'category_id',
      label: 'Level 1 DMIS Business Category',
      type: 'lookup',
      required: true,
      lookupTable: 'item_categories',
      displayField: 'category_desc',
      group: 'Classification',
      hint: 'Required. Used for stock-health reporting and burn-rate fallbacks.',
    },
    {
      field: 'ifrc_family_id',
      label: 'Level 2 IFRC Family',
      type: 'lookup',
      lookupTable: 'ifrc_families',
      displayField: 'ifrc_family_label',
      group: 'Classification',
      hint: 'Required on create when the chosen Level 1 category has governed IFRC families.',
    },
    {
      field: 'ifrc_item_ref_id',
      label: 'Level 3 IFRC Item Reference',
      type: 'lookup',
      lookupTable: 'ifrc_references',
      displayField: 'ifrc_reference_desc',
      group: 'Classification',
      hint: 'Optional. Search by description first, then confirm the IFRC code.',
    },
    {
      field: 'item_desc',
      label: 'Description',
      type: 'textarea',
      required: true,
      group: 'Classification',
      hint: 'Purpose, packaging, or specification notes for this item.',
    },

    {
      field: 'default_uom_code',
      label: 'Default UOM',
      type: 'lookup',
      required: true,
      lookupTable: 'uom',
      group: 'Inventory Rules',
      hint: 'Base unit for stock counts, movements, and needs-list quantities.',
    },
    {
      field: 'reorder_qty',
      label: 'Reorder Quantity',
      type: 'number',
      required: true,
      group: 'Inventory Rules',
      hint: 'Triggers a replenishment request when stock reaches this level.',
    },
    {
      field: 'issuance_order',
      label: 'Issuance Order',
      type: 'select',
      required: true,
      defaultValue: 'FIFO',
      options: [
        { value: 'FIFO', label: 'FIFO (First In, First Out)' },
        { value: 'FEFO', label: 'FEFO (First Expired, First Out)' },
        { value: 'LIFO', label: 'LIFO (Last In, First Out)' },
      ],
      group: 'Inventory Rules',
      hint: 'FIFO = first received. FEFO = earliest expiry. LIFO = latest received.',
    },
    {
      field: 'baseline_burn_rate',
      label: 'Baseline Burn Rate',
      type: 'number',
      defaultValue: 0,
      group: 'Inventory Rules',
      hint: 'Fallback used for stockout predictions when no demand history exists.',
    },
    {
      field: 'min_stock_threshold',
      label: 'Min Stock Threshold',
      type: 'number',
      defaultValue: 0,
      group: 'Inventory Rules',
      hint: 'Items below this floor are flagged critical on the dashboard.',
    },
    {
      field: 'criticality_level',
      label: 'Criticality Level',
      type: 'select',
      defaultValue: 'NORMAL',
      options: [
        { value: 'LOW', label: 'Low' },
        { value: 'NORMAL', label: 'Normal' },
        { value: 'HIGH', label: 'High' },
        { value: 'CRITICAL', label: 'Critical' },
      ],
      group: 'Inventory Rules',
      hint: 'Baseline catalog criticality only. Runtime decisions use resolved criticality.',
    },

    {
      field: 'is_batched_flag',
      label: 'Batch Tracked',
      type: 'boolean',
      defaultValue: true,
      colspan: 2,
      group: 'Tracking & Behaviour',
      hint: 'Records lot or batch numbers for all stock movements.',
    },
    {
      field: 'can_expire_flag',
      label: 'Can Expire',
      type: 'boolean',
      defaultValue: false,
      colspan: 2,
      group: 'Tracking & Behaviour',
      hint: 'Tracks expiration dates. FEFO is required whenever this is enabled.',
    },
    {
      field: 'units_size_vary_flag',
      label: 'Units Size Vary',
      type: 'boolean',
      defaultValue: false,
      colspan: 2,
      group: 'Tracking & Behaviour',
      hint: 'Units may vary in size or weight, for example loose produce or bundles.',
    },

    {
      field: 'usage_desc',
      label: 'Usage Description',
      type: 'textarea',
      maxLength: 300,
      group: 'Notes & Storage',
      hint: 'How and when this item is distributed or consumed.',
    },
    {
      field: 'storage_desc',
      label: 'Storage Description',
      type: 'textarea',
      maxLength: 300,
      group: 'Notes & Storage',
      hint: 'Handling instructions, temperature, or special storage conditions.',
    },
    {
      field: 'comments_text',
      label: 'Comments',
      type: 'textarea',
      maxLength: 300,
      colspan: 2,
      group: 'Notes & Storage',
      hint: 'Administrative notes and audit-relevant context.',
    },

    {
      field: 'status_code',
      label: 'Status',
      type: 'select',
      required: true,
      defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Status',
    },
  ],
};
