import { Routes } from '@angular/router';

import { StockStatusDashboardComponent } from './replenishment/stock-status-dashboard/stock-status-dashboard.component';
import { NeedsListPreviewComponent } from './replenishment/needs-list-preview/needs-list-preview.component';
import { NeedsListWizardComponent } from './replenishment/needs-list-wizard/needs-list-wizard.component';

export const routes: Routes = [
  { path: '', redirectTo: 'replenishment/dashboard', pathMatch: 'full' },
  { path: 'replenishment/dashboard', component: StockStatusDashboardComponent },
  { path: 'replenishment/needs-list-wizard', component: NeedsListWizardComponent },
  { path: 'replenishment/needs-list-preview', component: NeedsListPreviewComponent },
  { path: '**', redirectTo: 'replenishment/dashboard' }
];
