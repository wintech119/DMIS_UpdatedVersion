import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

interface AssignmentListResponse<T> {
  results: T[];
}

export interface UserRoleAssignment {
  role_id: number;
  code: string;
  name: string;
  assigned_at?: string | null;
}

export interface RolePermission {
  perm_id: number;
  resource: string;
  action: string;
  scope_json?: object | null;
}

export type TenantAccessLevel = 'ADMIN' | 'FULL' | 'STANDARD' | 'LIMITED' | 'READ_ONLY';

export interface TenantUser {
  user_id: number;
  username: string;
  email?: string | null;
  access_level: TenantAccessLevel;
  is_primary_tenant?: boolean;
  last_login_at?: string | null;
}

@Injectable({ providedIn: 'root' })
export class IamAssignmentService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = '/api/v1/masterdata';

  listUserRoles(userId: number): Observable<UserRoleAssignment[]> {
    return this.http
      .get<AssignmentListResponse<UserRoleAssignment>>(`${this.apiUrl}/user/${userId}/roles`)
      .pipe(map((response) => response.results));
  }

  assignUserRole(userId: number, roleId: number): Observable<void> {
    return this.http
      .post<unknown>(`${this.apiUrl}/user/${userId}/roles`, { role_id: roleId })
      .pipe(map(() => void 0));
  }

  revokeUserRole(userId: number, roleId: number): Observable<void> {
    const params = new HttpParams().set('role_id', String(roleId));
    return this.http
      .delete<unknown>(`${this.apiUrl}/user/${userId}/roles`, { params })
      .pipe(map(() => void 0));
  }

  listRolePermissions(roleId: number): Observable<RolePermission[]> {
    return this.http
      .get<AssignmentListResponse<RolePermission>>(`${this.apiUrl}/role/${roleId}/permissions`)
      .pipe(map((response) => response.results));
  }

  assignRolePermission(roleId: number, permId: number, scopeJson?: object): Observable<void> {
    const body: { perm_id: number; scope_json?: object } = { perm_id: permId };
    if (scopeJson != null) {
      body.scope_json = scopeJson;
    }
    return this.http
      .post<unknown>(`${this.apiUrl}/role/${roleId}/permissions`, body)
      .pipe(map(() => void 0));
  }

  revokeRolePermission(roleId: number, permId: number): Observable<void> {
    const params = new HttpParams().set('perm_id', String(permId));
    return this.http
      .delete<unknown>(`${this.apiUrl}/role/${roleId}/permissions`, { params })
      .pipe(map(() => void 0));
  }

  listTenantUsers(tenantId: number): Observable<TenantUser[]> {
    return this.http
      .get<AssignmentListResponse<TenantUser>>(`${this.apiUrl}/tenant/${tenantId}/users`)
      .pipe(map((response) => response.results));
  }

  assignTenantUser(tenantId: number, userId: number, accessLevel: string): Observable<void> {
    return this.http
      .post<unknown>(`${this.apiUrl}/tenant/${tenantId}/users`, {
        user_id: userId,
        access_level: accessLevel,
      })
      .pipe(map(() => void 0));
  }

  revokeTenantUser(tenantId: number, userId: number): Observable<void> {
    const params = new HttpParams().set('user_id', String(userId));
    return this.http
      .delete<unknown>(`${this.apiUrl}/tenant/${tenantId}/users`, { params })
      .pipe(map(() => void 0));
  }

  listTenantUserRoles(tenantId: number, userId: number): Observable<UserRoleAssignment[]> {
    return this.http
      .get<AssignmentListResponse<UserRoleAssignment>>(`${this.apiUrl}/tenant/${tenantId}/users/${userId}/roles`)
      .pipe(map((response) => response.results));
  }

  assignTenantUserRole(tenantId: number, userId: number, roleId: number): Observable<void> {
    return this.http
      .post<unknown>(`${this.apiUrl}/tenant/${tenantId}/users/${userId}/roles`, { role_id: roleId })
      .pipe(map(() => void 0));
  }

  revokeTenantUserRole(tenantId: number, userId: number, roleId: number): Observable<void> {
    const params = new HttpParams().set('role_id', String(roleId));
    return this.http
      .delete<unknown>(`${this.apiUrl}/tenant/${tenantId}/users/${userId}/roles`, { params })
      .pipe(map(() => void 0));
  }
}
