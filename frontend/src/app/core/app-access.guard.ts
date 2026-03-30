import { inject } from '@angular/core';
import { CanActivateFn, CanMatchFn, Router, UrlTree } from '@angular/router';
import { map, Observable } from 'rxjs';

import { AuthRbacService } from '../replenishment/services/auth-rbac.service';
import { AppAccessService } from './app-access.service';

export const appAccessGuard: CanActivateFn = (route) => evaluateAccess(route.data ?? {});

export const appAccessMatchGuard: CanMatchFn = (route) => evaluateAccess(route.data ?? {});

function evaluateAccess(
  data: Record<string, unknown>,
): Observable<boolean | UrlTree> {
  const router = inject(Router);
  const auth = inject(AuthRbacService);
  const access = inject(AppAccessService);

  return auth.ensureLoaded().pipe(
    map(() => {
      if (isRouteAllowed(access, data)) {
        return true;
      }
      return router.parseUrl('/replenishment/dashboard');
    }),
  );
}

function isRouteAllowed(access: AppAccessService, data: Record<string, unknown>): boolean {
  const accessKey = typeof data['accessKey'] === 'string' ? data['accessKey'] : null;
  if (accessKey) {
    return access.canAccessNavKey(accessKey);
  }

  const routePath = typeof data['routePath'] === 'string' ? data['routePath'] : null;
  const action = typeof data['masterAction'] === 'string' ? data['masterAction'] : 'view';

  if (!routePath) {
    return true;
  }

  if (action === 'create') {
    return access.canCreateMasterRoutePath(routePath);
  }
  if (action === 'edit') {
    return access.canEditMasterRoutePath(routePath);
  }
  return access.canAccessMasterRoutePath(routePath);
}
