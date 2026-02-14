import { Routes } from '@angular/router';

import { StockStatusDashboardComponent } from './replenishment/stock-status-dashboard/stock-status-dashboard.component';
import { NeedsListWizardComponent } from './replenishment/needs-list-wizard/needs-list-wizard.component';
import { NeedsListReviewQueueComponent } from './replenishment/needs-list-review/needs-list-review-queue.component';
import { NeedsListReviewDetailComponent } from './replenishment/needs-list-review/needs-list-review-detail.component';

export const routes: Routes = [
  { path: '', redirectTo: 'replenishment/dashboard', pathMatch: 'full' },
  { path: 'replenishment/dashboard', component: StockStatusDashboardComponent },
  { path: 'replenishment/needs-list-wizard', component: NeedsListWizardComponent },
  { path: 'replenishment/needs-list-review', component: NeedsListReviewQueueComponent },
  { path: 'replenishment/needs-list-review/:id', component: NeedsListReviewDetailComponent },
  { path: '**', redirectTo: 'replenishment/dashboard' }
];
