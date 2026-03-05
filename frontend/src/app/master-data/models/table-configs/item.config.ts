import { MasterTableConfig } from '../master-data.models';
import { AbstractControl, ValidationErrors } from '@angular/forms';

/**
 * Cross-field validator for item forms:
 * FEFO issuance requires expiration tracking to be enabled.
 */
export function validateFefoRequiresExpiry(control: AbstractControl): ValidationErrors | null {
  const issuanceOrder = control.get('issuance_order')?.value;
  const canExpireFlag = control.get('can_expire_flag')?.value;

  if (issuanceOrder === 'FEFO' && canExpireFlag !== true) {
    return { fefoRequiresExpiry: true };
  }

  return null;
}

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
    // ── Item Identity ────────────────────────────────────────────────────────
    {
      field: 'item_code', label: 'Item Code', type: 'text', required: true,
      maxLength: 30, uppercase: true,
      pattern: '^[A-Z0-9\\-_\\.]+$', patternMessage: 'Only uppercase letters, digits, hyphens, underscores, dots',
      group: 'Item Identity',
      hint: 'Uppercase letters, digits, hyphens, underscores, and dots only',
    },
    {
      field: 'item_name', label: 'Item Name', type: 'text', required: true,
      maxLength: 60, uppercase: true,
      group: 'Item Identity',
      hint: 'Display name shown across dashboards and reports',
    },
    {
      field: 'sku_code', label: 'SKU Code (Optional)', type: 'text', required: false,
      maxLength: 30, uppercase: true,
      group: 'Item Identity',
      hint: 'Inventory or procurement system reference — leave blank if not applicable',
    },

    // ── Classification ───────────────────────────────────────────────────────
    {
      field: 'category_id', label: 'Category', type: 'lookup', required: true,
      lookupTable: 'item_categories',
      group: 'Classification',
      hint: 'Groups items for reporting and burn rate fallbacks',
    },
    {
      field: 'item_desc', label: 'Description', type: 'textarea', required: true,
      group: 'Classification',
      hint: 'Purpose and specifications of this item',
    },

    // ── Inventory Rules ──────────────────────────────────────────────────────
    {
      field: 'default_uom_code', label: 'Default UOM', type: 'lookup', required: true,
      lookupTable: 'uom',
      group: 'Inventory Rules',
      hint: 'Base unit for stock counts, movements, and needs-list quantities',
    },
    {
      field: 'reorder_qty', label: 'Reorder Quantity', type: 'number', required: true,
      group: 'Inventory Rules',
      hint: 'Triggers a replenishment request when stock reaches this level',
    },
    {
      field: 'issuance_order', label: 'Issuance Order', type: 'select', required: true,
      defaultValue: 'FIFO',
      options: [
        { value: 'FIFO', label: 'FIFO (First In, First Out)' },
        { value: 'FEFO', label: 'FEFO (First Expired, First Out)' },
        { value: 'LIFO', label: 'LIFO (Last In, First Out)' },
      ],
      group: 'Inventory Rules',
      hint: 'FIFO = first received · FEFO = soonest expiry · LIFO = latest received',
    },
    {
      field: 'baseline_burn_rate', label: 'Baseline Burn Rate', type: 'number',
      defaultValue: 0,
      group: 'Inventory Rules',
      hint: 'Fallback used for stockout predictions when no demand history exists',
    },
    {
      field: 'min_stock_threshold', label: 'Min Stock Threshold', type: 'number',
      defaultValue: 0,
      group: 'Inventory Rules',
      hint: 'Items below this floor are flagged Critical on the dashboard',
    },
    {
      field: 'criticality_level', label: 'Criticality Level', type: 'select',
      defaultValue: 'NORMAL',
      options: [
        { value: 'NORMAL', label: 'Normal' },
        { value: 'HIGH', label: 'High' },
        { value: 'CRITICAL', label: 'Critical' },
      ],
      group: 'Inventory Rules',
      hint: 'Affects replenishment priority and approval routing',
    },

    // ── Tracking & Behaviour ─────────────────────────────────────────────────
    {
      field: 'is_batched_flag', label: 'Batch Tracked', type: 'boolean',
      defaultValue: true, colspan: 2,
      group: 'Tracking & Behaviour',
      hint: 'Records lot/batch numbers for all stock movements',
    },
    {
      field: 'can_expire_flag', label: 'Can Expire', type: 'boolean',
      defaultValue: false, colspan: 2,
      group: 'Tracking & Behaviour',
      hint: 'Tracks expiration dates. Required when Issuance Order is FEFO',
    },
    {
      field: 'units_size_vary_flag', label: 'Units Size Vary', type: 'boolean',
      defaultValue: false, colspan: 2,
      group: 'Tracking & Behaviour',
      hint: 'Units may vary in size or weight (e.g. loose produce, bundles)',
    },

    // ── Notes & Storage ──────────────────────────────────────────────────────
    {
      field: 'usage_desc', label: 'Usage Description', type: 'textarea',
      maxLength: 300,
      group: 'Notes & Storage',
      hint: 'How and when this item is distributed or consumed',
    },
    {
      field: 'storage_desc', label: 'Storage Description', type: 'textarea',
      maxLength: 300,
      group: 'Notes & Storage',
      hint: 'Handling instructions, temperature, or special storage conditions',
    },
    {
      field: 'comments_text', label: 'Comments', type: 'textarea',
      maxLength: 300, colspan: 2,
      group: 'Notes & Storage',
      hint: 'Any additional notes or administrative remarks',
    },

    // ── Status ───────────────────────────────────────────────────────────────
    {
      field: 'status_code', label: 'Status', type: 'select', required: true,
      defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Status',
    },
  ],
};
