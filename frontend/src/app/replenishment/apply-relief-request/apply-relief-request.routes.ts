import { Routes } from '@angular/router';

import { appAccessGuard } from '../../core/app-access.guard';
import { ApplyReliefRequestComponent } from './apply-relief-request.component';

export const APPLY_RELIEF_REQUEST_ROUTES: Routes = [
  {
    path: '',
    component: ApplyReliefRequestComponent,
    canActivate: [appAccessGuard],
    data: { accessKey: 'operations.relief-requests.create' },
  },
];
