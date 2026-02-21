import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { StockStatusResponse, StockStatusItem, calculateSeverity } from '../models/stock-status.model';
import {
  DonationsResponse,
  MySubmissionsResponse,
  NeedsListFulfillmentSourcesResponse,
  NeedsListResponse,
  NeedsListSummaryVersionResponse,
  ProcurementExportResponse,
  TransferDraft,
  TransferDraftsResponse
} from '../models/needs-list.model';
import {
  CreateProcurementPayload,
  CreateSupplierPayload,
  ProcurementListResponse,
  ProcurementOrder,
  ReceivePayload,
  Supplier,
  UpdateProcurementPayload,
} from '../models/procurement.model';

export interface ActiveEvent {
  event_id: number;
  event_name: string;
  status: string;
  phase: string;
  declaration_date: string;
}

export interface Warehouse {
  warehouse_id: number;
  warehouse_name: string;
}

export interface WarehousesResponse {
  warehouses: Warehouse[];
  count: number;
}

export interface ApproveNeedsListPayload {
  notes?: string;
}

export interface RejectNeedsListPayload {
  reason: string;
  notes?: string;
}

export interface ReturnNeedsListPayload {
  reason_code: string;
  reason?: string;
}

export interface CreateNeedsListDraftPayload {
  event_id: number;
  warehouse_id: number;
  phase: string;
  as_of_datetime?: string;
  selected_item_keys?: string[];
  selected_method?: 'A' | 'B' | 'C';
}

export interface NeedsListLineOverridePayload {
  item_id: number;
  overridden_qty: number;
  reason: string;
}

export interface NeedsListListOptions {
  mine?: boolean;
  eventId?: number;
  warehouseId?: number;
  phase?: string;
  includeClosed?: boolean;
}

export interface MySubmissionsQueryParams {
  status?: string;
  warehouse_id?: number;
  event_id?: number;
  date_from?: string;
  date_to?: string;
  sort_by?: 'date' | 'status' | 'warehouse';
  sort_order?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
}

@Injectable({
  providedIn: 'root'
})
export class ReplenishmentService {
  private http = inject(HttpClient);

  private readonly apiUrl = '/api/v1/replenishment';

  /**
   * Get the currently active event
   * Returns null if no active event exists
   */
  getActiveEvent(): Observable<ActiveEvent | null> {
    return this.http.get<ActiveEvent | null>(`${this.apiUrl}/active-event`);
  }

  /**
   * Get all active warehouses
   */
  getAllWarehouses(): Observable<Warehouse[]> {
    return this.http.get<WarehousesResponse>(`${this.apiUrl}/warehouses`).pipe(
      map(response => response.warehouses)
    );
  }

  getStockStatus(eventId: number, warehouseId: number, phase: string): Observable<StockStatusResponse> {
    return this.http.post<StockStatusResponse>(`${this.apiUrl}/needs-list/preview`, {
      event_id: eventId,
      warehouse_id: warehouseId,
      phase: phase
    }).pipe(
      map(response => this.enrichStockStatusResponse(response))
    );
  }

