import { Routes } from '@angular/router';
import { MasterListComponent } from './components/master-list/master-list.component';
import { MasterFormPageComponent } from './components/master-form-page/master-form-page.component';
import { MasterDetailPageComponent } from './components/master-detail-page/master-detail-page.component';
import { MasterHomeComponent } from './components/master-home/master-home.component';
import { masterDataAccessGuard } from './guards/master-data-access.guard';

/** Helper to generate routes for a page-mode table */
function pageRoutes(routePath: string): Routes {
  return [
    { path: routePath, component: MasterListComponent, data: { routePath, masterAction: 'view' }, canMatch: [masterDataAccessGuard] },
    { path: `${routePath}/new`, component: MasterFormPageComponent, data: { routePath, masterAction: 'create' }, canMatch: [masterDataAccessGuard] },
    { path: `${routePath}/:pk`, component: MasterDetailPageComponent, data: { routePath, masterAction: 'view' }, canMatch: [masterDataAccessGuard] },
    { path: `${routePath}/:pk/edit`, component: MasterFormPageComponent, data: { routePath, masterAction: 'edit' }, canMatch: [masterDataAccessGuard] },
  ];
}

/** Helper to generate routes for a dialog-mode table (list only, forms open as dialogs) */
function dialogRoutes(routePath: string): Routes {
  return [
    { path: routePath, component: MasterListComponent, data: { routePath, masterAction: 'view' }, canMatch: [masterDataAccessGuard] },
  ];
}

export const MASTER_DATA_ROUTES: Routes = [
  { path: '', component: MasterHomeComponent, pathMatch: 'full' },

  ...pageRoutes('item-categories'),
  ...dialogRoutes('uom'),
  ...dialogRoutes('countries'),
  ...dialogRoutes('currencies'),
  ...dialogRoutes('parishes'),

  ...pageRoutes('items'),
  ...pageRoutes('ifrc-families'),
  ...pageRoutes('ifrc-item-references'),
  ...pageRoutes('inventory'),
  ...pageRoutes('locations'),
  ...pageRoutes('warehouses'),
  ...pageRoutes('agencies'),
  ...pageRoutes('donors'),
  ...pageRoutes('events'),
  ...pageRoutes('suppliers'),

  ...pageRoutes('users'),
  ...pageRoutes('roles'),
  ...pageRoutes('permissions'),
  ...pageRoutes('tenant-types'),
  {
    path: 'tenants/:pk/users/:userId/roles',
    component: MasterDetailPageComponent,
    data: { routePath: 'tenants', masterAction: 'view' },
    canMatch: [masterDataAccessGuard],
  },
  ...pageRoutes('tenants'),
];

