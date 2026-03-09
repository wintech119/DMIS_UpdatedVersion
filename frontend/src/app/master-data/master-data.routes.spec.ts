import { routes } from '../app.routes';
import { MASTER_DATA_ROUTES } from './master-data.routes';

describe('MASTER_DATA_ROUTES', () => {
  it('keeps the lazy-loaded /master-data route mounted from the app shell', () => {
    const masterDataRoute = routes.find((route) => route.path === 'master-data');

    expect(masterDataRoute).toBeDefined();
    expect(masterDataRoute?.loadChildren).toBeDefined();
  });

  it('keeps item master compatibility for /master-data/items and its page flow', () => {
    const routePaths = MASTER_DATA_ROUTES.map((route) => route.path);

    expect(routePaths).toContain('items');
    expect(routePaths).toContain('items/new');
    expect(routePaths).toContain('items/:pk');
    expect(routePaths).toContain('items/:pk/edit');
  });
});
