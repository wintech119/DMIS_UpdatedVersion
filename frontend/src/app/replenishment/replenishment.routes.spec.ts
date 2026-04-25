import { appAccessGuard } from '../core/app-access.guard';
import { REPLENISHMENT_ROUTES } from './replenishment.routes';

describe('REPLENISHMENT_ROUTES', () => {
  function findRoute(path: string) {
    return REPLENISHMENT_ROUTES.find((route) => route.path === path);
  }

  it('guards the replenishment routes that map to shared nav access keys', () => {
    expect(findRoute('dashboard')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('dashboard')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.dashboard' }));

    expect(findRoute('my-submissions')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('my-submissions')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.submissions' }));

    expect(findRoute('needs-list-wizard')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('needs-list-wizard')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.wizard' }));

    expect(findRoute('needs-list/:id/wizard')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('needs-list/:id/wizard')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.wizard' }));

    expect(findRoute('needs-list-review')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('needs-list-review')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.review' }));

    expect(findRoute('needs-list/:id/review')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('needs-list/:id/review')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.review' }));

    expect(findRoute('needs-list/:id/apply-relief-request')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('needs-list/:id/apply-relief-request')?.data).toEqual(jasmine.objectContaining({ accessKey: 'operations.relief-requests.create' }));
    expect(findRoute('needs-list/:id/apply-relief-request')?.loadChildren).toEqual(jasmine.any(Function));

    expect(findRoute('needs-list/:id/transfers')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('needs-list/:id/transfers')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.execution' }));

    expect(findRoute('needs-list/:id/donations')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('needs-list/:id/donations')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.execution' }));

    expect(findRoute('needs-list/:id/procurement')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('needs-list/:id/procurement')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.procurement.view' }));

    expect(findRoute('procurement/:procId')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('procurement/:procId')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.procurement.view' }));

    expect(findRoute('procurement/:procId/edit')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('procurement/:procId/edit')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.procurement.edit' }));

    expect(findRoute('procurement/:procId/receive')?.canActivate).toEqual([appAccessGuard]);
    expect(findRoute('procurement/:procId/receive')?.data).toEqual(jasmine.objectContaining({ accessKey: 'replenishment.procurement.receive' }));
  });

  it('keeps legacy needs-list operational workspace URLs redirected to replenishment review', () => {
    for (const path of [
      'needs-list/:id/track',
      'needs-list/:id/allocation',
      'needs-list/:id/dispatch',
      'needs-list/:id/history',
      'needs-list/:id/superseded',
    ]) {
      expect(findRoute(path)).toEqual(jasmine.objectContaining({
        redirectTo: 'needs-list/:id/review',
        pathMatch: 'full',
      }));
    }
  });
});
