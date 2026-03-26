import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, of, switchMap, throwError } from 'rxjs';

import {
  AllocationCommitPayload,
  AllocationCommitResponse,
  AllocationOptionsResponse,
  CreateRequestPayload,
  DispatchDetailResponse,
  DispatchHandoffPayload,
  DispatchHandoffResponse,
  DispatchQueueResponse,
  EligibilityDecisionPayload,
  EligibilityDetailResponse,
  OperationsTaskListResponse,
  OverrideApprovalPayload,
  PackageDetailResponse,
  PackageQueueResponse,
  ReceiptConfirmationPayload,
  ReceiptConfirmationResponse,
  RequestDetailResponse,
  RequestListResponse,
  UpdateRequestPayload,
  WaybillResponse,
} from '../models/operations.model';
import {
  createDispatchDetailFallback,
  normalizeAllocationOptions,
  normalizeDispatchDetail,
  normalizeDispatchQueueItem,
  normalizeEligibilityDetail,
  normalizePackageDetail,
  normalizePackageQueueItem,
  normalizeRequestDetail,
  normalizeRequestSummary,
  normalizeTaskFeed,
  normalizeWaybill,
} from './operations-adapters';

@Injectable({ providedIn: 'root' })
export class OperationsService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = '/api/v1/operations';

  listRequests(filter?: string): Observable<RequestListResponse> {
    let params = new HttpParams();
    if (filter) {
      params = params.set('filter', filter);
    }
    return this.http.get<RequestListResponse>(`${this.apiUrl}/requests`, { params }).pipe(
      map((response) => ({
        results: (response.results ?? []).map(normalizeRequestSummary),
      })),
    );
  }

  createRequest(payload: CreateRequestPayload): Observable<RequestDetailResponse> {
    return this.http.post<RequestDetailResponse>(`${this.apiUrl}/requests`, payload).pipe(
      map(normalizeRequestDetail),
    );
  }

  getRequest(reliefrqstId: number): Observable<RequestDetailResponse> {
    return this.http.get<RequestDetailResponse>(`${this.apiUrl}/requests/${reliefrqstId}`).pipe(
      map(normalizeRequestDetail),
    );
  }

  updateRequest(reliefrqstId: number, payload: UpdateRequestPayload): Observable<RequestDetailResponse> {
    return this.http.patch<RequestDetailResponse>(`${this.apiUrl}/requests/${reliefrqstId}`, payload).pipe(
      map(normalizeRequestDetail),
    );
  }

  submitRequest(reliefrqstId: number): Observable<RequestDetailResponse> {
    return this.http.post<RequestDetailResponse>(`${this.apiUrl}/requests/${reliefrqstId}/submit`, {}).pipe(
      map(normalizeRequestDetail),
    );
  }

  getEligibilityQueue(): Observable<RequestListResponse> {
    return this.http.get<RequestListResponse>(`${this.apiUrl}/eligibility/queue`).pipe(
      map((response) => ({
        results: (response.results ?? []).map(normalizeRequestSummary),
      })),
    );
  }

  getEligibilityDetail(reliefrqstId: number): Observable<EligibilityDetailResponse> {
    return this.http.get<EligibilityDetailResponse>(`${this.apiUrl}/eligibility/${reliefrqstId}`).pipe(
      map(normalizeEligibilityDetail),
    );
  }

  submitEligibilityDecision(
    reliefrqstId: number,
    payload: EligibilityDecisionPayload,
  ): Observable<EligibilityDetailResponse> {
    return this.http.post<EligibilityDetailResponse>(
      `${this.apiUrl}/eligibility/${reliefrqstId}/decision`,
      payload,
    ).pipe(map(normalizeEligibilityDetail));
  }

  getPackagesQueue(): Observable<PackageQueueResponse> {
    return this.http.get<PackageQueueResponse>(`${this.apiUrl}/packages/queue`).pipe(
      map((response) => ({
        results: (response.results ?? []).map(normalizePackageQueueItem),
      })),
    );
  }

  getPackage(reliefrqstId: number): Observable<PackageDetailResponse> {
    return this.http.get<PackageDetailResponse>(`${this.apiUrl}/packages/${reliefrqstId}`).pipe(
      map(normalizePackageDetail),
    );
  }

  savePackageDraft(
    reliefrqstId: number,
    payload: { to_inventory_id?: number; transport_mode?: string; comments_text?: string },
  ): Observable<PackageDetailResponse> {
    return this.http.post<PackageDetailResponse>(
      `${this.apiUrl}/packages/${reliefrqstId}/draft`,
      payload,
    ).pipe(switchMap(() => this.getPackage(reliefrqstId)));
  }

  getAllocationOptions(
    reliefrqstId: number,
    sourceWarehouseId?: number,
  ): Observable<AllocationOptionsResponse> {
    let params = new HttpParams();
    if (sourceWarehouseId != null) {
      params = params.set('source_warehouse_id', String(sourceWarehouseId));
    }
    return this.http.get<AllocationOptionsResponse>(
      `${this.apiUrl}/packages/${reliefrqstId}/allocation-options`,
      { params },
    ).pipe(map(normalizeAllocationOptions));
  }

  commitAllocations(
    reliefrqstId: number,
    payload: AllocationCommitPayload,
  ): Observable<AllocationCommitResponse> {
    return this.http.post<AllocationCommitResponse>(
      `${this.apiUrl}/packages/${reliefrqstId}/allocations/commit`,
      payload,
    );
  }

  approveOverride(
    reliefrqstId: number,
    payload: OverrideApprovalPayload,
  ): Observable<AllocationCommitResponse> {
    return this.http.post<AllocationCommitResponse>(
      `${this.apiUrl}/packages/${reliefrqstId}/allocations/override-approve`,
      payload,
    );
  }

  getDispatchQueue(): Observable<DispatchQueueResponse> {
    return this.http.get<DispatchQueueResponse>(`${this.apiUrl}/dispatch/queue`).pipe(
      map((response) => ({
        results: (response.results ?? [])
          .map(normalizeDispatchQueueItem)
          .sort((left, right) => {
            const urgencyRank = this.rankUrgency(left.request?.urgency_ind)
              - this.rankUrgency(right.request?.urgency_ind);
            if (urgencyRank !== 0) {
              return urgencyRank;
            }
            return String(right.request?.request_date ?? '').localeCompare(String(left.request?.request_date ?? ''));
          }),
      })),
    );
  }

  getDispatchDetail(reliefpkgId: number): Observable<DispatchDetailResponse> {
    return this.http.get<DispatchDetailResponse>(`${this.apiUrl}/dispatch/${reliefpkgId}`).pipe(
      map(normalizeDispatchDetail),
      catchError((error: HttpErrorResponse) => {
        if (!this.isPreDispatchWaybillError(error)) {
          return throwError(() => error);
        }
        return this.getDispatchQueue().pipe(
          map((response) => response.results.find((entry) => entry.reliefpkg_id === reliefpkgId)),
          switchMap((queueEntry) => {
            if (!queueEntry?.reliefrqst_id) {
              return throwError(() => error);
            }
            return this.getPackage(queueEntry.reliefrqst_id).pipe(
              map((detail) => createDispatchDetailFallback(detail)),
              switchMap((fallback) => fallback ? of(fallback) : throwError(() => error)),
            );
          }),
        );
      }),
    );
  }

  submitDispatchHandoff(
    reliefpkgId: number,
    payload: DispatchHandoffPayload = {},
  ): Observable<DispatchHandoffResponse> {
    return this.http.post<DispatchHandoffResponse>(
      `${this.apiUrl}/dispatch/${reliefpkgId}/handoff`,
      payload,
    );
  }

  getWaybill(reliefpkgId: number): Observable<WaybillResponse> {
    return this.http.get<WaybillResponse>(`${this.apiUrl}/dispatch/${reliefpkgId}/waybill`).pipe(
      map(normalizeWaybill),
    );
  }

  getTasks(): Observable<OperationsTaskListResponse> {
    return this.http.get<unknown>(`${this.apiUrl}/tasks`).pipe(map(normalizeTaskFeed));
  }

  confirmReceipt(
    reliefpkgId: number,
    payload: ReceiptConfirmationPayload,
  ): Observable<ReceiptConfirmationResponse> {
    return this.http.post<ReceiptConfirmationResponse>(
      `${this.apiUrl}/receipt-confirmation/${reliefpkgId}`,
      payload,
    );
  }

  private isPreDispatchWaybillError(error: HttpErrorResponse): boolean {
    if (error.status !== 400) {
      return false;
    }

    const payload = (error.error ?? {}) as Record<string, unknown>;
    const directWaybill = typeof payload['waybill'] === 'string'
      ? payload['waybill']
      : '';
    const detail = typeof payload['detail'] === 'string'
      ? payload['detail']
      : '';

    return [directWaybill, detail]
      .join(' ')
      .toLowerCase()
      .includes('waybill not available');
  }

  private rankUrgency(value: unknown): number {
    switch (String(value ?? '').trim().toUpperCase()) {
      case 'C':
        return 0;
      case 'H':
        return 1;
      case 'M':
        return 2;
      case 'L':
        return 3;
      default:
        return 4;
    }
  }
}
