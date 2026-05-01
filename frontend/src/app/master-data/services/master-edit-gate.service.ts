import { Injectable, signal } from '@angular/core';

import {
  CatalogEditGuidance,
  MasterFieldConfig,
  MasterRecord,
  MasterTableConfig,
} from '../models/master-data.models';
import { EditGateDialogData } from '../components/master-edit-gate-dialog/master-edit-gate-dialog.component';

const TABLE_IMPACT_MAP: Record<string, { modules: string[]; description: string }> = {
  items: {
    modules: ['Replenishment', 'Needs Lists', 'Transfers', 'Procurement', 'Donations', 'Stock Monitoring'],
    description: 'Changes to this item will propagate to all supply chain modules and active workflows.',
  },
  warehouses: {
    modules: ['Inventory', 'Replenishment', 'Transfers', 'Stock Monitoring'],
    description: 'Warehouse changes affect inventory tracking and active transfer operations.',
  },
  item_categories: {
    modules: ['Items', 'Classification', 'Replenishment'],
    description: 'Category changes cascade to all items in this classification group.',
  },
  uom: {
    modules: ['Items', 'Replenishment', 'Procurement'],
    description: 'Unit of measure changes affect quantity calculations across the system.',
  },
  agencies: {
    modules: ['Warehouses', 'Transfers', 'Events'],
    description: 'Agency changes affect associated warehouses and coordination assignments.',
  },
  events: {
    modules: ['Replenishment', 'Needs Lists', 'Stock Monitoring'],
    description: 'Event changes affect active response operations and planning windows.',
  },
  donors: {
    modules: ['Donations', 'Procurement'],
    description: 'Donor changes affect active and historical donation records.',
  },
  suppliers: {
    modules: ['Procurement'],
    description: 'Supplier changes affect active and pending procurement orders.',
  },
  ifrc_families: {
    modules: ['Items', 'Classification'],
    description: 'Changes to governed IFRC families cascade to item references and mapped items.',
  },
  ifrc_item_references: {
    modules: ['Items', 'Classification'],
    description: 'Changes to governed IFRC references affect all items mapped to this reference.',
  },
};

interface DisabledFieldOptions {
  config: MasterTableConfig | null;
  editGuidance?: CatalogEditGuidance | null;
  isEdit: boolean;
  replacementMode?: boolean;
  alwaysEnabledFieldNames?: readonly string[];
}

@Injectable({ providedIn: 'root' })
export class MasterEditGateService {
  private readonly skipGovernedEditWarning = signal(false);

  isGovernedCatalogTable(tableKey: string | null | undefined): tableKey is 'ifrc_families' | 'ifrc_item_references' {
    return tableKey === 'ifrc_families' || tableKey === 'ifrc_item_references';
  }

  getDefaultCatalogEditGuidance(tableKey: string | null | undefined): CatalogEditGuidance | null {
    if (tableKey === 'ifrc_families') {
      return {
        warning_required: true,
        warning_text: 'You are modifying governed IFRC Family data. Changes may affect classification, search, and future item selection. Canonical code-bearing fields stay locked, and code corrections must use replacement instead of overwrite.',
        locked_fields: ['group_code', 'family_code'],
        replacement_supported: true,
      };
    }

    if (tableKey === 'ifrc_item_references') {
      return {
        warning_required: true,
        warning_text: 'You are modifying governed IFRC Item Reference data. Changes may affect classification, search, and future item selection. Canonical code-bearing fields stay locked, and code corrections must use replacement instead of overwrite.',
        locked_fields: ['ifrc_family_id', 'ifrc_code', 'category_code', 'spec_segment'],
        replacement_supported: true,
      };
    }

    return null;
  }

  getEffectiveCatalogEditGuidance(
    config: MasterTableConfig | null,
    editGuidance?: CatalogEditGuidance | null,
  ): CatalogEditGuidance | null {
    if (!config) {
      return null;
    }
    return editGuidance ?? this.getDefaultCatalogEditGuidance(config.tableKey);
  }

