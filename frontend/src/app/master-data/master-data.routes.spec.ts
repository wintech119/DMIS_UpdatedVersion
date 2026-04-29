import { routes } from '../app.routes';
import { MASTER_DATA_ROUTES } from './master-data.routes';

describe('MASTER_DATA_ROUTES', () => {
  it('keeps the lazy-loaded /master-data route mounted from the app shell', () => {
    const masterDataRoute = routes.find((route) => route.path === 'master-data');

    expect(masterDataRoute).toBeDefined();
    expect(masterDataRoute?.loadChildren).toBeDefined();
  });

  it('applies the master data access guard to deep-linkable maintenance routes', () => {
    const itemCategoryRoute = MASTER_DATA_ROUTES.find((route) => route.path === 'item-categories');
    const uomRoute = MASTER_DATA_ROUTES.find((route) => route.path === 'uom');
    const homeRoute = MASTER_DATA_ROUTES.find((route) => route.path === '');

    expect(itemCategoryRoute?.canMatch?.length).toBe(1);
    expect(uomRoute?.canMatch?.length).toBe(1);
    expect(homeRoute?.canMatch).toBeUndefined();
  });

  it('keeps item master compatibility for /master-data/items and its page flow', () => {
    const routePaths = MASTER_DATA_ROUTES.map((route) => route.path);

    expect(routePaths).toContain('items');
    expect(routePaths).toContain('items/new');
    expect(routePaths).toContain('items/:pk');
    expect(routePaths).toContain('items/:pk/edit');
  });

  it('exposes Level 1, Level 2, and Level 3 catalog maintenance routes under /master-data', () => {
    const routePaths = MASTER_DATA_ROUTES.map((route) => route.path);

    expect(routePaths).toContain('item-categories');
    expect(routePaths).toContain('item-categories/new');
    expect(routePaths).toContain('item-categories/:pk');
    expect(routePaths).toContain('item-categories/:pk/edit');
    expect(routePaths).toContain('ifrc-families');
    expect(routePaths).toContain('ifrc-families/new');
    expect(routePaths).toContain('ifrc-families/:pk');
    expect(routePaths).toContain('ifrc-families/:pk/edit');
    expect(routePaths).toContain('ifrc-item-references');
    expect(routePaths).toContain('ifrc-item-references/new');
    expect(routePaths).toContain('ifrc-item-references/:pk');
    expect(routePaths).toContain('ifrc-item-references/:pk/edit');
  });

  it('keeps UOM on list-only routing while it remains a dialog-sized maintenance form', () => {
    const routePaths = MASTER_DATA_ROUTES.map((route) => route.path);

    expect(routePaths).toContain('uom');
    expect(routePaths).not.toContain('uom/new');
    expect(routePaths).not.toContain('uom/:pk');
    expect(routePaths).not.toContain('uom/:pk/edit');
  });

  it('exposes advanced system master maintenance routes under /master-data', () => {
    const routePaths = MASTER_DATA_ROUTES.map((route) => route.path);

    for (const routePath of ['users', 'roles', 'permissions', 'tenant-types', 'tenants']) {
      expect(routePaths).toContain(routePath);
      expect(routePaths).toContain(`${routePath}/new`);
      expect(routePaths).toContain(`${routePath}/:pk`);
      expect(routePaths).toContain(`${routePath}/:pk/edit`);
    }
  });
});
