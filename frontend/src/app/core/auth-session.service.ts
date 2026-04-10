import { DOCUMENT } from '@angular/common';
import {
  HttpClient,
  HttpContext,
  HttpContextToken,
  HttpErrorResponse,
  HttpHeaders,
} from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, firstValueFrom, from } from 'rxjs';

import type {
  OperationsCapabilities,
  TenantContextSummary,
} from '../replenishment/services/auth-rbac.service';

export interface AuthRuntimeConfig {
  enabled: boolean;
  issuer: string;
  clientId: string;
  scope: string;
  redirectPath: string;
  postLogoutRedirectPath: string;
  audience?: string | null;
}

export type AuthSessionStatus =
  | 'bootstrapping'
  | 'authenticated'
  | 'unauthenticated'
  | 'expired_or_invalid_token'
  | 'backend_auth_failure';

export interface AuthSessionState {
  status: AuthSessionStatus;
  message: string | null;
  configured: boolean;
  oidcEnabled: boolean;
}

export interface AuthPrincipal {
  user_id: string | null;
  username: string | null;
  roles: string[];
  permissions: string[];
  tenant_context: TenantContextSummary | null;
  operations_capabilities: OperationsCapabilities | null;
}

interface PendingLoginState {
  state: string;
  codeVerifier: string;
  returnUrl: string;
}

interface StoredOidcSession {
  accessToken: string;
  idToken: string | null;
  tokenType: string;
  expiresAt: number;
  scope: string | null;
}

interface OidcDiscoveryDocument {
  issuer?: string;
  authorization_endpoint?: string;
  token_endpoint?: string;
  end_session_endpoint?: string;
}

interface OidcTokenResponse {
  access_token?: string;
  id_token?: string;
  token_type?: string;
  expires_in?: number;
  scope?: string;
}

interface WhoAmIResponse {
  user_id?: string | null;
  username?: string | null;
  roles?: string[];
  permissions?: string[];
  tenant_context?: Partial<TenantContextSummary> | null;
  operations_capabilities?: Partial<OperationsCapabilities> | null;
}

const AUTH_CONFIG_URL = 'auth-config.json';
const OIDC_SESSION_STORAGE_KEY = 'dmis_oidc_session';
const OIDC_PENDING_LOGIN_STORAGE_KEY = 'dmis_oidc_pending_login';
const OIDC_EXPIRY_SKEW_MS = 30_000;
const DEFAULT_AUTH_RETURN_URL = '/replenishment/dashboard';

export const AUTH_INTERCEPTOR_BYPASS = new HttpContextToken<boolean>(() => false);
export const AUTH_HANDLED_BY_CALLER = new HttpContextToken<boolean>(() => false);

export function authInterceptorBypassContext(context = new HttpContext()): HttpContext {
  return context.set(AUTH_INTERCEPTOR_BYPASS, true);
}

export function authHandledByCallerContext(context = new HttpContext()): HttpContext {
  return context.set(AUTH_HANDLED_BY_CALLER, true);
}

export function isExpiredOrInvalidTokenResponse(error: unknown): error is HttpErrorResponse {
  return error instanceof HttpErrorResponse && error.status === 401;
}

export function isInsufficientPermissionsResponse(error: unknown): error is HttpErrorResponse {
  return error instanceof HttpErrorResponse && error.status === 403;
}

export function isAuthSensitiveApiResponse(error: unknown): error is HttpErrorResponse {
  return isExpiredOrInvalidTokenResponse(error) || isInsufficientPermissionsResponse(error);
}