  /**
   * Get stock status for multiple warehouses (for wizard)
   */
  getStockStatusMulti(
    eventId: number,
    warehouseIds: number[],
    phase: string,
    asOfDatetime?: string
  ): Observable<NeedsListResponse> {
    const payload: {
      event_id: number;
      warehouse_ids: number[];
      phase: string;
      as_of_datetime?: string;
    } = {
      event_id: eventId,
      warehouse_ids: warehouseIds,
      phase: phase
    };

    if (asOfDatetime) {
      payload.as_of_datetime = asOfDatetime;
    }

    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/preview-multi`,
      payload
    ).pipe(
      map(response => ({
        ...response,
        items: response.items.map(item => ({
          ...item,
          time_to_stockout_hours: this.parseTimeToStockout(item.time_to_stockout) ?? undefined,
          severity: calculateSeverity(this.parseTimeToStockout(item.time_to_stockout))
        }))
      }))
    );
  }

  createNeedsListDraft(payload: CreateNeedsListDraftPayload): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/draft`,
      payload
    );
  }

  editNeedsListLines(
    needsListId: string,
    overrides: NeedsListLineOverridePayload[]
  ): Observable<NeedsListResponse> {
    return this.http.patch<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/lines`,
      overrides
    );
  }

  submitNeedsListForApproval(needsListId: string): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/submit`,
      {}
    );
  }

  approveNeedsList(
    needsListId: string,
    payload: ApproveNeedsListPayload = {}
  ): Observable<NeedsListResponse> {
    const notes = payload.notes?.trim();
    const body = notes ? { comment: notes } : {};

    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/approve`,
      body
    );
  }

  rejectNeedsList(
    needsListId: string,
    payload: RejectNeedsListPayload
  ): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/reject`,
      payload
    );
  }

  listNeedsLists(
    statuses?: string[],
    options: NeedsListListOptions = {}
  ): Observable<{ needs_lists: NeedsListResponse[]; count: number }> {
    const query = new URLSearchParams();
    if (statuses?.length) {
      query.set('status', statuses.join(','));
    }
    if (options.mine) {
      query.set('mine', 'true');
    }
    if (Number.isInteger(options.eventId) && (options.eventId ?? 0) > 0) {
      query.set('event_id', String(options.eventId));
    }
    if (Number.isInteger(options.warehouseId) && (options.warehouseId ?? 0) > 0) {
      query.set('warehouse_id', String(options.warehouseId));
    }
    if (options.phase) {
      query.set('phase', options.phase);
    }
    if (options.includeClosed !== undefined) {
      query.set('include_closed', options.includeClosed ? 'true' : 'false');
    }
    const suffix = query.toString();

    return this.http.get<{ needs_lists: NeedsListResponse[]; count: number }>(
      `${this.apiUrl}/needs-list/${suffix ? `?${suffix}` : ''}`
    );
  }

  getMySubmissions(
    params: MySubmissionsQueryParams = {}
  ): Observable<MySubmissionsResponse> {
    const query = new URLSearchParams();
    if (params.status) {
      query.set('status', params.status);
    }
    if (Number.isInteger(params.warehouse_id) && (params.warehouse_id ?? 0) > 0) {
      query.set('warehouse_id', String(params.warehouse_id));
    }
    if (Number.isInteger(params.event_id) && (params.event_id ?? 0) > 0) {
      query.set('event_id', String(params.event_id));
    }
    if (params.date_from) {
      query.set('date_from', params.date_from);
    }
    if (params.date_to) {
      query.set('date_to', params.date_to);
    }
    if (params.sort_by) {
      query.set('sort_by', params.sort_by);
    }
    if (params.sort_order) {
      query.set('sort_order', params.sort_order);
    }
    if (Number.isInteger(params.page) && (params.page ?? 0) > 0) {
      query.set('page', String(params.page));
    }
    if (Number.isInteger(params.page_size) && (params.page_size ?? 0) > 0) {
      query.set('page_size', String(params.page_size));
    }

    const suffix = query.toString();
    return this.http.get<MySubmissionsResponse>(
      `${this.apiUrl}/needs-list/my-submissions/${suffix ? `?${suffix}` : ''}`
    );
  }

  getNeedsListSummaryVersion(
    needsListId: string
  ): Observable<NeedsListSummaryVersionResponse> {
    return this.http.get<NeedsListSummaryVersionResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/summary-version`
    );
  }

  getNeedsListFulfillmentSources(
    needsListId: string
  ): Observable<NeedsListFulfillmentSourcesResponse> {
    return this.http.get<NeedsListFulfillmentSourcesResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/fulfillment-sources`
    );
  }

  bulkSubmitDrafts(ids: string[]): Observable<{ submitted_ids: string[]; errors: { id: string; error: string }[]; count: number }> {
    return this.http.post<{ submitted_ids: string[]; errors: { id: string; error: string }[]; count: number }>(
      `${this.apiUrl}/needs-list/bulk-submit/`,
      { ids }
    );
  }

  bulkDeleteDrafts(
    ids: string[],
    reason = 'Removed from My Submissions.'
  ): Observable<{ cancelled_ids: string[]; errors: { id: string; error: string }[]; count: number }> {
    return this.http.post<{ cancelled_ids: string[]; errors: { id: string; error: string }[]; count: number }>(
      `${this.apiUrl}/needs-list/bulk-delete/`,
      { ids, reason }
    );
  }

  getNeedsList(id: string): Observable<NeedsListResponse> {
    return this.http.get<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(id)}`
    );
  }

  returnNeedsList(id: string, payload: ReturnNeedsListPayload): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(id)}/return`,
      payload
    );
  }

  escalateNeedsList(id: string, reason: string): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(id)}/escalate`,
      { reason }
    );
  }

  addReviewComments(
    id: string,
    comments: { item_id: number; comment: string }[]
  ): Observable<NeedsListResponse> {
    return this.http.patch<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(id)}/review-comments`,
      comments
    );
  }

  sendReviewReminder(id: string): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(id)}/review/reminder`,
      {}
    );
  }

  startPreparation(needsListId: string): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/start-preparation`,
      {}
    );
  }

  markDispatched(needsListId: string): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/mark-dispatched`,
      {}
    );
  }

  markReceived(needsListId: string): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/mark-received`,
      {}
    );
  }

  markCompleted(needsListId: string): Observable<NeedsListResponse> {
    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/mark-completed`,
      {}
    );
  }

  // ── Transfer Draft Methods (Horizon A) ──────────────────────────────────

  generateTransfers(needsListId: string): Observable<TransferDraftsResponse> {
    return this.http.post<TransferDraftsResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/generate-transfers`,
      {}
    );
  }

  getTransfers(needsListId: string): Observable<TransferDraftsResponse> {
    return this.http.get<TransferDraftsResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/transfers`
    );
  }

  updateTransferDraft(
    needsListId: string,
    transferId: number,
    updates: { reason: string; items: { item_id: number; item_qty: number }[] }
  ): Observable<{ transfer: TransferDraft; warnings: string[] }> {
    return this.http.patch<{ transfer: TransferDraft; warnings: string[] }>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/transfers/${transferId}`,
      updates
    );
  }

  confirmTransfer(
    needsListId: string,
    transferId: number
  ): Observable<{ transfer: TransferDraft; warnings: string[] }> {
    return this.http.post<{ transfer: TransferDraft; warnings: string[] }>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/transfers/${transferId}/confirm`,
      {}
    );
  }

  // ── Donation Methods (Horizon B) ────────────────────────────────────────

  getDonations(needsListId: string): Observable<DonationsResponse> {
    return this.http.get<DonationsResponse>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/donations`
    );
  }

  allocateDonation(
    needsListId: string,
    allocations: { item_id: number; donation_id: number; allocated_qty: number }[]
  ): Observable<{ needs_list_id: string; allocated_count: number; warnings: string[] }> {
    return this.http.post<{ needs_list_id: string; allocated_count: number; warnings: string[] }>(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/donations/allocate`,
      allocations
    );
  }

  exportDonationNeeds(needsListId: string, format: 'csv' | 'pdf' = 'csv'): Observable<Blob> {
    return this.http.get(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/donations/export?format=${format}`,
      { responseType: 'blob' }
    );
  }

  // ── Procurement Methods (Horizon C) ─────────────────────────────────────

  exportProcurementNeeds(needsListId: string, format: 'csv' | 'pdf' = 'csv'): Observable<Blob> {
    return this.http.get(
      `${this.apiUrl}/needs-list/${encodeURIComponent(needsListId)}/procurement/export?format=${format}`,
      { responseType: 'blob' }
    );
  }

  createProcurement(payload: CreateProcurementPayload): Observable<ProcurementOrder> {
    return this.http.post<ProcurementOrder>(`${this.apiUrl}/procurement/`, payload);
  }

  listProcurements(filters?: {
    status?: string;
    warehouse_id?: number;
    event_id?: number;
    needs_list_id?: string;
    supplier_id?: number;
  }): Observable<ProcurementListResponse> {
    const query = new URLSearchParams();
    if (filters) {
      Object.entries(filters).forEach(([key, val]) => {
        if (val !== undefined && val !== null) {
          query.set(key, String(val));
        }
      });
    }
    const suffix = query.toString();
    return this.http.get<ProcurementListResponse>(
      `${this.apiUrl}/procurement/${suffix ? `?${suffix}` : ''}`
    );
  }

  getProcurement(id: number): Observable<ProcurementOrder> {
    return this.http.get<ProcurementOrder>(`${this.apiUrl}/procurement/${id}`);
  }

  updateProcurement(id: number, updates: UpdateProcurementPayload): Observable<ProcurementOrder> {
    return this.http.patch<ProcurementOrder>(`${this.apiUrl}/procurement/${id}`, updates);
  }

  submitProcurement(id: number): Observable<ProcurementOrder> {
    return this.http.post<ProcurementOrder>(`${this.apiUrl}/procurement/${id}/submit`, {});
  }

  approveProcurement(id: number, notes?: string): Observable<ProcurementOrder> {
    return this.http.post<ProcurementOrder>(
      `${this.apiUrl}/procurement/${id}/approve`,
      notes ? { notes } : {}
    );
  }

  rejectProcurement(id: number, reason: string): Observable<ProcurementOrder> {
    return this.http.post<ProcurementOrder>(
      `${this.apiUrl}/procurement/${id}/reject`,
      { reason }
    );
  }

  markProcurementOrdered(id: number, poNumber: string): Observable<ProcurementOrder> {
    return this.http.post<ProcurementOrder>(
      `${this.apiUrl}/procurement/${id}/order`,
      { po_number: poNumber }
    );
  }

  markProcurementShipped(
    id: number,
    details: { shipped_at?: string; expected_arrival?: string }
  ): Observable<ProcurementOrder> {
    return this.http.post<ProcurementOrder>(
      `${this.apiUrl}/procurement/${id}/ship`,
      details
    );
  }

  receiveProcurementItems(id: number, payload: ReceivePayload): Observable<ProcurementOrder> {
    return this.http.post<ProcurementOrder>(
      `${this.apiUrl}/procurement/${id}/receive`,
      payload
    );
  }

  cancelProcurement(id: number, reason: string): Observable<ProcurementOrder> {
    return this.http.post<ProcurementOrder>(
      `${this.apiUrl}/procurement/${id}/cancel`,
      { reason }
    );
  }

  // ── Supplier Methods ──────────────────────────────────────────────────────

  listSuppliers(): Observable<{ suppliers: Supplier[]; count: number }> {
    return this.http.get<{ suppliers: Supplier[]; count: number }>(
      `${this.apiUrl}/suppliers/`
    );
  }

  createSupplier(payload: CreateSupplierPayload): Observable<Supplier> {
    return this.http.post<Supplier>(`${this.apiUrl}/suppliers/`, payload);
  }

  getSupplier(id: number): Observable<Supplier> {
    return this.http.get<Supplier>(`${this.apiUrl}/suppliers/${id}`);
  }

  updateSupplier(id: number, updates: Partial<CreateSupplierPayload>): Observable<Supplier> {
    return this.http.patch<Supplier>(`${this.apiUrl}/suppliers/${id}`, updates);
  }

  private enrichStockStatusResponse(response: StockStatusResponse): StockStatusResponse {
    const enrichedItems = response.items.map(item => this.enrichStockItem(item));
    return {
      ...response,
      items: enrichedItems
    };
  }

  private enrichStockItem(item: StockStatusItem): StockStatusItem {
    const timeToStockoutHours = this.parseTimeToStockout(item.time_to_stockout);
    const severity = calculateSeverity(timeToStockoutHours);
    const isEstimated = (item.warnings ?? []).includes('burn_rate_estimated');

    return {
      ...item,
      time_to_stockout_hours: timeToStockoutHours ?? undefined,
      severity,
      is_estimated: isEstimated
    };
  }

  private parseTimeToStockout(value: number | string | undefined): number | null {
    if (value === undefined || value === null || value === 'N/A') {
      return null;
    }
    if (typeof value === 'number') {
      return value;
    }
    const parsed = parseFloat(value);
    return isNaN(parsed) ? null : parsed;
  }
}
