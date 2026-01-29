import { Routes } from '@angular/router';

import { NeedsListPreviewComponent } from './replenishment/needs-list-preview/needs-list-preview.component';

export const routes: Routes = [
  { path: '', redirectTo: 'replenishment/needs-list-preview', pathMatch: 'full' },
  { path: 'replenishment/needs-list-preview', component: NeedsListPreviewComponent },
  { path: '**', redirectTo: 'replenishment/needs-list-preview' }
];
