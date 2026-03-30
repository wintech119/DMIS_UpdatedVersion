import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, finalize, map, of, shareReplay } from 'rxjs';

export interface TenantMembershipSummary {
  tenant_id: number | null;
  tenant_code: string | null;
  tenant_name: string | null;
  tenant_type: string | null;
  is_primary: boolean;
  access_level: string | null;
}

export interface TenantContextSummary {
  requested_tenant_id: number | null;
  active_tenant_id: number | null;
  active_tenant_code: string | null;
  active_tenant_type: string | null;
  is_neoc: boolean;
  can_read_all_tenants: boolean;
  can_act_cross_tenant: boolean;
  memberships: TenantMembershipSummary[];
}

export type OriginMode = 'self' | 'for_subordinate' | 'on_behalf_bridge';

export interface OperationsCapabilities {
  can_create_relief_request: boolean;
  can_create_relief_request_on_behalf: boolean;
  relief_request_submission_mode: OriginMode | null;
  default_requesting_tenant_id: number | null;
  allowed_origin_modes: OriginMode[];
}

interface WhoAmIResponse {
  user_id?: string | null;
  username?: string | null;
  roles?: string[];
  permissions?: string[];
  tenant_context?: Partial<TenantContextSummary> | null;
  operations_capabilities?: Partial<OperationsCapabilities> | null;
}

@Injectable({
  providedIn: 'root'
})
export class AuthRbacService {
  private readonly http = inject(HttpClient);
  private pendingLoad$?: Observable<void>;

  readonly roles = signal<string[]>([]);
  readonly permissions = signal<string[]>([]);
  readonly currentUserRef = signal<string | null>(null);
  readonly tenantContext = signal<TenantContextSummary | null>(null);
  readonly operationsCapabilities = signal<OperationsCapabilities | null>(null);
  readonly loading = signal(false);
  readonly loaded = signal(false);

  load(): void {
    this.ensureLoaded().subscribe();
  }

  refresh(): void {
    this.ensureLoaded(true).subscribe();
  }

  ensureLoaded(force = false): Observable<void> {
    if (!force && this.loaded()) {
      return of(void 0);
    }
    if (!force && this.pendingLoad$) {
      return this.pendingLoad$;
    }
    return this.fetchWhoAmI(force);
  }

  hasPermission(permission: string): boolean {
    return this.permissions().includes(permission.toLowerCase());
  }

  private fetchWhoAmI(force = false): Observable<void> {
    if (force) {
      this.loaded.set(false);
    }
    this.loading.set(true);
    const request$ = this.http.get<WhoAmIResponse>('/api/v1/auth/whoami/').pipe(
      map((data) => {
        const roles = [
          ...new Set((data.roles ?? []).map((role) => String(role).trim()).filter(Boolean))
        ];
        const permissions = [
          ...new Set(
            (data.permissions ?? [])
              .map((permission) => String(permission).trim().toLowerCase())
              .filter(Boolean)
          )
        ];
        const currentUserRef = String(data.username ?? data.user_id ?? '').trim();

        this.roles.set(roles);
        this.permissions.set(permissions);
        this.currentUserRef.set(currentUserRef || null);
        this.tenantContext.set(normalizeTenantContext(data.tenant_context));
        this.operationsCapabilities.set(normalizeOperationsCapabilities(data.operations_capabilities));
      }),
      catchError(() => {
        this.roles.set([]);
        this.permissions.set([]);
        this.currentUserRef.set(null);
        this.tenantContext.set(null);
        this.operationsCapabilities.set(null);
        return of(void 0);
      }),
      map(() => void 0),
      finalize(() => {
        this.loaded.set(true);
        this.loading.set(false);
        this.pendingLoad$ = undefined;
      }),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    this.pendingLoad$ = request$;
    return request$;
  }
}

function normalizeTenantContext(source: Partial<TenantContextSummary> | null | undefined): TenantContextSummary | null {
  if (!source || typeof source !== 'object') {
    return null;
  }

  return {
    requested_tenant_id: asNullableNumber(source.requested_tenant_id),
    active_tenant_id: asNullableNumber(source.active_tenant_id),
    active_tenant_code: asNullableString(source.active_tenant_code),
    active_tenant_type: asNullableString(source.active_tenant_type),
    is_neoc: Boolean(source.is_neoc),
    can_read_all_tenants: Boolean(source.can_read_all_tenants),
    can_act_cross_tenant: Boolean(source.can_act_cross_tenant),
    memberships: Array.isArray(source.memberships)
      ? source.memberships.map((membership) => ({
        tenant_id: asNullableNumber(membership?.tenant_id),
        tenant_code: asNullableString(membership?.tenant_code),
        tenant_name: asNullableString(membership?.tenant_name),
        tenant_type: asNullableString(membership?.tenant_type),
        is_primary: Boolean(membership?.is_primary),
        access_level: asNullableString(membership?.access_level),
      }))
      : [],
  };
}

const VALID_ORIGIN_MODES = new Set<OriginMode>(['self', 'for_subordinate', 'on_behalf_bridge']);

function normalizeOperationsCapabilities(
  source: Partial<OperationsCapabilities> | null | undefined,
): OperationsCapabilities | null {
  if (!source || typeof source !== 'object') {
    return null;
  }

  const submissionMode = String(source.relief_request_submission_mode ?? '').trim().toLowerCase();
  const validMode: OriginMode | null =
    VALID_ORIGIN_MODES.has(submissionMode as OriginMode) ? submissionMode as OriginMode : null;

  return {
    can_create_relief_request: Boolean(source.can_create_relief_request),
    can_create_relief_request_on_behalf: Boolean(source.can_create_relief_request_on_behalf),
    relief_request_submission_mode: validMode,
    default_requesting_tenant_id: asNullableNumber(source.default_requesting_tenant_id),
    allowed_origin_modes: normalizeAllowedOriginModes(source, validMode),
  };
}

function normalizeAllowedOriginModes(
  source: Record<string, unknown>,
  fallbackMode: OriginMode | null,
): OriginMode[] {
  const raw = source['allowed_origin_modes'];
  if (Array.isArray(raw)) {
    return raw
      .map((entry: unknown) => String(entry ?? '').trim().toLowerCase())
      .filter((mode): mode is OriginMode => VALID_ORIGIN_MODES.has(mode as OriginMode));
  }
  return fallbackMode ? [fallbackMode] : [];
}

function asNullableString(value: unknown): string | null {
  const normalized = String(value ?? '').trim();
  return normalized ? normalized : null;
}

function asNullableNumber(value: unknown): number | null {
  if (value == null || value === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
