import { inject } from '@angular/core';
import { CanMatchFn, Router } from '@angular/router';
import { map } from 'rxjs/operators';

import { MasterDataAccessService } from '../services/master-data-access.service';

export const masterDataAccessGuard: CanMatchFn = (route) => {
  const access = inject(MasterDataAccessService);
  const router = inject(Router);
  const routePath = typeof route.data?.['routePath'] === 'string'
    ? route.data['routePath']
    : route.path ?? '';
  const action = typeof route.data?.['masterAction'] === 'string'
    ? route.data['masterAction']
    : 'view';

  if (!routePath) {
    return true;
  }

  return access.waitForAuthReady().pipe(
    map(() => {
      if (action === 'create') {
        return access.canCreateRoutePath(routePath) ? true : router.parseUrl('/master-data');
      }
      if (action === 'edit') {
        return access.canEditRoutePath(routePath) ? true : router.parseUrl('/master-data');
      }
      return access.canAccessRoutePath(routePath) ? true : router.parseUrl('/master-data');
    }),
  );
};
