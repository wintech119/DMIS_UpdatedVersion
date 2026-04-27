import { inject } from '@angular/core';
import { CanMatchFn, Router } from '@angular/router';

const REPLENISHMENT_ENABLED = typeof DMIS_REPLENISHMENT_ENABLED === 'undefined'
  ? true
  : DMIS_REPLENISHMENT_ENABLED;
const OPERATIONS_ENABLED = typeof DMIS_OPERATIONS_ENABLED === 'undefined'
  ? true
  : DMIS_OPERATIONS_ENABLED;

export const environmentFeatureGuard: CanMatchFn = (route) => {
  const feature = route.data?.['feature'] as string | undefined;
  if (!feature) return true;
  if (feature === 'replenishment' && !REPLENISHMENT_ENABLED) {
    return inject(Router).createUrlTree(['/']);
  }
  if (feature === 'operations' && !OPERATIONS_ENABLED) {
    return inject(Router).createUrlTree(['/']);
  }
  return true;
};
