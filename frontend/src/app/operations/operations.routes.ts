import { Routes } from '@angular/router';

import { OperationsDashboardComponent } from './operations-dashboard/operations-dashboard.component';
import { ReliefRequestListComponent } from './relief-request-list/relief-request-list.component';
import { ReliefRequestDetailComponent } from './relief-request-detail/relief-request-detail.component';
import { ReliefRequestWizardComponent } from './relief-request-wizard/relief-request-wizard.component';
import { EligibilityReviewQueueComponent } from './eligibility-review-queue/eligibility-review-queue.component';
import { EligibilityReviewDetailComponent } from './eligibility-review-detail/eligibility-review-detail.component';
import { PackageFulfillmentQueueComponent } from './package-fulfillment-queue/package-fulfillment-queue.component';
import { PackageFulfillmentWorkspaceComponent } from './package-fulfillment-workspace/package-fulfillment-workspace.component';
import { DispatchQueueComponent } from './dispatch-queue/dispatch-queue.component';
import { OpsDispatchWorkspaceComponent } from './dispatch-workspace/dispatch-workspace.component';
import { DispatchWaybillComponent } from './dispatch-waybill/dispatch-waybill.component';
import { ReceiptConfirmationComponent } from './receipt-confirmation/receipt-confirmation.component';
import { TaskCenterComponent } from './task-center/task-center.component';

export const OPERATIONS_ROUTES: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'dashboard', component: OperationsDashboardComponent },
  { path: 'tasks', component: TaskCenterComponent },
  { path: 'relief-requests', component: ReliefRequestListComponent },
  { path: 'relief-requests/new', component: ReliefRequestWizardComponent },
  { path: 'relief-requests/:reliefrqstId', component: ReliefRequestDetailComponent },
  { path: 'relief-requests/:reliefrqstId/edit', component: ReliefRequestWizardComponent },
  { path: 'eligibility-review', component: EligibilityReviewQueueComponent },
  { path: 'eligibility-review/:reliefrqstId', component: EligibilityReviewDetailComponent },
  { path: 'package-fulfillment', component: PackageFulfillmentQueueComponent },
  { path: 'package-fulfillment/:reliefrqstId', component: PackageFulfillmentWorkspaceComponent },
  { path: 'dispatch', component: DispatchQueueComponent },
  { path: 'dispatch/:reliefpkgId/waybill', component: DispatchWaybillComponent },
  { path: 'dispatch/:reliefpkgId', component: OpsDispatchWorkspaceComponent },
  { path: 'receipt-confirmation/:reliefpkgId', component: ReceiptConfirmationComponent },
];
