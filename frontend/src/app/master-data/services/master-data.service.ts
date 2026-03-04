import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map, shareReplay } from 'rxjs/operators';
import {
  LookupItem,
  MasterDetailResponse,
  MasterListResponse,
  MasterLookupResponse,
  MasterRecord,
  MasterSummaryResponse,
} from '../models/master-data.models';

@Injectable({ providedIn: 'root' })
export class MasterDataService {
  private http = inject(HttpClient);
  private readonly apiUrl = '/api/v1/masterdata';

  /** Lookup cache: table_key -> Observable */
  private lookupCache = new Map<string, Observable<LookupItem[]>>();

  // ── List ────────────────────────────────────────────────────────────
  list(
    tableKey: string,
    opts?: {
      status?: string;
      search?: string;
      orderBy?: string;
      limit?: number;
      offset?: number;
    },
  ): Observable<MasterListResponse> {
    let params = new HttpParams();
    if (opts?.status) params = params.set('status', opts.status);
    if (opts?.search) params = params.set('search', opts.search);
    if (opts?.orderBy) params = params.set('order_by', opts.orderBy);
    if (opts?.limit != null) params = params.set('limit', opts.limit.toString());
    if (opts?.offset != null) params = params.set('offset', opts.offset.toString());

    return this.http.get<MasterListResponse>(`${this.apiUrl}/${tableKey}/`, { params });
  }

  // ── Get single ──────────────────────────────────────────────────────
  get(tableKey: string, pk: string | number): Observable<MasterDetailResponse> {
    return this.http.get<MasterDetailResponse>(`${this.apiUrl}/${tableKey}/${pk}`);
  }

  // ── Create ──────────────────────────────────────────────────────────
  create(tableKey: string, data: MasterRecord): Observable<MasterDetailResponse> {
    return this.http.post<MasterDetailResponse>(`${this.apiUrl}/${tableKey}/`, data);
  }

  // ── Update ──────────────────────────────────────────────────────────
  update(tableKey: string, pk: string | number, data: MasterRecord): Observable<MasterDetailResponse> {
    return this.http.patch<MasterDetailResponse>(`${this.apiUrl}/${tableKey}/${pk}`, data);
  }

  // ── Inactivate ──────────────────────────────────────────────────────
  inactivate(tableKey: string, pk: string | number, versionNbr?: number): Observable<MasterDetailResponse> {
    const body: { version_nbr?: number } = {};
    if (versionNbr != null) body['version_nbr'] = versionNbr;
    return this.http.post<MasterDetailResponse>(`${this.apiUrl}/${tableKey}/${pk}/inactivate`, body);
  }

  // ── Activate ────────────────────────────────────────────────────────
  activate(tableKey: string, pk: string | number, versionNbr?: number): Observable<MasterDetailResponse> {
    const body: { version_nbr?: number } = {};
    if (versionNbr != null) body['version_nbr'] = versionNbr;
    return this.http.post<MasterDetailResponse>(`${this.apiUrl}/${tableKey}/${pk}/activate`, body);
  }

  // ── Summary counts ──────────────────────────────────────────────────
  getSummary(tableKey: string): Observable<MasterSummaryResponse> {
    return this.http.get<MasterSummaryResponse>(`${this.apiUrl}/${tableKey}/summary`);
  }

  // ── Lookup (cached) ─────────────────────────────────────────────────
  lookup(tableKey: string, activeOnly = true): Observable<LookupItem[]> {
    const cacheKey = `${tableKey}_${activeOnly}`;
    if (!this.lookupCache.has(cacheKey)) {
      let params = new HttpParams();
      if (!activeOnly) params = params.set('active_only', 'false');
      const obs$ = this.http.get<MasterLookupResponse>(
        `${this.apiUrl}/${tableKey}/lookup`, { params },
      ).pipe(
        map(res => res.items),
        shareReplay(1),
      );
      this.lookupCache.set(cacheKey, obs$);
    }
    return this.lookupCache.get(cacheKey)!;
  }

  /** Invalidate lookup cache (e.g. after creating a new record in the lookup table) */
  clearLookupCache(tableKey?: string): void {
    if (tableKey) {
      this.lookupCache.delete(`${tableKey}_true`);
      this.lookupCache.delete(`${tableKey}_false`);
    } else {
      this.lookupCache.clear();
    }
  }
}
