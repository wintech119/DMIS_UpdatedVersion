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
import { OpsStockAvailabilityPreviewComponent } from './shared/ops-stock-availability-preview.component';
import { ConsolidationQueueComponent } from './consolidation-queue/consolidation-queue.component';
import { ConsolidationPackageComponent } from './consolidation/consolidation-package.component';
import { ConsolidationLegWorkspaceComponent } from './consolidation/consolidation-leg-workspace.component';
import { PickupReleaseComponent } from './consolidation/pickup-release.component';
import { appAccessGuard } from '../core/app-access.guard';

export const OPERATIONS_ROUTES: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'dashboard', component: OperationsDashboardComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.dashboard' } },
  { path: 'tasks', component: TaskCenterComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.tasks' } },
  { path: 'relief-requests', component: ReliefRequestListComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.relief-requests' } },
  { path: 'relief-requests/new', component: ReliefRequestWizardComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.relief-requests.create' } },
  { path: 'relief-requests/:reliefrqstId', component: ReliefRequestDetailComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.relief-requests' } },
  { path: 'relief-requests/:reliefrqstId/edit', component: ReliefRequestWizardComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.relief-requests.edit' } },
  { path: 'eligibility-review', component: EligibilityReviewQueueComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.eligibility' } },
  { path: 'eligibility-review/:reliefrqstId', component: EligibilityReviewDetailComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.eligibility' } },
  { path: 'package-fulfillment', component: PackageFulfillmentQueueComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.fulfillment' } },
  { path: 'package-fulfillment/:reliefrqstId', component: PackageFulfillmentWorkspaceComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.fulfillment' } },
  { path: 'consolidation', component: ConsolidationQueueComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.fulfillment' } },
  { path: 'consolidation/:reliefpkgId', component: ConsolidationPackageComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.fulfillment' } },
  { path: 'consolidation/:reliefpkgId/leg/:legId', component: ConsolidationLegWorkspaceComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.fulfillment' } },
  { path: 'pickup-release/:reliefpkgId', component: PickupReleaseComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.dispatch' } },
  { path: 'dev/stock-availability-preview', component: OpsStockAvailabilityPreviewComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.fulfillment' } },
  { path: 'dispatch', component: DispatchQueueComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.dispatch' } },
  { path: 'dispatch/:reliefpkgId/waybill', component: DispatchWaybillComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.dispatch' } },
  { path: 'dispatch/:reliefpkgId', component: OpsDispatchWorkspaceComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.dispatch' } },
  { path: 'receipt-confirmation/:reliefpkgId', component: ReceiptConfirmationComponent, canActivate: [appAccessGuard], data: { accessKey: 'operations.dispatch' } },
];
