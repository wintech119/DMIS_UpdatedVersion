import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';

import { normalizeRequestedUrlString } from '../core/app-access.guard';
import { AuthSessionService, AuthSessionStatus } from '../core/auth-session.service';
import { localAuthHarnessClientEnabled } from '../core/dev-user.interceptor';
import { DmisLocalHarnessSwitcherComponent } from '../local-harness-switcher.component';
import { AuthRbacService } from '../replenishment/services/auth-rbac.service';

const AUTH_PAGE_STYLES = [`
  :host {
    position: relative;
    display: block;
    min-height: 100vh;
    min-height: 100dvh;
    background: var(--color-surface-muted);
    color: var(--color-text-primary);
    font-family: var(--dmis-font-sans);
  }

  :host::before {
    content: '';
    position: fixed;
    inset: 0 0 auto;
    z-index: 1;
    height: 4px;
    background: var(--color-accent);
  }

  .auth-page {
    min-height: 100vh;
    min-height: 100dvh;
    display: grid;
    place-items: center;
    padding: 4rem var(--page-padding) var(--page-padding);
  }

  .auth-card {
    position: relative;
    width: min(100%, 26rem);
    padding: 2rem 1.75rem;
    overflow: hidden;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-card);
    background: var(--color-surface);
    box-shadow: 0 1px 2px color-mix(in srgb, var(--color-text-primary) 4%, transparent);
  }

  .auth-card::before {
    content: '';
    position: absolute;
    inset: 0 0 auto;
    height: 3px;
    background: var(--color-accent);
  }

  .auth-brand-mark {
    width: 32px;
    aspect-ratio: 1;
    margin: 0 0 0.75rem;
    border-radius: var(--radius-inner);
    background: var(--color-surface-muted);
  }

  .auth-eyebrow {
    margin: 0 0 0.5rem;
    color: var(--color-accent);
    font-size: var(--text-xs);
    font-weight: var(--weight-bold);
    letter-spacing: var(--tracking-wide);
    line-height: var(--leading-tight);
    text-transform: uppercase;
  }

  h1 {
    margin: 0;
    color: var(--color-text-primary);
    font-size: clamp(1.875rem, 5.5vw, 2.25rem);
    font-weight: var(--weight-bold);
    letter-spacing: 0;
    line-height: 1.1;
  }

  .auth-status,
  .auth-warning,
  .auth-hint,
  .auth-copy {
    color: var(--color-text-primary);
    font-size: var(--text-base);
    font-weight: var(--weight-normal);
    line-height: var(--leading-relaxed);
  }

  .auth-status {
    margin: 1rem 0 0;
  }

  .auth-status[data-tone='critical'] {
    padding-left: 0.875rem;
    border-left: 1px solid var(--color-critical);
  }

  .auth-warning {
    margin: 0;
    padding: 0.875rem 1rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-card);
    background: var(--color-bg-warning);
    color: var(--color-warning-text);
  }

  .auth-hint,
  .auth-copy {
    margin: 1rem 0 0;
    color: var(--color-text-secondary);
    font-size: var(--text-sm);
    line-height: var(--leading-normal);
  }

  .auth-primary,
  .auth-secondary,
  .auth-link {
    min-height: 44px;
    border-radius: var(--radius-card);
    font-family: var(--dmis-font-sans);
    font-size: var(--text-md);
    font-weight: var(--weight-semibold);
    letter-spacing: var(--tracking-tight);
    line-height: 1;
    text-decoration: none;
  }

  .auth-primary {
    width: 100%;
    margin-top: 1.5rem;
    border: 0;
    padding: 0.75rem 1rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--color-accent);
    color: var(--color-surface);
    cursor: pointer;
    transition: background-color 200ms ease;
  }

  .auth-primary:hover:not(:disabled) {
    background: color-mix(in srgb, var(--color-accent) 88%, var(--color-text-primary));
  }

  .auth-primary:focus-visible,
  .auth-secondary:focus-visible,
  .auth-link:focus-visible {
    outline: none;
    box-shadow: 0 0 0 3px var(--color-focus-ring);
  }

  .auth-primary:active:not(:disabled) {
    transform: translateY(1px);
    background: color-mix(in srgb, var(--color-accent) 80%, var(--color-text-primary));
  }

  .auth-primary:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .auth-primary__skeleton {
    position: relative;
    width: 60%;
    height: 12px;
    overflow: hidden;
    border-radius: var(--radius-inner);
    background: color-mix(in srgb, var(--color-surface) 25%, var(--color-accent));
  }

  .auth-primary__skeleton::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(
      90deg,
      transparent,
      color-mix(in srgb, var(--color-surface) 45%, transparent),
      transparent
    );
    transform: translateX(-100%);
  }

  .auth-secondary,
  .auth-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-top: 1.5rem;
    padding: 0.75rem 1rem;
    border: 1px solid var(--color-border);
    background: color-mix(in srgb, var(--color-accent) 8%, var(--color-surface));
    color: var(--color-accent);
  }

  .auth-local-harness {
    margin-top: 1.5rem;
    display: grid;
    gap: 1rem;
  }

  .auth-local-harness dmis-local-harness-switcher {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .auth-actions {
    display: grid;
    gap: 0.75rem;
    margin-top: 1.5rem;
  }

  .auth-actions .auth-primary,
  .auth-actions .auth-secondary {
    margin-top: 0;
  }

  code {
    color: var(--color-text-primary);
    font-size: 0.95em;
  }

  @media (prefers-reduced-motion: no-preference) {
    .auth-primary__skeleton::after {
      animation: auth-skeleton-shimmer 1.2s ease-in-out infinite;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .auth-primary,
    .auth-primary__skeleton::after {
      transition: none;
      animation: none;
    }

    .auth-primary:active:not(:disabled) {
      transform: none;
    }
  }

  @media (max-width: 520px) {
    .auth-page {
      place-items: start center;
    }

    .auth-card {
      width: 100%;
    }
  }

  @keyframes auth-skeleton-shimmer {
    to {
      transform: translateX(100%);
    }
  }
`];