@Injectable({
  providedIn: 'root',
})
export class AuthSessionService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly document = inject(DOCUMENT);

  private readonly runtimeConfig = signal<AuthRuntimeConfig | null>(null);
  private readonly discoveryDocument = signal<OidcDiscoveryDocument | null>(null);
  private readonly principalData = signal<AuthPrincipal | null>(null);
  private readonly sessionStateData = signal<AuthSessionState>({
    status: 'bootstrapping',
    message: null,
    configured: false,
    oidcEnabled: false,
  });

  private pendingInitialization?: Promise<void>;

  readonly state = computed(() => this.sessionStateData());
  readonly principal = computed(() => this.principalData());
  readonly config = computed(() => this.runtimeConfig());
  readonly discovery = computed(() => this.discoveryDocument());
  readonly authenticated = computed(() => this.state().status === 'authenticated');
  readonly principalLoaded = computed(() => this.authenticated());
  readonly oidcEnabled = computed(() => Boolean(this.config()?.enabled));
  readonly bootstrapping = computed(() => this.state().status === 'bootstrapping');
  readonly loginAvailable = computed(() => {
    const config = this.config();
    return Boolean(config?.enabled && isCompleteOidcConfig(config));
  });
  readonly logoutAvailable = computed(() => this.authenticated() && this.loginAvailable());

  initializeApp(force = false): Promise<void> {
    if (force || !this.pendingInitialization) {
      this.pendingInitialization = this.bootstrapSession().finally(() => {
        this.pendingInitialization = undefined;
      });
    }
    return this.pendingInitialization;
  }

  ensureInitialized(force = false): Observable<void> {
    return from(this.initializeApp(force));
  }

  refreshPrincipal(): Observable<void> {
    return from(this.refreshPrincipalAsync());
  }

  getAccessToken(): string | null {
    return this.readStoredSession()?.accessToken ?? null;
  }

  async startLogin(returnUrl?: string): Promise<void> {
    await this.ensureDiscoveryLoaded();

    const config = this.runtimeConfig();
    const discovery = this.discoveryDocument();
    if (!config?.enabled || !isCompleteOidcConfig(config) || !discovery?.authorization_endpoint) {
      this.setSessionState('unauthenticated', 'OIDC login is not configured for this deployment.');
      return;
    }

    const resolvedReturnUrl = normalizeReturnUrl(returnUrl ?? this.readBrowserUrl());
    const codeVerifier = generateRandomBase64Url(64);
    const loginState = generateRandomBase64Url(32);
    const codeChallenge = await createPkceCodeChallenge(codeVerifier);

    this.writePendingLogin({
      state: loginState,
      codeVerifier,
      returnUrl: resolvedReturnUrl,
    });

    const authorizationUrl = new URL(discovery.authorization_endpoint);
    authorizationUrl.searchParams.set('response_type', 'code');
    authorizationUrl.searchParams.set('client_id', config.clientId);
    authorizationUrl.searchParams.set('redirect_uri', resolveAbsoluteUrl(config.redirectPath, this.document.baseURI));
    authorizationUrl.searchParams.set('scope', config.scope);
    authorizationUrl.searchParams.set('state', loginState);
    authorizationUrl.searchParams.set('code_challenge', codeChallenge);
    authorizationUrl.searchParams.set('code_challenge_method', 'S256');
    if (config.audience) {
      authorizationUrl.searchParams.set('audience', config.audience);
    }

    this.document.defaultView?.location.assign(authorizationUrl.toString());
  }

  async logout(): Promise<void> {
    await this.ensureDiscoveryLoaded();

    const config = this.runtimeConfig();
    const discovery = this.discoveryDocument();
    const storedSession = this.readStoredSession();
    const postLogoutRedirect = resolveAbsoluteUrl(
      config?.postLogoutRedirectPath || '/auth/login',
      this.document.baseURI,
    );

    this.clearStoredSession();
    this.clearPendingLogin();
    this.principalData.set(null);
    this.setSessionState('unauthenticated', 'You have been signed out.');

    if (config?.enabled && discovery?.end_session_endpoint) {
      const logoutUrl = new URL(discovery.end_session_endpoint);
      logoutUrl.searchParams.set('client_id', config.clientId);
      logoutUrl.searchParams.set('post_logout_redirect_uri', postLogoutRedirect);
      if (storedSession?.idToken) {
        logoutUrl.searchParams.set('id_token_hint', storedSession.idToken);
      }
      this.document.defaultView?.location.assign(logoutUrl.toString());
      return;
    }

    void this.router.navigate(['/auth/login'], {
      queryParams: { reason: 'unauthenticated' },
      replaceUrl: true,
    });
  }

  handleApiAuthFailure(
    status: Extract<AuthSessionStatus, 'expired_or_invalid_token' | 'backend_auth_failure'>,
    message?: string,
  ): void {
    if (status === 'expired_or_invalid_token') {
      this.clearStoredSession();
    }
    this.principalData.set(null);
    this.setSessionState(status, message ?? defaultStatusMessage(status));

    const currentUrl = normalizeReturnUrl(this.readBrowserUrl());
    if (isAuthOnlyUrl(currentUrl)) {
      return;
    }

    void this.router.navigate(['/auth/login'], {
      queryParams: {
        reason: status,
        returnUrl: currentUrl,
      },
      replaceUrl: true,
    });
  }

  private async bootstrapSession(): Promise<void> {
    this.setSessionState('bootstrapping', null);

    const config = await this.loadRuntimeConfig();
    if (!config) {
      await this.bootstrapWithoutOidc();
      return;
    }

    if (isAuthCallbackUrl(this.readBrowserUrl())) {
      await this.handleCallbackFromCurrentUrl(config);
      return;
    }

    if (!config.enabled) {
      await this.bootstrapWithoutOidc();
      return;
    }

    const storedSession = this.readStoredSession();
    if (!storedSession) {
      this.principalData.set(null);
      this.setSessionState('unauthenticated', 'Sign in to continue.');
      return;
    }

    if (isStoredSessionExpired(storedSession)) {
      this.clearStoredSession();
      this.principalData.set(null);
      this.setSessionState('expired_or_invalid_token', defaultStatusMessage('expired_or_invalid_token'));
      return;
    }

    try {
      await this.bootstrapPrincipal();
    } catch {
      // bootstrapPrincipal already set an explicit auth state for guard/UI consumers.
    }
  }

  private async refreshPrincipalAsync(): Promise<void> {
    if (!this.runtimeConfig()) {
      await this.loadRuntimeConfig();
    }
    if (this.runtimeConfig()?.enabled) {
      const storedSession = this.readStoredSession();
      if (!storedSession || isStoredSessionExpired(storedSession)) {
        this.clearStoredSession();
        this.principalData.set(null);
        this.setSessionState('expired_or_invalid_token', defaultStatusMessage('expired_or_invalid_token'));
        return;
      }
    }

    try {
      await this.bootstrapPrincipal();
    } catch {
      // refresh consumers read the resulting explicit auth state instead of relying on thrown errors.
    }
  }

  private async bootstrapWithoutOidc(): Promise<void> {
    try {
      await this.bootstrapPrincipal();
    } catch {
      if (this.runtimeConfig()?.enabled) {
        this.setSessionState('unauthenticated', 'Sign in to continue.');
        return;
      }
      this.principalData.set(null);
      this.setSessionState('unauthenticated', 'OIDC login is not configured for this deployment.');
    }
  }

  private async bootstrapPrincipal(): Promise<void> {
    try {
      const data = await firstValueFrom(
        this.http.get<WhoAmIResponse>('/api/v1/auth/whoami/', {
          context: authHandledByCallerContext(),
        }),
      );
      const principal = normalizePrincipal(data);
      if (!principal) {
        this.principalData.set(null);
        this.setSessionState('backend_auth_failure', defaultStatusMessage('backend_auth_failure'));
        return;
      }

      this.principalData.set(principal);
      this.setSessionState('authenticated', null);
    } catch (error) {
      this.principalData.set(null);
      if (isExpiredOrInvalidTokenResponse(error)) {
        this.clearStoredSession();
        this.setSessionState('expired_or_invalid_token', defaultStatusMessage('expired_or_invalid_token'));
        throw error;
      }

      this.setSessionState('backend_auth_failure', defaultStatusMessage('backend_auth_failure'));
      throw error;
    }
  }

  private async loadRuntimeConfig(): Promise<AuthRuntimeConfig | null> {
    if (this.runtimeConfig()) {
      return this.runtimeConfig();
    }

    try {
      const config = await firstValueFrom(
        this.http.get<Partial<AuthRuntimeConfig>>(AUTH_CONFIG_URL, {
          context: authInterceptorBypassContext(),
        }),
      );
      const normalized = normalizeRuntimeConfig(config);
      this.runtimeConfig.set(normalized);
      this.sessionStateData.update((state) => ({
        ...state,
        configured: Boolean(normalized),
        oidcEnabled: Boolean(normalized?.enabled),
      }));
      return normalized;
    } catch {
      this.runtimeConfig.set(null);
      this.sessionStateData.update((state) => ({
        ...state,
        configured: false,
        oidcEnabled: false,
      }));
      return null;
    }
  }

  private async ensureDiscoveryLoaded(): Promise<void> {
    const config = await this.loadRuntimeConfig();
    if (!config?.enabled || !isCompleteOidcConfig(config) || this.discoveryDocument()) {
      return;
    }

    const discoveryUrl = new URL('.well-known/openid-configuration', ensureTrailingSlash(config.issuer)).toString();
    const discovery = await firstValueFrom(
      this.http.get<OidcDiscoveryDocument>(discoveryUrl, {
        context: authInterceptorBypassContext(),
      }),
    );

    this.discoveryDocument.set(discovery ?? null);
  }

  private async handleCallbackFromCurrentUrl(config: AuthRuntimeConfig): Promise<void> {
    const callbackUrl = new URL(this.document.defaultView?.location.href ?? resolveAbsoluteUrl('/', this.document.baseURI));
    const callbackError = callbackUrl.searchParams.get('error');
    const code = String(callbackUrl.searchParams.get('code') ?? '').trim();
    const state = String(callbackUrl.searchParams.get('state') ?? '').trim();
    const pendingLogin = this.readPendingLogin();

    if (callbackError || !code || !state || !pendingLogin || pendingLogin.state !== state) {
      this.clearStoredSession();
      this.clearPendingLogin();
      this.principalData.set(null);
      this.setSessionState('expired_or_invalid_token', defaultStatusMessage('expired_or_invalid_token'));
      await this.router.navigate(['/auth/login'], {
        queryParams: {
          reason: 'expired_or_invalid_token',
          returnUrl: normalizeReturnUrl(pendingLogin?.returnUrl),
        },
        replaceUrl: true,
      });
      return;
    }

    try {
      await this.ensureDiscoveryLoaded();
      const discovery = this.discoveryDocument();
      if (!discovery?.token_endpoint) {
        throw new Error('OIDC token endpoint is unavailable.');
      }

      const body = new URLSearchParams();
      body.set('grant_type', 'authorization_code');
      body.set('client_id', config.clientId);
      body.set('code', code);
      body.set('redirect_uri', resolveAbsoluteUrl(config.redirectPath, this.document.baseURI));
      body.set('code_verifier', pendingLogin.codeVerifier);

      const tokenResponse = await firstValueFrom(
        this.http.post<OidcTokenResponse>(discovery.token_endpoint, body.toString(), {
          context: authInterceptorBypassContext(),
          headers: new HttpHeaders({
            'Content-Type': 'application/x-www-form-urlencoded',
          }),
        }),
      );

      const storedSession = normalizeTokenResponse(tokenResponse);
      if (!storedSession) {
        throw new Error('OIDC token response is incomplete.');
      }

      this.writeStoredSession(storedSession);
      this.clearPendingLogin();
      await this.bootstrapPrincipal();
      await this.router.navigateByUrl(pendingLogin.returnUrl || DEFAULT_AUTH_RETURN_URL, {
        replaceUrl: true,
      });
    } catch {
      this.clearStoredSession();
      this.clearPendingLogin();
      this.principalData.set(null);
      this.setSessionState('expired_or_invalid_token', defaultStatusMessage('expired_or_invalid_token'));
      await this.router.navigate(['/auth/login'], {
        queryParams: {
          reason: 'expired_or_invalid_token',
          returnUrl: normalizeReturnUrl(pendingLogin.returnUrl),
        },
        replaceUrl: true,
      });
    }
  }

  private readStoredSession(): StoredOidcSession | null {
    return readJsonSessionStorage<StoredOidcSession>(OIDC_SESSION_STORAGE_KEY);
  }

  private writeStoredSession(session: StoredOidcSession): void {
    writeJsonSessionStorage(OIDC_SESSION_STORAGE_KEY, session);
  }

  private clearStoredSession(): void {
    removeSessionStorage(OIDC_SESSION_STORAGE_KEY);
  }

  private readPendingLogin(): PendingLoginState | null {
    return readJsonSessionStorage<PendingLoginState>(OIDC_PENDING_LOGIN_STORAGE_KEY);
  }

  private writePendingLogin(loginState: PendingLoginState): void {
    writeJsonSessionStorage(OIDC_PENDING_LOGIN_STORAGE_KEY, loginState);
  }

  private clearPendingLogin(): void {
    removeSessionStorage(OIDC_PENDING_LOGIN_STORAGE_KEY);
  }

  private setSessionState(status: AuthSessionStatus, message: string | null): void {
    this.sessionStateData.update((current) => ({
      ...current,
      status,
      message,
      configured: current.configured || Boolean(this.runtimeConfig()),
      oidcEnabled: Boolean(this.runtimeConfig()?.enabled),
    }));
  }

  private readBrowserUrl(): string {
    const location = this.document.defaultView?.location;
    if (!location) {
      return DEFAULT_AUTH_RETURN_URL;
    }
    return `${location.pathname}${location.search}`;
  }
}

