import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';

import { AuthSessionService } from './auth-session.service';

describe('AuthSessionService', () => {
  let service: AuthSessionService;
  let httpMock: HttpTestingController;
  let router: Router;

  const oidcConfig = {
    enabled: true,
    issuer: 'https://issuer.example.com/realms/dmis',
    clientId: 'dmis-web',
    scope: 'openid profile email',
    redirectPath: '/auth/callback',
    postLogoutRedirectPath: '/auth/login',
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        AuthSessionService,
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });

    service = TestBed.inject(AuthSessionService);
    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    spyOn(router, 'navigateByUrl').and.resolveTo(true);
    sessionStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  afterEach(() => {
    httpMock.verify();
    sessionStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  it('marks the session unauthenticated when OIDC is enabled but no token is active', async () => {
    const init = service.initializeApp();

    expectConfigRequest().flush(oidcConfig);
    await init;

    expect(service.state().status).toBe('unauthenticated');
    expect(service.state().message).toContain('Sign in');
    expect(httpMock.match('/api/v1/auth/whoami/').length).toBe(0);
  });

  it('marks expired stored tokens explicitly and clears session storage', async () => {
    seedStoredSession({ expiresAt: Date.now() - 5_000 });

    const init = service.initializeApp();

    expectConfigRequest().flush(oidcConfig);
    await init;

    expect(service.state().status).toBe('expired_or_invalid_token');
    expect(readStoredSession()).toBeNull();
  });

  it('classifies backend 401 whoami failures as expired_or_invalid_token', async () => {
    seedStoredSession();

    const init = service.initializeApp();

    expectConfigRequest().flush(oidcConfig);
    expectWhoamiRequest().flush(
      { detail: 'Unauthorized' },
      { status: 401, statusText: 'Unauthorized' },
    );
    await init;

    expect(service.state().status).toBe('expired_or_invalid_token');
    expect(readStoredSession()).toBeNull();
  });

  it('classifies non-401 whoami failures as backend auth failures without pretending the user is loaded', async () => {
    seedStoredSession();

    const init = service.initializeApp();

    expectConfigRequest().flush(oidcConfig);
    expectWhoamiRequest().flush(
      { detail: 'Backend unavailable' },
      { status: 503, statusText: 'Service Unavailable' },
    );
    await init;

    expect(service.state().status).toBe('backend_auth_failure');
    expect(service.principal()).toBeNull();
    expect(readStoredSession()).not.toBeNull();
  });

  it('completes the callback flow, stores the token in sessionStorage, and restores the return route', async () => {
    seedPendingLogin({
      state: 'pending-state',
      codeVerifier: 'verifier-123',
      returnUrl: '/operations/dashboard',
    });
    window.history.replaceState({}, '', '/auth/callback?code=auth-code&state=pending-state');

    const init = service.initializeApp();

    expectConfigRequest().flush(oidcConfig);
    expectDiscoveryRequest().flush({
      authorization_endpoint: 'https://issuer.example.com/authorize',
      token_endpoint: 'https://issuer.example.com/token',
      end_session_endpoint: 'https://issuer.example.com/logout',
    });
    const tokenRequest = httpMock.expectOne('https://issuer.example.com/token');
    expect(tokenRequest.request.method).toBe('POST');
    expect(tokenRequest.request.body).toContain('grant_type=authorization_code');
    expect(tokenRequest.request.body).toContain('code=auth-code');
    tokenRequest.flush({
      access_token: 'access-token-123',
      id_token: 'id-token-123',
      token_type: 'Bearer',
      expires_in: 3600,
      scope: 'openid profile email',
    });
    expectWhoamiRequest().flush({
      user_id: 'EMP-123',
      username: 'ops.user',
      roles: ['SYSTEM_ADMINISTRATOR'],
      permissions: ['masterdata.view'],
    });
    await init;

    expect(service.state().status).toBe('authenticated');
    expect(service.principal()?.username).toBe('ops.user');
    expect(readStoredSession()).toEqual(jasmine.objectContaining({
      accessToken: 'access-token-123',
      idToken: 'id-token-123',
      tokenType: 'Bearer',
      scope: 'openid profile email',
    }));
    expect(sessionStorage.getItem('dmis_oidc_pending_login')).toBeNull();
    expect(router.navigateByUrl).toHaveBeenCalledWith('/operations/dashboard', { replaceUrl: true });
  });

  it('clears session storage and resets state during logout when no end-session endpoint is available', async () => {
    seedStoredSession();

    const logout = service.logout();

    expectConfigRequest().flush({ ...oidcConfig, enabled: false });
    await logout;

    expect(readStoredSession()).toBeNull();
    expect(service.state().status).toBe('unauthenticated');
    expect(router.navigate).toHaveBeenCalledWith(['/auth/login'], {
      queryParams: { reason: 'unauthenticated' },
      replaceUrl: true,
    });
  });

  function expectConfigRequest() {
    return httpMock.expectOne('auth-config.json');
  }

  function expectDiscoveryRequest() {
    return httpMock.expectOne('https://issuer.example.com/realms/dmis/.well-known/openid-configuration');
  }

  function expectWhoamiRequest() {
    const request = httpMock.expectOne('/api/v1/auth/whoami/');
    expect(request.request.method).toBe('GET');
    return request;
  }

  function seedStoredSession(overrides: Partial<StoredOidcSession> = {}) {
    const session: StoredOidcSession = {
      accessToken: 'access-token',
      idToken: 'id-token',
      tokenType: 'Bearer',
      expiresAt: Date.now() + 60_000,
      scope: 'openid profile email',
      ...overrides,
    };
    sessionStorage.setItem('dmis_oidc_session', JSON.stringify(session));
  }

  function seedPendingLogin(overrides: PendingLoginState) {
    sessionStorage.setItem('dmis_oidc_pending_login', JSON.stringify(overrides));
  }

  function readStoredSession(): StoredOidcSession | null {
    const raw = sessionStorage.getItem('dmis_oidc_session');
    return raw ? JSON.parse(raw) as StoredOidcSession : null;
  }
});

interface StoredOidcSession {
  accessToken: string;
  idToken: string | null;
  tokenType: string;
  expiresAt: number;
  scope: string | null;
}

interface PendingLoginState {
  state: string;
  codeVerifier: string;
  returnUrl: string;
}
