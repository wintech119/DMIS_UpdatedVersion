import { appAccessGuard } from '../core/app-access.guard';
import { REPLENISHMENT_ROUTES } from './replenishment.routes';

describe('REPLENISHMENT_ROUTES', () => {
  function findRoute(path: string) {
    return REPLENISHMENT_ROUTES.find((route) => route.path === path);
  }

  it('guards replenishment routes that map to shared nav access keys', () => {
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
  });
});
