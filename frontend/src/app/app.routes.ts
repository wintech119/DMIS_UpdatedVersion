import { Routes } from '@angular/router';

import { StockStatusDashboardComponent } from './replenishment/stock-status-dashboard/stock-status-dashboard.component';
import { NeedsListWizardComponent } from './replenishment/needs-list-wizard/needs-list-wizard.component';
import { NeedsListReviewQueueComponent } from './replenishment/needs-list-review/needs-list-review-queue.component';
import { NeedsListReviewDetailComponent } from './replenishment/needs-list-review/needs-list-review-detail.component';
import { MySubmissionsComponent } from './replenishment/my-submissions/my-submissions.component';
import { NeedsListFulfillmentTrackerComponent } from './replenishment/needs-list-fulfillment-tracker/needs-list-fulfillment-tracker.component';

export const routes: Routes = [
  { path: '', redirectTo: 'replenishment/dashboard', pathMatch: 'full' },
  { path: 'replenishment/dashboard', component: StockStatusDashboardComponent },
  { path: 'replenishment/my-submissions', component: MySubmissionsComponent },
  { path: 'replenishment/needs-list-wizard', component: NeedsListWizardComponent },
  { path: 'replenishment/needs-list/:id/wizard', component: NeedsListWizardComponent },
  { path: 'replenishment/needs-list-review', component: NeedsListReviewQueueComponent },
  { path: 'replenishment/needs-list-review/:id', component: NeedsListReviewDetailComponent },
  { path: 'replenishment/needs-list/:id/review', component: NeedsListReviewDetailComponent },
  { path: 'replenishment/needs-list/:id/track', component: NeedsListFulfillmentTrackerComponent },
  { path: 'replenishment/needs-list/:id/history', component: NeedsListFulfillmentTrackerComponent },
  { path: 'replenishment/needs-list/:id/superseded', component: NeedsListFulfillmentTrackerComponent },
  { path: '**', redirectTo: 'replenishment/dashboard' }
];