function normalizePrincipal(source: WhoAmIResponse | null | undefined): AuthPrincipal | null {
  if (!source || typeof source !== 'object') {
    return null;
  }

  const roles = [...new Set((source.roles ?? []).map((role) => String(role).trim()).filter(Boolean))];
  const permissions = [
    ...new Set(
      (source.permissions ?? [])
        .map((permission) => String(permission).trim().toLowerCase())
        .filter(Boolean),
    ),
  ];

  return {
    user_id: asNullableString(source.user_id),
    username: asNullableString(source.username),
    roles,
    permissions,
    tenant_context: normalizeTenantContext(source.tenant_context),
    operations_capabilities: normalizeOperationsCapabilities(source.operations_capabilities),
  };
}

function normalizeRuntimeConfig(source: Partial<AuthRuntimeConfig> | null | undefined): AuthRuntimeConfig | null {
  if (!source || typeof source !== 'object') {
    return null;
  }

  return {
    enabled: Boolean(source.enabled),
    issuer: String(source.issuer ?? '').trim(),
    clientId: String(source.clientId ?? '').trim(),
    scope: String(source.scope ?? '').trim() || 'openid profile email',
    redirectPath: String(source.redirectPath ?? '').trim() || '/auth/callback',
    postLogoutRedirectPath: String(source.postLogoutRedirectPath ?? '').trim() || '/auth/login',
    audience: asNullableString(source.audience),
  };
}

