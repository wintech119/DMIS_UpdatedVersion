import { Routes } from '@angular/router';

import { StockStatusDashboardComponent } from './replenishment/stock-status-dashboard/stock-status-dashboard.component';
import { NeedsListWizardComponent } from './replenishment/needs-list-wizard/needs-list-wizard.component';
import { NeedsListReviewQueueComponent } from './replenishment/needs-list-review/needs-list-review-queue.component';
import { NeedsListReviewDetailComponent } from './replenishment/needs-list-review/needs-list-review-detail.component';
import { MySubmissionsComponent } from './replenishment/my-submissions/my-submissions.component';
import { TransferDraftsComponent } from './replenishment/transfer-drafts/transfer-drafts.component';
import { DonationAllocationComponent } from './replenishment/donation-allocation/donation-allocation.component';
import { ProcurementListComponent } from './replenishment/procurement-list/procurement-list.component';
import { ProcurementDetailComponent } from './replenishment/procurement-detail/procurement-detail.component';
import { ProcurementFormComponent } from './replenishment/procurement-form/procurement-form.component';
import { ProcurementIntakeComponent } from './replenishment/procurement-intake/procurement-intake.component';

export const routes: Routes = [
  { path: '', redirectTo: 'replenishment/dashboard', pathMatch: 'full' },
  { path: 'replenishment/dashboard', component: StockStatusDashboardComponent },
  { path: 'replenishment/my-submissions', component: MySubmissionsComponent },
  { path: 'replenishment/needs-list-wizard', component: NeedsListWizardComponent },
  { path: 'replenishment/needs-list/:id/wizard', component: NeedsListWizardComponent },
  { path: 'replenishment/needs-list-review', component: NeedsListReviewQueueComponent },
  { path: 'replenishment/needs-list-review/:id', redirectTo: 'replenishment/needs-list/:id/review', pathMatch: 'full' },
  { path: 'replenishment/needs-list/:id/review', component: NeedsListReviewDetailComponent },
  { path: 'replenishment/needs-list/:id/track', redirectTo: 'replenishment/needs-list/:id/review', pathMatch: 'full' },
  { path: 'replenishment/needs-list/:id/allocation', redirectTo: 'replenishment/needs-list/:id/review', pathMatch: 'full' },
  { path: 'replenishment/needs-list/:id/dispatch', redirectTo: 'replenishment/needs-list/:id/review', pathMatch: 'full' },
  { path: 'replenishment/needs-list/:id/history', redirectTo: 'replenishment/needs-list/:id/review', pathMatch: 'full' },
  { path: 'replenishment/needs-list/:id/superseded', redirectTo: 'replenishment/needs-list/:id/review', pathMatch: 'full' },
  { path: 'replenishment/needs-list/:id/transfers', component: TransferDraftsComponent },
  { path: 'replenishment/needs-list/:id/donations', component: DonationAllocationComponent },
  { path: 'replenishment/needs-list/:id/procurement', component: ProcurementListComponent },
  { path: 'replenishment/procurement/new', redirectTo: 'replenishment/needs-list-review', pathMatch: 'full' },
  { path: 'replenishment/procurement/:procId', component: ProcurementDetailComponent },
  { path: 'replenishment/procurement/:procId/edit', component: ProcurementFormComponent },
  { path: 'replenishment/procurement/:procId/receive', component: ProcurementIntakeComponent },
  {
    path: 'master-data',
    loadChildren: () => import('./master-data/master-data.routes').then(m => m.MASTER_DATA_ROUTES),
  },
  {
    path: 'operations',
    loadChildren: () => import('./operations/operations.routes').then(m => m.OPERATIONS_ROUTES),
  },
  { path: '**', redirectTo: 'replenishment/dashboard' }
];
