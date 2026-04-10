import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AuthSessionService, AuthSessionStatus } from '../core/auth-session.service';
import { AuthRbacService } from '../replenishment/services/auth-rbac.service';

@Component({
  selector: 'dmis-auth-login-page',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="auth-page">
      <div class="auth-card">
        <p class="auth-eyebrow">DMIS Authentication</p>
        <h1>Sign in to continue</h1>
        <p class="auth-copy">{{ message() }}</p>

        @if (loginEnabled()) {
          <button type="button" class="auth-primary" (click)="signIn()" [disabled]="working()">
            {{ working() ? 'Redirecting...' : 'Sign in with OIDC' }}
          </button>
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
  styles: [`
    :host {
      display: block;
      min-height: 100vh;
      background:
        radial-gradient(circle at top, rgba(17, 93, 89, 0.16), transparent 34%),
        linear-gradient(180deg, #eef7f5 0%, #f7faf9 100%);
    }

    .auth-page {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 1.5rem;
    }

    .auth-card {
      width: min(100%, 34rem);
      padding: 2rem;
      border-radius: 1.5rem;
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid rgba(17, 93, 89, 0.14);
      box-shadow: 0 1.25rem 3rem rgba(19, 49, 46, 0.1);
    }

    .auth-eyebrow {
      margin: 0 0 0.75rem;
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #115d59;
    }

    h1 {
      margin: 0;
      font-size: clamp(1.9rem, 5vw, 2.5rem);
      line-height: 1.05;
      color: #17302f;
    }

    .auth-copy,
    .auth-warning,
    .auth-hint {
      margin: 1rem 0 0;
      color: #365654;
      line-height: 1.55;
    }

    .auth-warning {
      padding: 0.9rem 1rem;
      border-radius: 0.9rem;
      background: #fff3d6;
      border: 1px solid #efdca5;
      color: #684e16;
    }

    .auth-primary {
      margin-top: 1.25rem;
      border: 0;
      border-radius: 999px;
      padding: 0.9rem 1.25rem;
      background: linear-gradient(135deg, #115d59 0%, #16807b 100%);
      color: #fff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 0.8rem 1.8rem rgba(17, 93, 89, 0.24);
    }

    .auth-primary:disabled {
      cursor: wait;
      opacity: 0.75;
    }

    code {
      font-size: 0.95em;
      color: #17302f;
    }
  `],
})
export class DmisAuthLoginPageComponent {
  readonly defaultReturnUrl = '/replenishment/dashboard';

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly authSession = inject(AuthSessionService);

  readonly working = signal(false);
  readonly returnUrl = signal(this.defaultReturnUrl);
  readonly loginEnabled = computed(() => this.authSession.loginAvailable());
  readonly message = computed(() =>
    messageForStatus(
      this.route.snapshot.queryParamMap.get('reason'),
      this.authSession.state().status,
      this.authSession.state().message,
    ),
  );

  constructor() {
    const initialReturnUrl = this.route.snapshot.queryParamMap.get('returnUrl');
    this.returnUrl.set(initialReturnUrl?.trim() || this.defaultReturnUrl);

    if (this.authSession.authenticated()) {
      void this.router.navigateByUrl(this.returnUrl(), { replaceUrl: true });
    }

    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      this.returnUrl.set(params.get('returnUrl')?.trim() || this.defaultReturnUrl);
    });
  }

  async signIn(): Promise<void> {
    this.working.set(true);
    try {
      await this.authSession.startLogin(this.returnUrl());
    } finally {
      this.working.set(false);
    }
  }
}

@Component({
  selector: 'dmis-auth-callback-page',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="auth-page">
      <div class="auth-card">
        <p class="auth-eyebrow">DMIS Authentication</p>
        <h1>Completing sign-in</h1>
        <p class="auth-copy">{{ message() }}</p>

        @if (showRetry()) {
          <a class="auth-link" routerLink="/auth/login">Return to sign-in</a>
        }
      </div>
    </section>
  `,
  styles: [`
    :host {
      display: block;
      min-height: 100vh;
      background:
        radial-gradient(circle at top, rgba(17, 93, 89, 0.16), transparent 34%),
        linear-gradient(180deg, #eef7f5 0%, #f7faf9 100%);
    }

    .auth-page {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 1.5rem;
    }

    .auth-card {
      width: min(100%, 30rem);
      padding: 2rem;
      border-radius: 1.5rem;
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid rgba(17, 93, 89, 0.14);
      box-shadow: 0 1.25rem 3rem rgba(19, 49, 46, 0.1);
    }

    .auth-eyebrow {
      margin: 0 0 0.75rem;
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #115d59;
    }

    h1 {
      margin: 0;
      font-size: clamp(1.8rem, 5vw, 2.35rem);
      line-height: 1.05;
      color: #17302f;
    }

    .auth-copy {
      margin: 1rem 0 0;
      color: #365654;
      line-height: 1.55;
    }

    .auth-link {
      display: inline-block;
      margin-top: 1.25rem;
      color: #115d59;
      font-weight: 700;
      text-decoration: none;
    }
  `],
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

  readonly showRetry = computed(() => this.authSession.state().status !== 'bootstrapping');
}

@Component({
  selector: 'dmis-access-denied-page',
  standalone: true,
  imports: [RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="access-page">
      <div class="access-card">
        <p class="access-eyebrow">Access Denied</p>
        <h1>You are signed in, but this route is not available to your account.</h1>
        <p class="access-copy">
          DMIS keeps backend authorization as the source of truth. The frontend blocked this route early so you do
          not land on a misleading empty page.
        </p>
        <p class="access-copy">
          Signed in as <strong>{{ currentUser() }}</strong>
        </p>

        <div class="access-actions">
          <a class="access-primary" [routerLink]="['/replenishment/dashboard']">Go to dashboard</a>
          <a class="access-secondary" [routerLink]="['/operations/dashboard']">Try operations</a>
        </div>
      </div>
    </section>
  `,
  styles: [`
    :host {
      display: block;
      min-height: 100%;
    }

    .access-page {
      display: grid;
      place-items: center;
      padding: 1rem 0 3rem;
    }

    .access-card {
      width: min(100%, 42rem);
      padding: 1.75rem;
      border-radius: 1.25rem;
      background: linear-gradient(180deg, rgba(255, 247, 235, 0.9) 0%, rgba(255, 255, 255, 0.98) 100%);
      border: 1px solid rgba(211, 162, 76, 0.28);
      box-shadow: 0 1rem 2.4rem rgba(68, 49, 14, 0.12);
    }

    .access-eyebrow {
      margin: 0 0 0.75rem;
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #8b5e17;
    }

    h1 {
      margin: 0;
      font-size: clamp(1.7rem, 5vw, 2.2rem);
      line-height: 1.1;
      color: #2c220f;
    }

    .access-copy {
      margin: 1rem 0 0;
      color: #5d4c2c;
      line-height: 1.55;
    }

    .access-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-top: 1.5rem;
    }

    .access-primary,
    .access-secondary {
      border-radius: 999px;
      padding: 0.8rem 1.1rem;
      font-weight: 700;
      text-decoration: none;
    }

    .access-primary {
      background: #8b5e17;
      color: #fff;
    }

    .access-secondary {
      background: rgba(139, 94, 23, 0.08);
      color: #8b5e17;
    }
  `],
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
