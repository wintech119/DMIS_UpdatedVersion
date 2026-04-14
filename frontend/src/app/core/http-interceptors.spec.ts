import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { HttpClient } from '@angular/common/http';

import { AuthSessionService } from './auth-session.service';
import { DMIS_HTTP_INTERCEPTORS } from './http-interceptors';

describe('DMIS_HTTP_INTERCEPTORS', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authSession: {
    getAccessToken: jasmine.Spy;
    handleApiAuthFailure: jasmine.Spy;
  };

  beforeEach(() => {
    (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'] = false;

    authSession = {
      getAccessToken: jasmine.createSpy('getAccessToken').and.returnValue('bearer-token'),
      handleApiAuthFailure: jasmine.createSpy('handleApiAuthFailure'),
    };

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors(DMIS_HTTP_INTERCEPTORS)),
        provideHttpClientTesting(),
        { provide: AuthSessionService, useValue: authSession },
      ],
    });

    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
    delete (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'];
  });

  it('injects a bearer token for DMIS API requests when a token is available', () => {
    http.get('/api/v1/replenishment/needs-lists/').subscribe();

    const request = httpMock.expectOne('/api/v1/replenishment/needs-lists/');
    expect(request.request.headers.get('Authorization')).toBe('Bearer bearer-token');
    request.flush({});
  });

  it('does not inject bearer tokens for local harness requests or non-DMIS endpoints', () => {
    http.get('/api/v1/auth/local-harness/').subscribe();
    http.post('https://issuer.example.com/token', {}).subscribe();

    const harnessRequest = httpMock.expectOne('/api/v1/auth/local-harness/');
    expect(harnessRequest.request.headers.has('Authorization')).toBeFalse();
    harnessRequest.flush({});

    const tokenRequest = httpMock.expectOne('https://issuer.example.com/token');
    expect(tokenRequest.request.headers.has('Authorization')).toBeFalse();
    tokenRequest.flush({});
  });

  it('classifies DMIS API 401 responses as auth failures', () => {
    http.get('/api/v1/operations/requests/').subscribe({
      error: () => undefined,
    });

    const request = httpMock.expectOne('/api/v1/operations/requests/');
    request.flush({ detail: 'Unauthorized' }, { status: 401, statusText: 'Unauthorized' });

    expect(authSession.handleApiAuthFailure).toHaveBeenCalledWith('expired_or_invalid_token');
  });

  it('does not treat DMIS API 403 responses as expired-token failures', () => {
    http.get('/api/v1/operations/requests/').subscribe({
      error: () => undefined,
    });

    const request = httpMock.expectOne('/api/v1/operations/requests/');
    request.flush({ detail: 'Forbidden' }, { status: 403, statusText: 'Forbidden' });

    expect(authSession.handleApiAuthFailure).not.toHaveBeenCalled();
  });

  it('injects the local harness user only for relative or same-origin request targets', () => {
    (globalThis as typeof globalThis & Record<string, unknown>)['__DMIS_LOCAL_AUTH_HARNESS_BUILD__'] = true;
    localStorage.setItem('dmis_local_harness_user', 'local_odpem_logistics_manager_tst');

    http.get('/api/v1/operations/requests/').subscribe();
    http.get(`${window.location.origin}/api/v1/operations/requests/`).subscribe();
    http.get('http://127.0.0.1:8001/api/v1/operations/requests/').subscribe();
    http.get('https://api.example.org/api/v1/operations/requests/').subscribe();

    const localRequest = httpMock.expectOne('/api/v1/operations/requests/');
    expect(localRequest.request.headers.get('X-DMIS-Local-User')).toBe('local_odpem_logistics_manager_tst');
    localRequest.flush({});

    const sameOriginRequest = httpMock.expectOne(`${window.location.origin}/api/v1/operations/requests/`);
    expect(sameOriginRequest.request.headers.get('X-DMIS-Local-User')).toBe('local_odpem_logistics_manager_tst');
    sameOriginRequest.flush({});

    const differentOriginLocalRequest = httpMock.expectOne('http://127.0.0.1:8001/api/v1/operations/requests/');
    expect(differentOriginLocalRequest.request.headers.has('X-DMIS-Local-User')).toBeFalse();
    differentOriginLocalRequest.flush({});

    const remoteRequest = httpMock.expectOne('https://api.example.org/api/v1/operations/requests/');
    expect(remoteRequest.request.headers.has('X-DMIS-Local-User')).toBeFalse();
    remoteRequest.flush({});
  });
});
