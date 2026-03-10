import { Routes } from '@angular/router';
import { MasterListComponent } from './components/master-list/master-list.component';
import { MasterFormPageComponent } from './components/master-form-page/master-form-page.component';
import { MasterDetailPageComponent } from './components/master-detail-page/master-detail-page.component';
import { MasterHomeComponent } from './components/master-home/master-home.component';

/** Helper to generate routes for a page-mode table */
function pageRoutes(routePath: string): Routes {
  return [
    { path: routePath, component: MasterListComponent, data: { routePath } },
    { path: `${routePath}/new`, component: MasterFormPageComponent, data: { routePath } },
    { path: `${routePath}/:pk`, component: MasterDetailPageComponent, data: { routePath } },
    { path: `${routePath}/:pk/edit`, component: MasterFormPageComponent, data: { routePath } },
  ];
}

/** Helper to generate routes for a dialog-mode table (list only, forms open as dialogs) */
function dialogRoutes(routePath: string): Routes {
  return [
    { path: routePath, component: MasterListComponent, data: { routePath } },
  ];
}

export const MASTER_DATA_ROUTES: Routes = [
  { path: '', component: MasterHomeComponent, pathMatch: 'full' },

  ...dialogRoutes('item-categories'),
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
  ...pageRoutes('custodians'),
  ...pageRoutes('donors'),
  ...pageRoutes('events'),
  ...pageRoutes('suppliers'),
];