function isCompleteOidcConfig(config: AuthRuntimeConfig): boolean {
  return Boolean(config.issuer && config.clientId && config.scope && config.redirectPath && config.postLogoutRedirectPath);
}

function normalizeTokenResponse(source: OidcTokenResponse | null | undefined): StoredOidcSession | null {
  const accessToken = String(source?.access_token ?? '').trim();
  const expiresIn = Number(source?.expires_in);
  if (!accessToken || !Number.isFinite(expiresIn) || expiresIn <= 0) {
    return null;
  }

  return {
    accessToken,
    idToken: asNullableString(source?.id_token),
    tokenType: String(source?.token_type ?? 'Bearer').trim() || 'Bearer',
    expiresAt: Date.now() + (expiresIn * 1000),
    scope: asNullableString(source?.scope),
  };
}

function isStoredSessionExpired(session: StoredOidcSession): boolean {
  return !session.accessToken || !Number.isFinite(session.expiresAt) || session.expiresAt <= (Date.now() + OIDC_EXPIRY_SKEW_MS);
}

function readJsonSessionStorage<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeJsonSessionStorage(key: string, value: unknown): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore storage failures and keep the session in-memory only.
  }
}

function removeSessionStorage(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    // Ignore storage failures.
  }
}

function defaultStatusMessage(status: Extract<AuthSessionStatus, 'expired_or_invalid_token' | 'backend_auth_failure'>): string {
  if (status === 'expired_or_invalid_token') {
    return 'Your sign-in session is missing, expired, or invalid. Sign in again to continue.';
  }
  return 'DMIS could not validate your sign-in state with the backend. Sign in again or contact support if the issue persists.';
}

