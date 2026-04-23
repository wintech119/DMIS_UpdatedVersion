import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, catchError, map, of, switchMap, throwError } from 'rxjs';

import {
  AllocationCommitPayload,
  AllocationCommitResponse,
  AllocationItemGroup,
  AllocationOptionsResponse,
  ItemAllocationPreviewPayload,
  ConsolidationLegDispatchPayload,
  ConsolidationLegDispatchResponse,
  ConsolidationLegReceivePayload,
  ConsolidationLegReceiveResponse,
  ConsolidationLegsResponse,
  ConsolidationWaybillResponse,
  CreateRequestPayload,
  RequestReferenceDataResponse,
  DispatchDetailResponse,
  DispatchHandoffPayload,
  DispatchHandoffResponse,
  DispatchQueueResponse,
  EligibilityDecisionPayload,
  EligibilityDetailResponse,
  OperationsTaskListResponse,
  OverrideApprovalPayload,
  OverrideRejectPayload,
  OverrideReturnPayload,
  OverrideReviewResponse,
  PackageAbandonDraftResponse,
  PackageDetailResponse,
  PackageDraftPayload,
  PackageLockReleaseResponse,
  PackageQueueResponse,
  PartialReleaseApprovePayload,
  PartialReleaseApproveResponse,
  PartialReleaseRequestPayload,
  PartialReleaseRequestResponse,
  PickupReleasePayload,
  PickupReleaseResponse,
  ReceiptConfirmationPayload,
  ReceiptConfirmationResponse,
  RequestDetailResponse,
  RequestListResponse,
  StagingRecommendationResponse,
  UpdateRequestPayload,
  WaybillResponse,
} from '../models/operations.model';
import {
  createDispatchDetailFallback,
  normalizeAllocationCommitResponse,
  normalizeAllocationItemGroup,
  normalizeAllocationOptions,
  normalizeConsolidationLegDispatchResponse,
  normalizeConsolidationLegReceiveResponse,
  normalizeConsolidationLegsResponse,
  normalizeConsolidationWaybill,
  normalizeDispatchDetail,
  normalizeDispatchQueueItem,
  normalizeEligibilityDetail,
  normalizeOverrideReviewResponse,
  normalizePackageDetail,
  normalizePackageQueueItem,
  normalizePartialReleaseApproveResponse,
  normalizePartialReleaseRequestResponse,
  normalizePickupReleaseResponse,
  normalizeRequestDetail,
  normalizeRequestSummary,
  normalizeStagingRecommendation,
  normalizeTaskFeed,
  normalizeWaybill,
} from './operations-adapters';

