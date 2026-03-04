// ---------------------------------------------------------------------------
// Master Data config-driven interfaces
// ---------------------------------------------------------------------------

export type FormMode = 'dialog' | 'page';
export type FieldType = 'text' | 'number' | 'select' | 'lookup' | 'boolean' | 'date' | 'textarea' | 'email' | 'phone';
export type ColumnType = 'text' | 'number' | 'date' | 'boolean' | 'status';
export type MasterRecord = Record<string, unknown>;

export interface MasterColumnConfig {
  field: string;
  header: string;
  type: ColumnType;
  sortable?: boolean;
  /** Hide on mobile screens */
  hideMobile?: boolean;
}

export interface MasterFieldConfig {
  field: string;
  label: string;
  type: FieldType;
  required?: boolean;
  maxLength?: number;
  pattern?: string;
  patternMessage?: string;
  /** For 'select' type: static options */
  options?: { value: string; label: string }[];
  /** For 'lookup' type: which table_key to fetch dropdown data from */
  lookupTable?: string;
  /** For 'boolean' type: default value */
  defaultValue?: unknown;
  /** Readonly on edit (e.g. donor_code) */
  readonlyOnEdit?: boolean;
  /** Uppercase on input */
  uppercase?: boolean;
  /** Group label for form section grouping */
  group?: string;
  /** Grid span (1 or 2 columns) */
  colspan?: 1 | 2;
}

export interface MasterTableConfig {
  tableKey: string;
  displayName: string;
  icon: string;
  pkField: string;
  routePath: string;
  formMode: FormMode;
  /** Read-only table (e.g. parishes) */
  readOnly?: boolean;
  /** Table has no status_code column (e.g. donor, custodian, parish) */
  hasStatus?: boolean;
  /** Columns shown in the list view */
  columns: MasterColumnConfig[];
  /** Fields shown in the create/edit form */
  formFields: MasterFieldConfig[];
  searchPlaceholder?: string;
  /** Custom status field name (default 'status_code') */
  statusField?: string;
  /** Custom active/inactive labels */
  activeLabel?: string;
  inactiveLabel?: string;
}

// ---------------------------------------------------------------------------
// API response interfaces
// ---------------------------------------------------------------------------

export interface MasterListResponse<T = MasterRecord> {
  results: T[];
  count: number;
  limit: number;
  offset: number;
  warnings: string[];
}

export interface MasterDetailResponse<T = MasterRecord> {
  record: T;
  warnings: string[];
}

export interface MasterSummaryResponse {
  counts: {
    total: number;
    active: number;
    inactive: number;
  };
  warnings: string[];
}

export interface MasterLookupResponse {
  items: LookupItem[];
  warnings: string[];
}

export interface LookupItem {
  value: string | number;
  label: string;
}

export interface MasterValidationErrors {
  errors: Record<string, string>;
}

export interface MasterInactivateBlockedResponse {
  detail: string;
  blocking: string[];
  warnings: string[];
}
