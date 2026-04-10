import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { provideNoopAnimations } from '@angular/platform-browser/animations';
import { convertToParamMap } from '@angular/router';
import { of } from 'rxjs';

import { AuthSessionService } from '../core/auth-session.service';
import { AuthRbacService } from '../replenishment/services/auth-rbac.service';
import {
  DmisAccessDeniedPageComponent,
  DmisAuthLoginPageComponent,
} from './auth-pages.component';

describe('Auth pages', () => {
  it('shows the non-local OIDC configuration warning on the login page when login is unavailable', async () => {
    const authSession = {
      loginAvailable: signal(false),
      authenticated: signal(false),
      state: signal({
        status: 'unauthenticated' as const,
        message: 'Sign in to continue.',
        configured: false,
        oidcEnabled: false,
      }),
      startLogin: jasmine.createSpy('startLogin'),
    };

    await TestBed.configureTestingModule({
      imports: [DmisAuthLoginPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        { provide: AuthSessionService, useValue: authSession },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: convertToParamMap({ reason: 'unauthenticated' }),
            },
            queryParamMap: of(convertToParamMap({ reason: 'unauthenticated' })),
          },
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DmisAuthLoginPageComponent);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('OIDC login is not configured for this deployment');
  });

  it('shows the signed-in user on the access denied page', async () => {
    await TestBed.configureTestingModule({
      imports: [DmisAccessDeniedPageComponent],
      providers: [
        provideRouter([]),
        provideNoopAnimations(),
        {
          provide: AuthRbacService,
          useValue: {
            currentUserRef: signal('ops.user'),
          },
        },
      ],
    }).compileComponents();

    const fixture = TestBed.createComponent(DmisAccessDeniedPageComponent);
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('ops.user');
    expect(element.textContent).toContain('route is not available');
  });
});
