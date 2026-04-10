import { Routes } from '@angular/router';

import { StockStatusDashboardComponent } from './stock-status-dashboard/stock-status-dashboard.component';
import { NeedsListWizardComponent } from './needs-list-wizard/needs-list-wizard.component';
import { NeedsListReviewQueueComponent } from './needs-list-review/needs-list-review-queue.component';
import { NeedsListReviewDetailComponent } from './needs-list-review/needs-list-review-detail.component';
import { MySubmissionsComponent } from './my-submissions/my-submissions.component';
import { TransferDraftsComponent } from './transfer-drafts/transfer-drafts.component';
import { DonationAllocationComponent } from './donation-allocation/donation-allocation.component';
import { ProcurementListComponent } from './procurement-list/procurement-list.component';
import { ProcurementDetailComponent } from './procurement-detail/procurement-detail.component';
import { ProcurementFormComponent } from './procurement-form/procurement-form.component';
import { ProcurementIntakeComponent } from './procurement-intake/procurement-intake.component';
import { appAccessGuard } from '../core/app-access.guard';

export const REPLENISHMENT_ROUTES: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'dashboard', component: StockStatusDashboardComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.dashboard' } },
  { path: 'my-submissions', component: MySubmissionsComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.submissions' } },
  { path: 'needs-list-wizard', component: NeedsListWizardComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.wizard' } },
  { path: 'needs-list/:id/wizard', component: NeedsListWizardComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.wizard' } },
  { path: 'needs-list-review', component: NeedsListReviewQueueComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.review' } },
  { path: 'needs-list-review/:id', redirectTo: 'needs-list/:id/review', pathMatch: 'full' },
  { path: 'needs-list/:id/review', component: NeedsListReviewDetailComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.review' } },
  { path: 'needs-list/:id/track', redirectTo: 'needs-list/:id/review', pathMatch: 'full' },
  { path: 'needs-list/:id/allocation', redirectTo: 'needs-list/:id/review', pathMatch: 'full' },
  { path: 'needs-list/:id/dispatch', redirectTo: 'needs-list/:id/review', pathMatch: 'full' },
  { path: 'needs-list/:id/history', redirectTo: 'needs-list/:id/review', pathMatch: 'full' },
  { path: 'needs-list/:id/superseded', redirectTo: 'needs-list/:id/review', pathMatch: 'full' },
  { path: 'needs-list/:id/transfers', component: TransferDraftsComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.execution' } },
  { path: 'needs-list/:id/donations', component: DonationAllocationComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.execution' } },
  { path: 'needs-list/:id/procurement', component: ProcurementListComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.procurement.view' } },
  { path: 'procurement/new', redirectTo: 'needs-list-review', pathMatch: 'full' },
  { path: 'procurement/:procId', component: ProcurementDetailComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.procurement.view' } },
  { path: 'procurement/:procId/edit', component: ProcurementFormComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.procurement.edit' } },
  { path: 'procurement/:procId/receive', component: ProcurementIntakeComponent, canActivate: [appAccessGuard], data: { accessKey: 'replenishment.procurement.receive' } },
];
