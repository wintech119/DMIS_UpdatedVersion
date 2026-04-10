import { Injectable, computed, inject } from '@angular/core';
import { Observable } from 'rxjs';

import type {
  AuthPrincipal,
} from '../../core/auth-session.service';
import { AuthSessionService } from '../../core/auth-session.service';

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

@Injectable({
  providedIn: 'root'
})
export class AuthRbacService {
  private readonly authSession = inject(AuthSessionService);

  readonly roles = computed(() => this.currentPrincipal()?.roles ?? []);
  readonly permissions = computed(() => this.currentPrincipal()?.permissions ?? []);
  readonly actorRef = computed(() => {
    const principal = this.currentPrincipal();
    return principal?.user_id ?? principal?.username ?? null;
  });
  readonly currentUserRef = computed(() => {
    const principal = this.currentPrincipal();
    return principal?.username ?? principal?.user_id ?? null;
  });
  readonly tenantContext = computed(() => this.currentPrincipal()?.tenant_context ?? null);
  readonly operationsCapabilities = computed(() => this.currentPrincipal()?.operations_capabilities ?? null);
  readonly loading = computed(() => this.authSession.bootstrapping());
  readonly loaded = computed(() => this.authSession.principalLoaded());

  load(): void {
    this.ensureLoaded().subscribe();
  }

  refresh(): void {
    this.authSession.refreshPrincipal().subscribe();
  }

  ensureLoaded(force = false): Observable<void> {
    if (force) {
      return this.authSession.refreshPrincipal();
    }
    return this.authSession.ensureInitialized();
  }

  hasPermission(permission: string): boolean {
    return this.permissions().includes(permission.toLowerCase());
  }

  private currentPrincipal(): AuthPrincipal | null {
    return this.authSession.principal();
  }
}
