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
      hint: 'Canonical code downstream reports use after IFRC mapping.',
      placeholder: 'WAT-PUR-TAB-25',
      maxLength: 30,
      uppercase: true,
      pattern: '^[A-Z0-9\\-_\\.]+$',
      patternMessage: 'Only uppercase letters, digits, hyphens, underscores, and dots are allowed.',
      group: 'Item Identity',
      tooltip: 'Auto-generated from the selected IFRC reference. If the reference changes, the canonical item code changes with it.' },
    {
      field: 'legacy_item_code',
      label: 'Local Item Code',
      type: 'text',
      hint: 'Local draft code teams can search before an IFRC match exists.',
      placeholder: 'LOC-WASH-001',
      maxLength: 30,
      uppercase: true,
      pattern: '^[A-Z0-9\\-_\\.]+$',
      patternMessage: 'Only uppercase letters, digits, hyphens, underscores, and dots are allowed.',
      group: 'Item Identity',
      tooltip: 'For local drafts only. This does not replace the official Item Code used after IFRC mapping.'},
    {
      field: 'item_name',
      label: 'Item Name',
      type: 'text',
      hint: 'Display name shown across stock, requests, dashboards, and reports.',
      placeholder: 'CORN BEEF, CANNED',
      required: true,
      maxLength: 60,
      uppercase: true,
      group: 'Item Identity',
      tooltip: 'Enter the common name followed by key specification details separated by commas. e.g. CORN BEEF, CANNED / TARPAULIN, 10 X 12 / RICE, WHITE, 5 KG BAG' },
    {
      field: 'sku_code',
      label: 'SKU Code (Optional)',
      type: 'text',
      hint: 'Procurement or inventory system reference, if one exists.',
      placeholder: 'SKU-2401-CB12',
      maxLength: 30,
      uppercase: true,
      group: 'Item Identity',
      tooltip: 'Use the vendor or procurement SKU if available. Leave blank if no external reference exists. e.g. SKU-2401-CB12, WH-TARP-1012, INV-00345' },

    {
      field: 'category_id',
      label: 'Level 1 Category',
      type: 'lookup',
      hint: 'Level 1 category used for reporting and burn-rate fallback.',
      required: true,
      lookupTable: 'item_categories',
      displayField: 'category_desc',
      group: 'Classification',
      tooltip: 'This is a policy-aligned field, not a free choice once the IFRC Family or IFRC Item Reference is selected.' },
    {
      field: 'ifrc_family_id',
      label: 'Level 2 IFRC Family',
      type: 'lookup',
      hint: 'Level 2 IFRC family that limits valid governed item references.',
      lookupTable: 'ifrc_families',
      displayField: 'ifrc_family_label',
      group: 'Classification',
      tooltip: 'Select the family that governs this item. The family drives category alignment and the list of valid IFRC references.' },
    {
      field: 'ifrc_item_ref_id',
      label: 'Level 3 IFRC Item Reference',
      type: 'lookup',
      hint: 'Level 3 IFRC reference that assigns the canonical item code.',
      lookupTable: 'ifrc_item_references',
      displayField: 'ifrc_reference_desc',
      group: 'Classification',
      tooltip: 'Search by IFRC description or code. Choose the closest governed reference and record any local difference in Description.' },
    {
      field: 'item_desc',
      label: 'Description',
      type: 'textarea',
      hint: 'Size, packaging, and local details that distinguish this item.',
      placeholder: 'Corned beef, 340 g tin, shelf-stable',
      required: true,
      group: 'Classification',
      tooltip: 'e.g. "Corned beef in 340g tin, shelf-stable, halal certified" or "Heavy-duty tarpaulin, 10ft x 12ft, blue/white, reinforced grommets"' },

    {
      field: 'default_uom_code',
      label: 'Default UOM',
      type: 'lookup',
      hint: 'Unit teams use when counting, issuing, and reporting this item.',
      required: true,
      lookupTable: 'uom',
      displayField: 'default_uom_desc',
      group: 'UOM & Conversions',
      tooltip: 'UOM is not always the same as IFRC form. A reference may classify as BAG, BOTTLE, or TABLET while stock is counted as EA, CS, KG, or L.' },
    {
      field: 'reorder_qty',
      label: 'Reorder Quantity',
      type: 'number',
      hint: 'Quantity threshold that signals replenishment should be considered.',
      required: true,
      group: 'Inventory Rules',
      tooltip: 'e.g. 100 for corn beef tins (covers ~2 days) / 50 for tarpaulins' },
    {
      field: 'issuance_order',
      label: 'Issuance Order',
      type: 'select',
      hint: 'Stock rotation rule teams follow when issuing this item.',
      required: true,
      defaultValue: 'FIFO',
      options: [
        { value: 'FIFO', label: 'FIFO (First In, First Out)' },
        { value: 'FEFO', label: 'FEFO (First Expired, First Out)' },
        { value: 'LIFO', label: 'LIFO (Last In, First Out)' },
      ],
      group: 'Inventory Rules',
      tooltip: 'FIFO issues oldest stock first. FEFO issues earliest expiry first (required when Can Expire is enabled). LIFO issues newest first.' },
    {
      field: 'can_expire_flag',
      label: 'Can Expire',
      type: 'boolean',
      hint: 'ON tracks expiry dates and requires FEFO; OFF treats stock as non-expiring.',
      defaultValue: false,
      group: 'Inventory Rules',
      tooltip: 'ON for food, medicine, batteries, water tablets. OFF for tarpaulins, blankets, tools.' },
    {
      field: 'baseline_burn_rate',
      label: 'Baseline Burn Rate',
      type: 'number',
      hint: 'Fallback units consumed per hour for stockout estimates when history is thin.',
      defaultValue: 0,
      group: 'Inventory Rules',
      tooltip: 'Fallback for stockout predictions when no demand history exists. e.g. 5 for corn beef tins / 2 for tarpaulins' },
    {
      field: 'min_stock_threshold',
      label: 'Min Stock Threshold',
      type: 'number',
      hint: 'Floor that flags the item as critical when usable stock falls below it.',
      defaultValue: 0,
      group: 'Inventory Rules',
      tooltip: 'e.g. 50 for corn beef tins / 20 for tarpaulins / 200 for water tablets' },
    {
      field: 'criticality_level',
      label: 'Criticality Level',
      type: 'select',
      hint: 'Baseline importance used before event-phase criticality is resolved.',
      defaultValue: 'NORMAL',
      options: [
        { value: 'LOW', label: 'Low' },
        { value: 'NORMAL', label: 'Normal' },
        { value: 'HIGH', label: 'High' },
        { value: 'CRITICAL', label: 'Critical' },
      ],
      group: 'Inventory Rules',
      tooltip: 'CRITICAL: water, medicine, infant formula / HIGH: rice, tarpaulins / NORMAL: canned goods / LOW: stationery' },

    {
      field: 'is_batched_flag',
      label: 'Batch Tracked',
      type: 'boolean',
      hint: 'ON tracks lot or batch movements; OFF treats stock as interchangeable.',
      defaultValue: true,
      group: 'Tracking & Behaviour',
      tooltip: 'ON for canned food, medicine, donated goods. OFF for generic supplies like rope or nails.' },
    {
      field: 'units_size_vary_flag',
      label: 'Units Size Vary',
      type: 'boolean',
      hint: 'ON allows variable-size units; OFF expects uniform packs or units.',
      defaultValue: false,
      group: 'Tracking & Behaviour',
      tooltip: 'ON for loose produce, variable-weight bags, mixed bundles. OFF for tins, pre-packaged kits, sealed cartons.' },

    {
      field: 'usage_desc',
      label: 'Usage Description',
      type: 'textarea',
      hint: 'How and when this item is distributed or consumed during a response.',
      placeholder: 'Issued one tin per person per day at shelters',
      maxLength: 300,
      group: 'Notes & Storage',
      tooltip: 'e.g. "Distributed 1 tin per person per day at shelter feeding points" or "Issued 1 per household for roof repair"' },
    {
      field: 'storage_desc',
      label: 'Storage Description',
      type: 'textarea',
      hint: 'Handling, temperature, stacking, or storage instructions for warehouses.',
      placeholder: 'Cool, dry area below 30 C; stack max 6 high',
      maxLength: 300,
      group: 'Notes & Storage',
      tooltip: 'e.g. "Cool, dry area below 30C; stack max 6 high" or "Folded on pallets, away from sunlight"' },
    {
      field: 'comments_text',
      label: 'Comments',
      type: 'textarea',
      hint: 'Administrative notes and audit-relevant context for this item.',
      placeholder: 'Donated stock reference WFP-2024-0892',
      maxLength: 300,
      group: 'Notes & Storage',
      tooltip: 'e.g. "Donated by WFP, ref WFP-2024-0892" or "Replaces legacy TARP-OLD-001" or "Pre-positioned per ODPEM directive 2024-15"' },

    {
      field: 'status_code',
      label: 'Status',
      type: 'select',
      hint: 'Active items can be requested and stocked; inactive items remain for history.',
      required: true,
      defaultValue: 'A',
      options: [
        { value: 'A', label: 'Active' },
        { value: 'I', label: 'Inactive' },
      ],
      group: 'Status' },
  ],
};
