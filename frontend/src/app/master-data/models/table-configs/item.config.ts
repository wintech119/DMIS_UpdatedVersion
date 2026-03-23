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
  formDescription:
    'Use this page to set up an item. Keep the item name the way your team knows it. ' +
    'Pick the IFRC Family and IFRC Item Reference to set the official code when a governed match is available.',
  searchPlaceholder: 'Search by item code, legacy code, name, SKU, category, IFRC family, description, or IFRC code...',
  columns: [
    { field: 'item_code', header: 'Item Code', type: 'text', sortable: true },
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
      label: 'Item Code',
      type: 'text',
      maxLength: 30,
      uppercase: true,
      pattern: '^[A-Z0-9\\-_\\.]+$',
      patternMessage: 'Only uppercase letters, digits, hyphens, underscores, and dots are allowed.',
      group: 'Item Identity',
      hint: 'Canonical code derived from the selected Level 3 IFRC reference. This is governed and not typed manually.',
      tooltip: 'Auto-generated from the selected IFRC reference. If the reference changes, the canonical item code changes with it.',
    },
    {
      field: 'legacy_item_code',
      label: 'Local Item Code',
      type: 'text',
      maxLength: 30,
      uppercase: true,
      pattern: '^[A-Z0-9\\-_\\.]+$',
      patternMessage: 'Only uppercase letters, digits, hyphens, underscores, and dots are allowed.',
      group: 'Item Identity',
      hint: 'Use this only when saving a local draft without an IFRC match yet. This helps your team find the item later.',
      tooltip: 'For local drafts only. This does not replace the official Item Code used after IFRC mapping.',
      placeholder: 'e.g. LOC-WASH-001',
    },
    {
      field: 'item_name',
      label: 'Item Name',
      type: 'text',
      required: true,
      maxLength: 60,
      uppercase: true,
      group: 'Item Identity',
      hint: 'Display name shown across dashboards and reports. Use common name + key spec.',
      placeholder: 'e.g. CORN BEEF, CANNED',
      tooltip: 'Enter the common name followed by key specification details separated by commas. e.g. CORN BEEF, CANNED / TARPAULIN, 10 X 12 / RICE, WHITE, 5 KG BAG',
    },
    {
      field: 'sku_code',
      label: 'SKU Code (Optional)',
      type: 'text',
      maxLength: 30,
      uppercase: true,
      group: 'Item Identity',
      hint: 'Inventory or procurement system reference, if one exists.',
      placeholder: 'e.g. SKU-2401-CB12',
      tooltip: 'Use the vendor or procurement SKU if available. Leave blank if no external reference exists. e.g. SKU-2401-CB12, WH-TARP-1012, INV-00345',
    },

    {
      field: 'category_id',
      label: 'Level 1 Category',
      type: 'lookup',
      required: true,
      lookupTable: 'item_categories',
      displayField: 'category_desc',
      group: 'Classification',
      hint: 'Governed Level 1 business category used for reporting and burn-rate fallback. It must align with the selected IFRC Family.',
      tooltip: 'This is a policy-aligned field, not a free choice once the IFRC Family or IFRC Item Reference is selected.',
    },
    {
      field: 'ifrc_family_id',
      label: 'Level 2 IFRC Family',
      type: 'lookup',
      lookupTable: 'ifrc_families',
      displayField: 'ifrc_family_label',
      group: 'Classification',
      hint: 'Governed Level 2 family under the chosen Level 1 category. The family determines which references are valid.',
      tooltip: 'Select the family that governs this item. The family drives category alignment and the list of valid IFRC references.',
    },
    {
      field: 'ifrc_item_ref_id',
      label: 'Level 3 IFRC Item Reference',
      type: 'lookup',
      lookupTable: 'ifrc_item_references',
      displayField: 'ifrc_reference_desc',
      group: 'Classification',
      hint: 'Governed Level 3 reference. Selecting it assigns the canonical item code and anchors category and UOM review.',
      tooltip: 'Search by IFRC description or code. Choose the closest governed reference and record any local difference in Description.',
    },
    {
      field: 'item_desc',
      label: 'Description',
      type: 'textarea',
      required: true,
      group: 'Classification',
      hint: 'Include size, weight, packaging, and any local spec that distinguishes this item from the governed IFRC reference.',
      placeholder: 'e.g. Corned beef, 340g tin, shelf-stable',
      tooltip: 'e.g. "Corned beef in 340g tin, shelf-stable, halal certified" or "Heavy-duty tarpaulin, 10ft x 12ft, blue/white, reinforced grommets"',
    },

    {
      field: 'default_uom_code',
      label: 'Default UOM',
      type: 'lookup',
      required: true,
      lookupTable: 'uom',
      displayField: 'default_uom_desc',
      group: 'UOM & Conversions',
      hint: 'Operational issue or counting unit for this item. It should follow the approved unit for the selected IFRC reference or local policy.',
      tooltip: 'UOM is not always the same as IFRC form. A reference may classify as BAG, BOTTLE, or TABLET while stock is counted as EA, CS, KG, or L.',
    },
    {
      field: 'reorder_qty',
      label: 'Reorder Quantity',
      type: 'number',
      required: true,
      group: 'Inventory Rules',
      hint: 'Triggers replenishment when stock reaches this level. Consider lead time and demand.',
      placeholder: 'e.g. 100',
      tooltip: 'e.g. 100 for corn beef tins (covers ~2 days) / 50 for tarpaulins',
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
      hint: 'FIFO: best default for most items. FEFO: required for perishable food & medicine. LIFO: rarely used.',
      tooltip: 'FIFO issues oldest stock first. FEFO issues earliest expiry first (required when Can Expire is enabled). LIFO issues newest first.',
    },
    {
      field: 'can_expire_flag',
      label: 'Can Expire',
      type: 'boolean',
      defaultValue: false,
      group: 'Inventory Rules',
      hint: 'Tracks expiration dates. When enabled, Issuance Order must be set to FEFO.',
      tooltip: 'ON for food, medicine, batteries, water tablets. OFF for tarpaulins, blankets, tools.',
    },
    {
      field: 'baseline_burn_rate',
      label: 'Baseline Burn Rate',
      type: 'number',
      defaultValue: 0,
      group: 'Inventory Rules',
      hint: 'Units consumed per hour. Set 0 if unknown — system will auto-calculate from demand.',
      placeholder: 'e.g. 5',
      tooltip: 'Fallback for stockout predictions when no demand history exists. e.g. 5 for corn beef tins / 2 for tarpaulins',
    },
    {
      field: 'min_stock_threshold',
      label: 'Min Stock Threshold',
      type: 'number',
      defaultValue: 0,
      group: 'Inventory Rules',
      hint: 'Items below this floor are flagged CRITICAL on the dashboard. Set 0 to use burn-rate only.',
      placeholder: 'e.g. 50',
      tooltip: 'e.g. 50 for corn beef tins / 20 for tarpaulins / 200 for water tablets',
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
      hint: 'Baseline catalog criticality. Runtime decisions use resolved criticality based on event phase.',
      tooltip: 'CRITICAL: water, medicine, infant formula / HIGH: rice, tarpaulins / NORMAL: canned goods / LOW: stationery',
    },

    {
      field: 'is_batched_flag',
      label: 'Batch Tracked',
      type: 'boolean',
      defaultValue: true,
      group: 'Tracking & Behaviour',
      hint: 'Enable lot/batch tracking for stock movements.',
      tooltip: 'ON for canned food, medicine, donated goods. OFF for generic supplies like rope or nails.',
    },
    {
      field: 'units_size_vary_flag',
      label: 'Units Size Vary',
      type: 'boolean',
      defaultValue: false,
      group: 'Tracking & Behaviour',
      hint: 'Enable when individual units are not uniform in size or weight.',
      tooltip: 'ON for loose produce, variable-weight bags, mixed bundles. OFF for tins, pre-packaged kits, sealed cartons.',
    },

    {
      field: 'usage_desc',
      label: 'Usage Description',
      type: 'textarea',
      maxLength: 300,
      group: 'Notes & Storage',
      hint: 'How and when this item is distributed or consumed during a response.',
      tooltip: 'e.g. "Distributed 1 tin per person per day at shelter feeding points" or "Issued 1 per household for roof repair"',
    },
    {
      field: 'storage_desc',
      label: 'Storage Description',
      type: 'textarea',
      maxLength: 300,
      group: 'Notes & Storage',
      hint: 'Handling instructions, temperature requirements, or special storage conditions.',
      tooltip: 'e.g. "Cool, dry area below 30C; stack max 6 high" or "Folded on pallets, away from sunlight"',
    },
    {
      field: 'comments_text',
      label: 'Comments',
      type: 'textarea',
      maxLength: 300,
      group: 'Notes & Storage',
      hint: 'Administrative notes and audit-relevant context.',
      tooltip: 'e.g. "Donated by WFP, ref WFP-2024-0892" or "Replaces legacy TARP-OLD-001" or "Pre-positioned per ODPEM directive 2024-15"',
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
