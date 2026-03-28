import { Routes } from '@angular/router';

import { appAccessMatchGuard } from './core/app-access.guard';

export const routes: Routes = [
  { path: '', redirectTo: 'replenishment/dashboard', pathMatch: 'full' },
  {
    path: 'replenishment',
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
    canMatch: [appAccessMatchGuard],
    data: { accessKey: 'operations.dashboard' },
    loadChildren: () => import('./operations/operations.routes').then(m => m.OPERATIONS_ROUTES),
  },
  { path: '**', redirectTo: 'replenishment/dashboard' }
];