function normalizeReturnUrl(value: string): string {
  const normalized = String(value ?? '').trim();
  if (!normalized.startsWith('/') || normalized.startsWith('//')) {
    return DEFAULT_AUTH_RETURN_URL;
  }
  if (isAuthOnlyUrl(normalized)) {
    return DEFAULT_AUTH_RETURN_URL;
  }
  return normalized;
}

function isAuthOnlyUrl(url: string): boolean {
  const normalized = String(url ?? '').trim().toLowerCase();
  return normalized.startsWith('/auth/login') || normalized.startsWith('/auth/callback');
}

function isAuthCallbackUrl(url: string): boolean {
  return String(url ?? '').trim().toLowerCase().startsWith('/auth/callback');
}

function resolveAbsoluteUrl(path: string, baseUri: string): string {
  return new URL(path, baseUri).toString();
}

function ensureTrailingSlash(value: string): string {
  return value.endsWith('/') ? value : `${value}/`;
}

function generateRandomBase64Url(size: number): string {
  const bytes = new Uint8Array(size);
  crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

async function createPkceCodeChallenge(codeVerifier: string): Promise<string> {
  const encoded = new TextEncoder().encode(codeVerifier);
  const digest = await crypto.subtle.digest('SHA-256', encoded);
  return bytesToBase64Url(new Uint8Array(digest));
}

function bytesToBase64Url(bytes: Uint8Array): string {
  const binary = Array.from(bytes, (value) => String.fromCharCode(value)).join('');
  return btoa(binary)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '');
}

