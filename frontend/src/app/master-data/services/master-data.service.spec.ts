import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { MasterDataService } from './master-data.service';

describe('MasterDataService', () => {
  let service: MasterDataService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        MasterDataService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });

    service = TestBed.inject(MasterDataService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('serializes item taxonomy filters for item list requests', () => {
    service.list('items', {
      status: 'A',
      search: 'water tabs',
      orderBy: '-item_name',
      limit: 25,
      offset: 50,
      categoryId: 101,
      ifrcFamilyId: 301,
      ifrcItemRefId: 401,
    }).subscribe();

    const request = httpMock.expectOne((req) => req.url === '/api/v1/masterdata/items/');
    expect(request.request.method).toBe('GET');
    expect(request.request.params.get('status')).toBe('A');
    expect(request.request.params.get('search')).toBe('water tabs');
    expect(request.request.params.get('order_by')).toBe('-item_name');
    expect(request.request.params.get('limit')).toBe('25');
    expect(request.request.params.get('offset')).toBe('50');
    expect(request.request.params.get('category_id')).toBe('101');
    expect(request.request.params.get('ifrc_family_id')).toBe('301');
    expect(request.request.params.get('ifrc_item_ref_id')).toBe('401');

    request.flush({
      results: [],
      count: 0,
      limit: 25,
      offset: 50,
      warnings: [],
    });
  });

  it('uses the dedicated category, family, and reference lookup endpoints', () => {
    service.lookupItemCategories({ includeValue: 101 }).subscribe();
    service.lookupIfrcFamilies({ categoryId: 101, search: 'WTR' }).subscribe();
    service.lookupIfrcReferences({ ifrcFamilyId: 301, search: 'tablet', limit: 20 }).subscribe();

    const categoryRequest = httpMock.expectOne('/api/v1/masterdata/items/categories/lookup?include_value=101');
    expect(categoryRequest.request.method).toBe('GET');
    categoryRequest.flush({ items: [], warnings: [] });

    const familyRequest = httpMock.expectOne('/api/v1/masterdata/items/ifrc-families/lookup?category_id=101&search=WTR');
    expect(familyRequest.request.method).toBe('GET');
    familyRequest.flush({ items: [], warnings: [] });

    const referenceRequest = httpMock.expectOne('/api/v1/masterdata/items/ifrc-references/lookup?ifrc_family_id=301&search=tablet&limit=20');
    expect(referenceRequest.request.method).toBe('GET');
    referenceRequest.flush({ items: [], warnings: [] });
  });
});