type OperationsIdempotencyScope =
  | 'dispatch'
  | 'receipt'
  | 'override'
  | 'request-submit'
  | 'eligibility-decision'
  | 'allocation-commit'
  | 'package-abandon'
  | 'consolidation-leg-dispatch'
  | 'consolidation-leg-receive'
  | 'partial-release-request'
  | 'partial-release-approve'
  | 'pickup-release';

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

  getRequestReferenceData(): Observable<RequestReferenceDataResponse> {
    return this.http.get<RequestReferenceDataResponse>(`${this.apiUrl}/requests/reference-data`).pipe(
      map((response) => ({
        agencies: normalizeReferenceOptions(response.agencies),
        events: normalizeReferenceOptions(response.events),
        items: normalizeReferenceOptions(response.items),
      })),
    );
  }

  updateRequest(reliefrqstId: number, payload: UpdateRequestPayload): Observable<RequestDetailResponse> {
    return this.http.patch<RequestDetailResponse>(`${this.apiUrl}/requests/${reliefrqstId}`, payload).pipe(
      map(normalizeRequestDetail),
    );
  }

  submitRequest(
    reliefrqstId: number,
    idempotencyKey = this.createIdempotencyKey('request-submit', reliefrqstId),
  ): Observable<RequestDetailResponse> {
    return this.http.post<RequestDetailResponse>(
      `${this.apiUrl}/requests/${reliefrqstId}/submit`,
      {},
      {
        headers: {
          'Idempotency-Key': idempotencyKey,
        },
      },
    ).pipe(map(normalizeRequestDetail));
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
    idempotencyKey = this.createIdempotencyKey('eligibility-decision', reliefrqstId),
  ): Observable<EligibilityDetailResponse> {
    return this.http.post<EligibilityDetailResponse>(
      `${this.apiUrl}/eligibility/${reliefrqstId}/decision`,
      payload,
      {
        headers: {
          'Idempotency-Key': idempotencyKey,
        },
      },
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
    payload: PackageDraftPayload,
  ): Observable<PackageDetailResponse> {
    return this.http.post<PackageDetailResponse>(
      `${this.apiUrl}/packages/${reliefrqstId}/draft`,
      payload,
    ).pipe(switchMap(() => this.getPackage(reliefrqstId)));
  }

  releasePackageLock(
    reliefrqstId: number,
    force = false,
  ): Observable<PackageLockReleaseResponse> {
    return this.http.post<PackageLockReleaseResponse>(
      `${this.apiUrl}/packages/${reliefrqstId}/unlock`,
      { force },
    );
  }

  /**
   * Non-terminal abandon: releases reserved stock, cancels planned legs, drops
   * the package lock, and leaves the parent relief request in
   * APPROVED_FOR_FULFILLMENT so another officer can start fresh. Distinct from
   * the terminal cancel path.
   */
  abandonDraft(
    reliefpkgId: number,
    reason?: string,
    idempotencyKey?: string,
  ): Observable<PackageAbandonDraftResponse> {
    const body: { reason?: string } = {};
    if (reason && reason.trim().length > 0) {
      body.reason = reason.trim().slice(0, 500);
    }
    const suppliedKey = typeof idempotencyKey === 'string' ? idempotencyKey.trim() : '';
    const key = suppliedKey || this.createIdempotencyKey('package-abandon', reliefpkgId);
    return this.http.post<PackageAbandonDraftResponse>(
      `${this.apiUrl}/packages/${reliefpkgId}/abandon-draft`,
      body,
      {
        headers: {
          'Idempotency-Key': key,
        },
      },
    );
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

  getItemAllocationOptions(
    reliefrqstId: number,
    itemId: number,
    sourceWarehouseId: number,
  ): Observable<AllocationItemGroup> {
    const params = new HttpParams().set('source_warehouse_id', String(sourceWarehouseId));
    return this.http.get<unknown>(
      `${this.apiUrl}/packages/${reliefrqstId}/allocation-options/${itemId}`,
      { params },
    ).pipe(map(normalizeAllocationItemGroup));
  }

  previewItemAllocationOptions(
    reliefrqstId: number,
    itemId: number,
    payload: ItemAllocationPreviewPayload,
  ): Observable<AllocationItemGroup> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefrqstId}/allocation-options/${itemId}/preview`,
      payload,
    ).pipe(map(normalizeAllocationItemGroup));
  }

  commitAllocations(
    reliefrqstId: number,
    payload: AllocationCommitPayload,
  ): Observable<AllocationCommitResponse> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefrqstId}/allocations/commit`,
      payload,
      { headers: { 'Idempotency-Key': this.createIdempotencyKey('allocation-commit', reliefrqstId) } },
    ).pipe(map(normalizeAllocationCommitResponse));
  }

  approveOverride(
    reliefrqstId: number,
    payload: OverrideApprovalPayload,
    idempotencyKey: string,
  ): Observable<AllocationCommitResponse> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefrqstId}/allocations/override-approve`,
      payload,
      { headers: { 'Idempotency-Key': idempotencyKey } },
    ).pipe(map(normalizeAllocationCommitResponse));
  }

  returnOverride(
    reliefrqstId: number,
    payload: OverrideReturnPayload,
    idempotencyKey: string,
  ): Observable<OverrideReviewResponse> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefrqstId}/allocations/override-return`,
      payload,
      { headers: { 'Idempotency-Key': idempotencyKey } },
    ).pipe(map(normalizeOverrideReviewResponse));
  }

  rejectOverride(
    reliefrqstId: number,
    payload: OverrideRejectPayload,
    idempotencyKey: string,
  ): Observable<OverrideReviewResponse> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefrqstId}/allocations/override-reject`,
      payload,
      { headers: { 'Idempotency-Key': idempotencyKey } },
    ).pipe(map(normalizeOverrideReviewResponse));
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
      {
        headers: {
          'Idempotency-Key': this.createIdempotencyKey('dispatch', reliefpkgId),
        },
      },
    );
  }

  getWaybill(reliefpkgId: number): Observable<WaybillResponse> {
    return this.http.get<WaybillResponse>(`${this.apiUrl}/dispatch/${reliefpkgId}/waybill`).pipe(
      map(normalizeWaybill),
    );
  }

  getStagingRecommendation(reliefrqstId: number): Observable<StagingRecommendationResponse> {
    return this.http.get<unknown>(
      `${this.apiUrl}/packages/${reliefrqstId}/staging-recommendation`,
    ).pipe(map(normalizeStagingRecommendation));
  }

  getConsolidationLegs(reliefpkgId: number): Observable<ConsolidationLegsResponse> {
    return this.http.get<unknown>(
      `${this.apiUrl}/packages/${reliefpkgId}/consolidation-legs`,
    ).pipe(map(normalizeConsolidationLegsResponse));
  }

  dispatchConsolidationLeg(
    reliefpkgId: number,
    legId: number,
    payload: ConsolidationLegDispatchPayload,
  ): Observable<ConsolidationLegDispatchResponse> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefpkgId}/consolidation-legs/${legId}/dispatch`,
      payload,
      {
        headers: {
          'Idempotency-Key': this.createIdempotencyKey('consolidation-leg-dispatch', `${reliefpkgId}-${legId}`),
        },
      },
    ).pipe(map(normalizeConsolidationLegDispatchResponse));
  }

  receiveConsolidationLeg(
    reliefpkgId: number,
    legId: number,
    payload: ConsolidationLegReceivePayload,
  ): Observable<ConsolidationLegReceiveResponse> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefpkgId}/consolidation-legs/${legId}/receive`,
      payload,
      {
        headers: {
          'Idempotency-Key': this.createIdempotencyKey('consolidation-leg-receive', `${reliefpkgId}-${legId}`),
        },
      },
    ).pipe(map(normalizeConsolidationLegReceiveResponse));
  }

  getConsolidationLegWaybill(
    reliefpkgId: number,
    legId: number,
  ): Observable<ConsolidationWaybillResponse> {
    return this.http.get<unknown>(
      `${this.apiUrl}/packages/${reliefpkgId}/consolidation-legs/${legId}/waybill`,
    ).pipe(map(normalizeConsolidationWaybill));
  }

  requestPartialRelease(
    reliefpkgId: number,
    payload: PartialReleaseRequestPayload,
  ): Observable<PartialReleaseRequestResponse> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefpkgId}/partial-release/request`,
      payload,
      {
        headers: {
          'Idempotency-Key': this.createIdempotencyKey('partial-release-request', reliefpkgId),
        },
      },
    ).pipe(map(normalizePartialReleaseRequestResponse));
  }

  approvePartialRelease(
    reliefpkgId: number,
    payload: PartialReleaseApprovePayload,
  ): Observable<PartialReleaseApproveResponse> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefpkgId}/partial-release/approve`,
      payload,
      {
        headers: {
          'Idempotency-Key': this.createIdempotencyKey('partial-release-approve', reliefpkgId),
        },
      },
    ).pipe(map(normalizePartialReleaseApproveResponse));
  }

  submitPickupRelease(
    reliefpkgId: number,
    payload: PickupReleasePayload,
  ): Observable<PickupReleaseResponse> {
    return this.http.post<unknown>(
      `${this.apiUrl}/packages/${reliefpkgId}/pickup-release`,
      payload,
      {
        headers: {
          'Idempotency-Key': this.createIdempotencyKey('pickup-release', reliefpkgId),
        },
      },
    ).pipe(map(normalizePickupReleaseResponse));
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
      {
        headers: {
          'Idempotency-Key': this.createIdempotencyKey('receipt', reliefpkgId),
        },
      },
    );
  }

  createIdempotencyKey(
    scope: OperationsIdempotencyScope,
    resourceId: number | string,
  ): string {
    const randomId = globalThis.crypto?.randomUUID?.()
      ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return `${scope}-${resourceId}-${randomId}`;
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

function normalizeReferenceOptions(value: unknown): RequestReferenceDataResponse['agencies'] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .map((entry) => {
      const source = (entry ?? {}) as Record<string, unknown>;
      const parsed = Number(source['value']);
      const label = String(source['label'] ?? '').trim();
      return Number.isFinite(parsed) && parsed > 0 && label
        ? { value: parsed, label }
        : null;
    })
    .filter((entry): entry is RequestReferenceDataResponse['agencies'][number] => entry !== null);
}