function normalizeTenantContext(source: Partial<TenantContextSummary> | null | undefined): TenantContextSummary | null {
  if (!source || typeof source !== 'object') {
    return null;
  }

  return {
    requested_tenant_id: asNullableNumber(source.requested_tenant_id),
    active_tenant_id: asNullableNumber(source.active_tenant_id),
    active_tenant_code: asNullableString(source.active_tenant_code),
    active_tenant_type: asNullableString(source.active_tenant_type),
    is_neoc: Boolean(source.is_neoc),
    can_read_all_tenants: Boolean(source.can_read_all_tenants),
    can_act_cross_tenant: Boolean(source.can_act_cross_tenant),
    memberships: Array.isArray(source.memberships)
      ? source.memberships.map((membership) => ({
        tenant_id: asNullableNumber(membership?.tenant_id),
        tenant_code: asNullableString(membership?.tenant_code),
        tenant_name: asNullableString(membership?.tenant_name),
        tenant_type: asNullableString(membership?.tenant_type),
        is_primary: Boolean(membership?.is_primary),
        access_level: asNullableString(membership?.access_level),
      }))
      : [],
  };
}

const VALID_ORIGIN_MODES = new Set<OperationsCapabilities['relief_request_submission_mode']>([
  'self',
  'for_subordinate',
  'on_behalf_bridge',
]);

function normalizeOperationsCapabilities(
  source: Partial<OperationsCapabilities> | null | undefined,
): OperationsCapabilities | null {
  if (!source || typeof source !== 'object') {
    return null;
  }

  const submissionMode = String(source.relief_request_submission_mode ?? '').trim().toLowerCase();
  const validMode = VALID_ORIGIN_MODES.has(submissionMode as OperationsCapabilities['relief_request_submission_mode'])
    ? submissionMode as OperationsCapabilities['relief_request_submission_mode']
    : null;

  return {
    can_create_relief_request: Boolean(source.can_create_relief_request),
    can_create_relief_request_on_behalf: Boolean(source.can_create_relief_request_on_behalf),
    relief_request_submission_mode: validMode,
    default_requesting_tenant_id: asNullableNumber(source.default_requesting_tenant_id),
    allowed_origin_modes: normalizeAllowedOriginModes(source, validMode),
  };
}

function normalizeAllowedOriginModes(
  source: Record<string, unknown>,
  fallbackMode: OperationsCapabilities['relief_request_submission_mode'],
): OperationsCapabilities['allowed_origin_modes'] {
  const raw = source['allowed_origin_modes'];
  if (Array.isArray(raw)) {
    return raw
      .map((entry) => String(entry ?? '').trim().toLowerCase())
      .filter(
        (mode): mode is NonNullable<OperationsCapabilities['relief_request_submission_mode']> =>
          VALID_ORIGIN_MODES.has(mode as OperationsCapabilities['relief_request_submission_mode']),
      );
  }
  return fallbackMode ? [fallbackMode] : [];
}

function asNullableString(value: unknown): string | null {
  const normalized = String(value ?? '').trim();
  return normalized ? normalized : null;
}

function asNullableNumber(value: unknown): number | null {
  if (value == null || value === '') {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