@Component({
  selector: 'dmis-auth-login-page',
  standalone: true,
  imports: [DmisLocalHarnessSwitcherComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="auth-page" aria-label="DMIS authentication sign in">
      <div class="auth-card">
        <div class="auth-brand-mark" aria-hidden="true"></div>
        <p class="auth-eyebrow">DMIS Authentication</p>
        <h1>Sign in to continue</h1>
        <p class="auth-status" role="status" aria-live="polite" [attr.data-tone]="state().tone">
          {{ state().message }}
        </p>

        @if (loginEnabled()) {
          <button
            type="button"
            class="auth-primary"
            (click)="signIn()"
            [disabled]="working()"
            [attr.aria-busy]="working() ? 'true' : 'false'">
            @if (working()) {
              <span class="auth-primary__skeleton" aria-hidden="true"></span>
              <span class="sr-only">Redirecting to OIDC sign-in</span>
            } @else {
              <span>Sign in with OIDC</span>
            }
          </button>
        } @else if (localHarnessClientEnabled) {
          <div class="auth-local-harness">
            <p class="auth-warning">
              Local harness mode is active. Select an allowlisted local test user to continue.
            </p>
            <button
              type="button"
              class="auth-primary"
              (click)="continueLocalHarness()"
              [disabled]="localHarnessWorking()"
              [attr.aria-busy]="localHarnessWorking() ? 'true' : 'false'">
              @if (localHarnessWorking()) {
                <span class="auth-primary__skeleton" aria-hidden="true"></span>
                <span class="sr-only">Checking local session</span>
              } @else {
                <span>Continue in local mode</span>
              }
            </button>
            <dmis-local-harness-switcher />
          </div>
        } @else {
          <p class="auth-warning">
            OIDC login is not configured for this deployment. Update
            <code>frontend/public/auth-config.json</code> before using a non-local environment.
          </p>
        }

        @if (returnUrl() !== defaultReturnUrl) {
          <p class="auth-hint">After sign-in, DMIS will return you to <code>{{ returnUrl() }}</code>.</p>
        }
      </div>
    </section>
  `,
  styles: AUTH_PAGE_STYLES,
})
export class DmisAuthLoginPageComponent {
  readonly defaultReturnUrl = '/replenishment/dashboard';

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly authSession = inject(AuthSessionService);

  readonly localHarnessClientEnabled = localAuthHarnessClientEnabled();
  readonly working = signal(false);
  readonly localHarnessWorking = signal(false);
  readonly localHarnessError = signal<string | null>(null);
  readonly returnUrl = signal(this.defaultReturnUrl);
  readonly loginEnabled = computed(() => this.authSession.loginAvailable() && !this.authSession.authenticated());
  readonly message = computed(() => {
    if (this.localHarnessClientEnabled && !this.authSession.loginAvailable()) {
      return 'Use the local harness session to continue.';
    }
    return messageForStatus(
      this.route.snapshot.queryParamMap.get('reason'),
      this.authSession.state().status,
      this.authSession.state().message,
    );
  });
  readonly state = computed(() => {
    const status = this.authSession.state().status;
    const routeReason = String(this.route.snapshot.queryParamMap.get('reason') ?? '').trim().toLowerCase();
    const localError = this.localHarnessError();
    const critical = Boolean(localError)
      || routeReason === 'expired_or_invalid_token'
      || routeReason === 'backend_auth_failure'
      || status === 'expired_or_invalid_token'
      || status === 'backend_auth_failure';
    return {
      message: localError ?? this.message(),
      tone: critical ? 'critical' : 'neutral',
    };
  });

  constructor() {
    const initialReturnUrl = this.route.snapshot.queryParamMap.get('returnUrl');
    this.returnUrl.set(this.resolveReturnUrl(initialReturnUrl));

    if (this.authSession.authenticated()) {
      void this.router.navigateByUrl(this.resolveReturnUrl(this.returnUrl()), { replaceUrl: true });
    }

    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      this.returnUrl.set(this.resolveReturnUrl(params.get('returnUrl')));
    });
  }

  async signIn(): Promise<void> {
    this.working.set(true);
    try {
      await this.authSession.startLogin(this.resolveReturnUrl(this.returnUrl()));
    } finally {
      this.working.set(false);
    }
  }

  async continueLocalHarness(): Promise<void> {
    this.localHarnessWorking.set(true);
    this.localHarnessError.set(null);
    try {
      await firstValueFrom(this.authSession.refreshPrincipal());
      if (this.authSession.authenticated()) {
        await this.router.navigateByUrl(this.resolveReturnUrl(this.returnUrl()), { replaceUrl: true });
        return;
      }

      this.localHarnessError.set(
        this.authSession.state().message
          ?? 'DMIS could not validate the local harness session. Confirm the Django backend is running over HTTP.',
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : null;
      this.localHarnessError.set(
        message
          || this.authSession.state().message
          || 'DMIS could not validate the local harness session. Confirm the Django backend is running over HTTP.',
      );
    } finally {
      this.localHarnessWorking.set(false);
    }
  }

  private resolveReturnUrl(rawValue: string | null | undefined): string {
    const trimmed = String(rawValue ?? '').trim();
    if (!trimmed) {
      return this.defaultReturnUrl;
    }
    const normalized = normalizeRequestedUrlString(trimmed);
    if (!normalized || (normalized === '/' && trimmed !== '/')) {
      return this.defaultReturnUrl;
    }
    return normalized;
  }
}

@Component({
  selector: 'dmis-auth-callback-page',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="auth-page" aria-label="DMIS authentication callback">
      <div class="auth-card">
        <div class="auth-brand-mark" aria-hidden="true"></div>
        <p class="auth-eyebrow">DMIS Authentication</p>
        <h1>Completing sign-in</h1>
        <p
          class="auth-status"
          role="status"
          aria-live="polite"
          [attr.data-tone]="showRetry() ? 'critical' : 'neutral'">
          {{ message() }}
        </p>

        @if (showRetry()) {
          <a class="auth-link" routerLink="/auth/login">Return to sign-in</a>
        }
      </div>
    </section>
  `,
  styles: AUTH_PAGE_STYLES,
})
export class DmisAuthCallbackPageComponent {
  private readonly authSession = inject(AuthSessionService);

  readonly message = computed(() => {
    const state = this.authSession.state();
    if (state.status === 'bootstrapping') {
      return 'DMIS is validating the authorization response and restoring your session.';
    }
    if (state.status === 'authenticated') {
      return 'Your session is ready. Redirecting you back into DMIS.';
    }
    return messageForStatus('expired_or_invalid_token', state.status, state.message);
  });

  readonly showRetry = computed(() => {
    const status = this.authSession.state().status;
    return status !== 'bootstrapping' && status !== 'authenticated';
  });
}

@Component({
  selector: 'dmis-access-denied-page',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="auth-page" aria-label="DMIS access denied">
      <div class="auth-card">
        <div class="auth-brand-mark" aria-hidden="true"></div>
        <p class="auth-eyebrow">Access Denied</p>
        <h1>You are signed in, but this route is not available to your account.</h1>
        <p class="auth-status" role="status" aria-live="polite" data-tone="critical">
          DMIS keeps backend authorization as the source of truth. The frontend blocked this route early so you do
          not land on a misleading empty page.
        </p>
        <p class="auth-hint">
          Signed in as <strong>{{ currentUser() }}</strong>
        </p>

        <div class="auth-actions">
          <a class="auth-primary" [routerLink]="['/replenishment/dashboard']">Go to dashboard</a>
          <a class="auth-secondary" [routerLink]="['/operations/dashboard']">Try operations</a>
        </div>
      </div>
    </section>
  `,
  styles: AUTH_PAGE_STYLES,
})
export class DmisAccessDeniedPageComponent {
  private readonly authRbac = inject(AuthRbacService);

  readonly currentUser = computed(() => this.authRbac.currentUserRef() ?? 'Unknown user');
}

function messageForStatus(
  routeReason: string | null,
  status: AuthSessionStatus,
  fallbackMessage: string | null,
): string {
  const normalizedReason = String(routeReason ?? '').trim().toLowerCase();
  if (normalizedReason === 'expired_or_invalid_token' || status === 'expired_or_invalid_token') {
    return fallbackMessage ?? 'Your session expired or the token is no longer valid. Sign in again to continue.';
  }
  if (normalizedReason === 'backend_auth_failure' || status === 'backend_auth_failure') {
    return fallbackMessage ?? 'DMIS could not verify your session with the backend. Sign in again or contact support if the issue persists.';
  }
  return fallbackMessage ?? 'DMIS requires a real sign-in session before you can open protected routes.';
}
