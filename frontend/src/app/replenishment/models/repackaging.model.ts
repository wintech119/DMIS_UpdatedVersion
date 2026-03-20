export interface RepackagingAuditRow {
  repackaging_audit_id: number;
  action_type: string;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  reason_code: string;
  note_text: string | null;
  actor_id: string;
  action_dtime: string;
}

export interface RepackagingAuditMetadata {
  created_by_id: string;
  created_at: string;
  audit_row_count?: number;
}

export interface RepackagingRecordSummary {
  repackaging_id: number;
  warehouse_id: number;
  warehouse_name: string;
  item_id: number;
  item_code: string;
  item_name: string;
  batch_id: number | null;
  batch_or_lot: string | number | null;
  expiry_date: string | null;
  source_uom_code: string;
  source_qty: number | string;
  target_uom_code: string;
  target_qty: number | string;
  equivalent_default_qty: number | string;
  reason_code: string;
  note_text: string | null;
  audit_metadata: RepackagingAuditMetadata;
}

export interface RepackagingRecord extends RepackagingRecordSummary {
  source_conversion_factor: number | string;
  target_conversion_factor: number | string;
  audit_rows: RepackagingAuditRow[];
}

export interface RepackagingListResponse {
  results: RepackagingRecordSummary[];
  count: number;
  limit: number;
  offset: number;
  warnings: string[];
}

export interface RepackagingDetailResponse {
  record: RepackagingRecord;
  warnings: string[];
}

export interface CreateRepackagingPayload {
  warehouse_id: number;
  item_id: number;
  source_uom_code: string;
  source_qty: number;
  target_uom_code: string;
  reason_code: string;
  note_text?: string;
  batch_id?: number;
  batch_or_lot?: string;
  target_qty?: number;
  equivalent_default_qty?: number;
}

export interface CreateRepackagingResponse {
  record: RepackagingRecord;
  warnings: string[];
}
