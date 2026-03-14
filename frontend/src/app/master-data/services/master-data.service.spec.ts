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
    service.lookupIfrcFamilies({ categoryId: 101, search: 'WTR', includeValue: 301 }).subscribe();
    service.lookupIfrcReferences({ ifrcFamilyId: 301, search: 'tablet', includeValue: 401, limit: 20 }).subscribe();

    const categoryRequest = httpMock.expectOne('/api/v1/masterdata/items/categories/lookup?include_value=101');
    expect(categoryRequest.request.method).toBe('GET');
    categoryRequest.flush({ items: [], warnings: [] });

    const familyRequest = httpMock.expectOne('/api/v1/masterdata/items/ifrc-families/lookup?category_id=101&include_value=301&search=WTR');
    expect(familyRequest.request.method).toBe('GET');
    familyRequest.flush({ items: [], warnings: [] });

    const referenceRequest = httpMock.expectOne('/api/v1/masterdata/items/ifrc-references/lookup?ifrc_family_id=301&include_value=401&search=tablet&limit=20');
    expect(referenceRequest.request.method).toBe('GET');
    referenceRequest.flush({ items: [], warnings: [] });
  });

  it('posts to the governed IFRC authoring-assist endpoints', () => {
    service.suggestIfrcFamilyValues({ family_label: 'Water Treatment' }).subscribe();
    service.suggestIfrcReferenceValues({ ifrc_family_id: 11, reference_desc: 'Water purification tablet' }).subscribe();

    const familySuggestRequest = httpMock.expectOne('/api/v1/masterdata/ifrc-families/suggest');
    expect(familySuggestRequest.request.method).toBe('POST');
    expect(familySuggestRequest.request.body).toEqual({ family_label: 'Water Treatment' });
    familySuggestRequest.flush({ source: 'deterministic', normalized: {}, warnings: [] });

    const referenceSuggestRequest = httpMock.expectOne('/api/v1/masterdata/ifrc-item-references/suggest');
    expect(referenceSuggestRequest.request.method).toBe('POST');
    expect(referenceSuggestRequest.request.body).toEqual({ ifrc_family_id: 11, reference_desc: 'Water purification tablet' });
    referenceSuggestRequest.flush({ source: 'deterministic', normalized: {}, warnings: [] });
  });

  it('posts governed replacement payloads to the replacement endpoint', () => {
    service.createCatalogReplacement('ifrc_item_references', 77, { ifrc_code: 'WWTRTABLTB02' }, true).subscribe();

    const request = httpMock.expectOne('/api/v1/masterdata/ifrc-item-references/77/replacement');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({
      ifrc_code: 'WWTRTABLTB02',
      retire_original: true,
    });
    request.flush({
      record: { ifrc_item_ref_id: 91 },
      replacement_for_pk: 77,
      warnings: [],
    });
  });
});
