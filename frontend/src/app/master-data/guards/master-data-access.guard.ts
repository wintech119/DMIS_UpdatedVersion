import { inject } from '@angular/core';
import { CanMatchFn, UrlSegment } from '@angular/router';

import { MasterDataAccessService } from '../services/master-data-access.service';
import { evaluateProtectedRouteAccess } from '../../core/app-access.guard';

export const masterDataAccessGuard: CanMatchFn = (route) => {
  const access = inject(MasterDataAccessService);
  const routePath = typeof route.data?.['routePath'] === 'string'
    ? route.data['routePath']
    : route.path ?? '';
  const action = typeof route.data?.['masterAction'] === 'string'
    ? route.data['masterAction']
    : 'view';

  if (!routePath) {
    return true;
  }

  return evaluateProtectedRouteAccess(routePathToUrl(routePath), () => {
    if (action === 'create') {
      return access.canCreateRoutePath(routePath);
    }
    if (action === 'edit') {
      return access.canEditRoutePath(routePath);
    }
    return access.canAccessRoutePath(routePath);
  });
};

function routePathToUrl(routePath: string): string {
  const segments = String(routePath ?? '')
    .split('/')
    .map((segment) => segment.trim())
    .filter(Boolean)
    .map((segment) => new UrlSegment(segment, {}));
  return `/${segments.map((segment) => segment.path).join('/')}`;
}
