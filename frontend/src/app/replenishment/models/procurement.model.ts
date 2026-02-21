export type ProcurementStatus =
  | 'DRAFT'
  | 'PENDING_APPROVAL'
  | 'APPROVED'
  | 'REJECTED'
  | 'ORDERED'
  | 'SHIPPED'
  | 'PARTIAL_RECEIVED'
  | 'RECEIVED'
  | 'CANCELLED';

export type ProcurementItemStatus = 'PENDING' | 'PARTIAL' | 'RECEIVED' | 'CANCELLED';

export type ProcurementMethod =
  | 'EMERGENCY_DIRECT'
  | 'SINGLE_SOURCE'
  | 'RFQ'
  | 'RESTRICTED_BIDDING'
  | 'OPEN_TENDER'
  | 'FRAMEWORK';

export interface Supplier {
  supplier_id: number;
  supplier_code: string;
  supplier_name: string;
  contact_name?: string;
  phone_no?: string;
  email_text?: string;
  address_text?: string;
  parish_code?: string;
  default_lead_time_days: number;
  is_framework_supplier: boolean;
  framework_contract_no?: string;
  framework_expiry_date?: string;
  status_code: 'A' | 'I';
}

export interface ProcurementApproval {
  tier: string;
  approver_role: string;
  methods_allowed: string[];
}

export interface ProcurementOrderItem {
  procurement_item_id: number;
  item_id: number;
  item_name: string;
  ordered_qty: number;
  unit_price: number | null;
  line_total: number | null;
  uom_code: string;
  received_qty: number;
  status_code: ProcurementItemStatus;
}

export interface ProcurementOrder {
  procurement_id: number;
  procurement_no: string;
  needs_list_id: string | null;
  event_id: number;
  target_warehouse_id: number;
  warehouse_name: string;
  supplier: Supplier | null;
  procurement_method: ProcurementMethod;
  po_number: string | null;
  total_value: string;
  currency_code: string;
  status_code: ProcurementStatus;
  approval: ProcurementApproval | null;
  items: ProcurementOrderItem[];
  shipped_at: string | null;
  expected_arrival: string | null;
  received_at: string | null;
  notes_text: string;
  create_dtime: string;
  update_dtime: string;
}

export interface ProcurementListResponse {
  procurements: ProcurementOrder[];
  count: number;
}

export interface CreateProcurementPayload {
  needs_list_id?: string;
  event_id?: number;
  target_warehouse_id?: number;
  procurement_method?: ProcurementMethod;
  supplier_id?: number | null;
  items?: {
    item_id: number;
    ordered_qty: number;
    unit_price?: number;
    uom_code?: string;
  }[];
  notes?: string;
}

export interface UpdateProcurementPayload {
  supplier_id?: number | null;
  procurement_method?: ProcurementMethod;
  notes?: string;
  items?: {
    procurement_item_id?: number;
    item_id?: number;
    ordered_qty?: number;
    unit_price?: number | null;
    uom_code?: string;
  }[];
}

export interface ReceiptLine {
  procurement_item_id: number;
  received_qty: number;
  notes?: string;
}

export interface ReceivePayload {
  receipts: ReceiptLine[];
  received_by_note?: string;
}

export interface CreateSupplierPayload {
  supplier_code: string;
  supplier_name: string;
  contact_name?: string;
  phone_no?: string;
  email_text?: string;
  address_text?: string;
  parish_code?: string;
  default_lead_time_days?: number;
  is_framework_supplier?: boolean;
}

export const PROCUREMENT_STATUS_LABELS: Record<ProcurementStatus, string> = {
  DRAFT: 'Draft',
  PENDING_APPROVAL: 'Pending Approval',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
  ORDERED: 'Ordered',
  SHIPPED: 'Shipped',
  PARTIAL_RECEIVED: 'Partial Received',
  RECEIVED: 'Received',
  CANCELLED: 'Cancelled',
};

export const PROCUREMENT_STATUS_COLORS: Record<ProcurementStatus, string> = {
  DRAFT: '#9e9e9e',
  PENDING_APPROVAL: '#ff9800',
  APPROVED: '#4caf50',
  REJECTED: '#f44336',
  ORDERED: '#2196f3',
  SHIPPED: '#673ab7',
  PARTIAL_RECEIVED: '#ff9800',
  RECEIVED: '#4caf50',
  CANCELLED: '#9e9e9e',
};

export const PROCUREMENT_METHOD_LABELS: Record<ProcurementMethod, string> = {
  EMERGENCY_DIRECT: 'Emergency Direct',
  SINGLE_SOURCE: 'Single Source',
  RFQ: 'Request for Quotation',
  RESTRICTED_BIDDING: 'Restricted Bidding',
  OPEN_TENDER: 'Open Tender',
  FRAMEWORK: 'Framework Agreement',
};
