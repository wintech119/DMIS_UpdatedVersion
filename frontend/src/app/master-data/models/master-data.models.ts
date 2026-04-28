// ---------------------------------------------------------------------------
// Master Data config-driven interfaces
// ---------------------------------------------------------------------------

export type FormMode = 'dialog' | 'page';
export type FieldType = 'text' | 'number' | 'select' | 'lookup' | 'boolean' | 'date' | 'textarea' | 'email' | 'phone';
export type ColumnType = 'text' | 'number' | 'date' | 'boolean' | 'status' | 'pill';
export type MasterDomainKey = 'catalogs' | 'operational' | 'policies' | 'tenant-access' | 'advanced';
export type MasterTone = 'critical' | 'warning' | 'success' | 'info' | 'neutral';
export type MasterRecord = Record<string, unknown>;

export interface MasterToneRule {
  value?: string;
  values?: readonly string[];
  startsWith?: string;
  label?: string;
  tone: MasterTone;
  icon?: string;
}

export interface MasterColumnConfig {
  field: string;
  header: string;
  type: ColumnType;
  sortable?: boolean;
  /** Hide on mobile screens */
  hideMobile?: boolean;
  /** Render with code-like typography */
  monospace?: boolean;
  /** Render as semibold when the value carries identity weight */
  semibold?: boolean;
  /** Trim long text for dense list columns */
  truncate?: number;
  /** Optional tone/icon mapping for status and semantic pill columns */
  toneMap?: readonly MasterToneRule[];
  /** Optional leading icon when a non-empty value needs context */
  prefixIcon?: string;
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
  /** Optional read/display field for detail pages */
  displayField?: string;
  /** For 'boolean' type: default value */
  defaultValue?: unknown;
  /** Readonly on edit (e.g. donor_code) */
  readonlyOnEdit?: boolean;
  /** Uppercase on input */
  uppercase?: boolean;
  /** Group label for form section grouping */
  group?: string;
  /** Grid span (1 or 2 columns) */
  colspan?: 1 | 2 | 4;
  /** Hide from create forms while keeping the control available for edit payloads */
  editOnly?: boolean;
  /** Optional help text rendered below the field */
  hint?: string;
  /** Value-specific help text, used when a select value needs operational context */
  valueHints?: { value: string; hint: string }[];
  /** Optional tooltip text rendered from an inline help affordance */
  tooltip?: string;
  /** Optional placeholder text shown inside the input when empty */
  placeholder?: string;
}

export interface MasterEmptyStateConfig {
  icon: string;
  title: string;
  message: string;
  actionLabel?: string;
  actionIcon?: string;
}

export interface MasterTableConfig {
  tableKey: string;
  displayName: string;
  icon: string;
  pkField: string;
  routePath: string;
  domain?: MasterDomainKey;
  formMode: FormMode;
  /** Read-only table (e.g. parishes) */
  readOnly?: boolean;
  /** Table has no status_code column (e.g. donor, custodian, parish) */
  hasStatus?: boolean;
  /** Instructional text shown at the top of the create/edit form */
  formDescription?: string;
  /** Optional always-visible governance guidance shown above the form */
  governanceNoteTitle?: string;
  /** Optional always-visible governance guidance copy shown above the form */
  governanceNoteBody?: string;
  /** Render governance guidance in a more compact layout when space is limited */
  governanceNoteCompact?: boolean;
  /** Columns shown in the list view */
  columns: MasterColumnConfig[];
  /** Fields shown in the create/edit form */
  formFields: MasterFieldConfig[];
  /** Config-specific empty state copy */
  emptyState?: MasterEmptyStateConfig;
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
  edit_guidance?: CatalogEditGuidance;
}

export interface MasterSummaryResponse {
  counts: {
    total: number;
    active: number;
    inactive: number;
  };
  warnings: string[];
}

export interface MasterLookupResponse<T = LookupItem> {
  items: T[];
  warnings: string[];
}

export interface CatalogEditGuidance {
  warning_required: boolean;
  warning_text: string;
  locked_fields: string[];
  replacement_supported: boolean;
}

export interface CatalogAuthoringSuggestionResponse {
  source: string;
  normalized: MasterRecord;
  conflicts?: Record<string, unknown>;
  warnings: string[];
  edit_guidance?: CatalogEditGuidance;
}

export interface CatalogReplacementResponse<T = MasterRecord> extends MasterDetailResponse<T> {
  replacement_for_pk: string | number;
  retire_original_requested?: boolean;
  retired_original?: boolean;
}

export interface LookupItem {
  value: string | number;
  label: string;
  [key: string]: unknown;
}

export interface MasterValidationErrors {
  errors: Record<string, string>;
}
export interface MasterSaveFailureResponse {
  detail?: string;
  diagnostic?: string;
  warnings?: string[];
  errors?: Record<string, unknown>;
}


export interface MasterInactivateBlockedResponse {
  detail: string;
  blocking: string[];
  warnings: string[];
}

