import { Routes } from '@angular/router';

import { appAccessMatchGuard } from './core/app-access.guard';
import { environmentFeatureGuard } from './core/environment-feature.guard';

const REPLENISHMENT_ENABLED = typeof DMIS_REPLENISHMENT_ENABLED === 'undefined'
  ? true
  : DMIS_REPLENISHMENT_ENABLED;
const DEFAULT_ROUTE = REPLENISHMENT_ENABLED ? 'replenishment/dashboard' : 'master-data';

export const routes: Routes = [
  { path: '', redirectTo: DEFAULT_ROUTE, pathMatch: 'full' },
  {
    path: 'auth/login',
    loadComponent: () =>
      import('./auth/auth-pages.component').then((m) => m.DmisAuthLoginPageComponent),
  },
  {
    path: 'auth/callback',
    loadComponent: () =>
      import('./auth/auth-pages.component').then((m) => m.DmisAuthCallbackPageComponent),
  },
  {
    path: 'access-denied',
    loadComponent: () =>
      import('./auth/auth-pages.component').then((m) => m.DmisAccessDeniedPageComponent),
  },
  {
    path: 'replenishment',
    canMatch: [environmentFeatureGuard],
    data: { feature: 'replenishment' },
    loadChildren: () => import('./replenishment/replenishment.routes').then(m => m.REPLENISHMENT_ROUTES),
  },
  {
    path: 'master-data',
    canMatch: [appAccessMatchGuard],
    data: { accessKey: 'master.any' },
    loadChildren: () => import('./master-data/master-data.routes').then(m => m.MASTER_DATA_ROUTES),
  },
  {
    path: 'operations',
    canMatch: [appAccessMatchGuard, environmentFeatureGuard],
    data: { accessKey: 'operations.dashboard', feature: 'operations' },
    loadChildren: () => import('./operations/operations.routes').then(m => m.OPERATIONS_ROUTES),
  },
  { path: '**', redirectTo: DEFAULT_ROUTE }
];
