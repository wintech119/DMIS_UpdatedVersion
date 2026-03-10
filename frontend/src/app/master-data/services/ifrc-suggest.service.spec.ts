import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';

import { IfrcSuggestService } from './ifrc-suggest.service';

describe('IfrcSuggestService', () => {
  let service: IfrcSuggestService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
      providers: [IfrcSuggestService],
    });

    service = TestBed.inject(IfrcSuggestService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('passes size_weight, form, and material to the IFRC suggestion endpoint', () => {
    service.suggest('water tabs', {
      size_weight: '500g',
      form: 'tablet',
      material: 'chlorine',
    }).subscribe();

    const request = httpMock.expectOne('/api/v1/masterdata/items/ifrc-suggest?name=water%20tabs&size_weight=500g&form=tablet&material=chlorine');

    expect(request.request.method).toBe('GET');
    expect(request.request.params.get('name')).toBe('water tabs');
    expect(request.request.params.get('size_weight')).toBe('500g');
    expect(request.request.params.get('form')).toBe('tablet');
    expect(request.request.params.get('material')).toBe('chlorine');

    request.flush({
      suggestion_id: '123',
      ifrc_code: 'WWTRTABLTB01',
      ifrc_description: 'Water purification tablet',
      confidence: 0.92,
      match_type: 'generated',
      construction_rationale: 'Matched by name and tablet form.',
      group_code: 'W',
      family_code: 'WTR',
      category_code: 'TABL',
      spec_segment: 'TB',
      sequence: 1,
      auto_fill_threshold: 0.85,
      resolution_status: 'resolved',
      resolution_explanation: 'Generated suggestion resolved to exactly one active governed IFRC reference.',
      ifrc_family_id: 301,
      resolved_ifrc_item_ref_id: 401,
      candidate_count: 1,
      auto_highlight_candidate_id: 401,
      direct_accept_allowed: true,
      candidates: [],
    });
  });
});