  getLockedCatalogFieldNames(
    config: MasterTableConfig | null,
    editGuidance?: CatalogEditGuidance | null,
  ): Set<string> {
    const guidanceFields = this.getEffectiveCatalogEditGuidance(config, editGuidance)?.locked_fields ?? [];
    if (guidanceFields.length > 0) {
      return new Set(guidanceFields);
    }

    return new Set((config?.formFields ?? [])
      .filter((field) => field.readonlyOnEdit)
      .map((field) => field.field));
  }

  shouldDisableField(field: MasterFieldConfig, options: DisabledFieldOptions): boolean {
    const {
      config,
      editGuidance,
      isEdit,
      replacementMode = false,
      alwaysEnabledFieldNames = [],
    } = options;

    if (alwaysEnabledFieldNames.includes(field.field)) {
      return false;
    }

    if (!isEdit) {
      return false;
    }

    if (
      this.isGovernedCatalogTable(config?.tableKey)
      && !replacementMode
      && this.getLockedCatalogFieldNames(config, editGuidance).has(field.field)
    ) {
      return true;
    }

    return field.readonlyOnEdit === true;
  }

  getDisabledFieldLabels(options: DisabledFieldOptions): string[] {
    const { config } = options;
    if (!config) {
      return [];
    }

    return config.formFields
      .filter((field) => this.shouldDisableField(field, options))
      .map((field) => field.label);
  }

  getRecordTitle(
    record: MasterRecord | null | undefined,
    config: MasterTableConfig | null,
    pk: string | number | null,
  ): string {
    if (!record || !config) {
      return '';
    }

    if (config.tableKey === 'user') {
      const firstName = this.trimRecordValue(record['first_name']);
      const lastName = this.trimRecordValue(record['last_name']);
      const fullName = this.trimRecordValue(record['full_name']) || [firstName, lastName].filter(Boolean).join(' ');
      const userTitle = fullName
        || this.trimRecordValue(record['user_name'])
        || this.trimRecordValue(record['username'])
        || this.trimRecordValue(record['email']);
      if (userTitle) {
        return userTitle;
      }
    }

    const nameFields = [
      'item_name', 'warehouse_name', 'agency_name', 'event_name',
      'donor_name', 'supplier_name', 'custodian_name', 'country_name',
      'currency_name', 'parish_name', 'family_label', 'reference_desc',
      'category_desc', 'uom_desc', 'full_name', 'description', 'name',
      'item_code', 'category_code', 'uom_code', 'warehouse_code',
    ];

    for (const field of nameFields) {
      const value = this.trimRecordValue(record[field]);
      if (value) {
        return value;
      }
    }

    return `${config.displayName} ${pk}`;
  }

  private trimRecordValue(value: unknown): string {
    return value == null ? '' : String(value).trim();
  }

  buildDialogData(options: {
    config: MasterTableConfig;
    recordName: string;
    editGuidance?: CatalogEditGuidance | null;
    isEdit?: boolean;
    replacementMode?: boolean;
    alwaysEnabledFieldNames?: readonly string[];
  }): EditGateDialogData {
    const {
      config,
      recordName,
      editGuidance,
      isEdit = true,
      replacementMode = false,
      alwaysEnabledFieldNames = [],
    } = options;
    const guidance = this.getEffectiveCatalogEditGuidance(config, editGuidance);
    const impact = TABLE_IMPACT_MAP[config.tableKey];
    const isGoverned = this.isGovernedCatalogTable(config.tableKey);

    return {
      recordName: recordName || `${config.displayName} Record`,
      tableName: config.displayName,
      tableIcon: config.icon,
      warningText: guidance?.warning_text
        ?? `You are about to edit ${config.displayName.toLowerCase()} master data. Changes will be audited and may affect dependent modules.`,
      isGoverned,
      lockedFields: this.getDisabledFieldLabels({
        config,
        editGuidance: guidance,
        isEdit,
        replacementMode,
        alwaysEnabledFieldNames,
      }),
      impactModules: impact?.modules ?? [],
      impactDescription: impact?.description
        ?? `Changes to this ${config.displayName.toLowerCase()} record will be tracked in the audit log.`,
    };
  }

  markDetailEditGatePassed(): void {
    this.skipGovernedEditWarning.set(true);
  }

  consumeGovernedEditWarningSkip(): boolean {
    const shouldSkip = this.skipGovernedEditWarning();
    this.skipGovernedEditWarning.set(false);
    return shouldSkip;
  }
}
