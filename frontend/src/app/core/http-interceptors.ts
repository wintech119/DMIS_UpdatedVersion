import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

import {
  AUTH_HANDLED_BY_CALLER,
  AUTH_INTERCEPTOR_BYPASS,
  AuthSessionService,
  isExpiredOrInvalidTokenResponse,
} from './auth-session.service';
import { devUserInterceptor } from './dev-user.interceptor';

export const DMIS_HTTP_INTERCEPTORS: HttpInterceptorFn[] = [
  devUserInterceptor,
  authTokenInterceptor,
  authFailureClassifierInterceptor,
];

export const authTokenInterceptor: HttpInterceptorFn = (req, next) => {
  const authSession = inject(AuthSessionService);

  if (req.context.get(AUTH_INTERCEPTOR_BYPASS) || !isDmisApiRequest(req.url) || isLocalHarnessRequest(req.url)) {
    return next(req);
  }

  const accessToken = authSession.getAccessToken();
  if (!accessToken) {
    return next(req);
  }

  return next(
    req.clone({
      setHeaders: {
        Authorization: `Bearer ${accessToken}`,
      },
    }),
  );
};

export const authFailureClassifierInterceptor: HttpInterceptorFn = (req, next) => {
  const authSession = inject(AuthSessionService);

  return next(req).pipe(
    catchError((error: unknown) => {
      if (
        isExpiredOrInvalidTokenResponse(error)
        && !req.context.get(AUTH_INTERCEPTOR_BYPASS)
        && !req.context.get(AUTH_HANDLED_BY_CALLER)
        && isDmisApiRequest(req.url)
      ) {
        authSession.handleApiAuthFailure('expired_or_invalid_token');
      }

      return throwError(() => error);
    }),
  );
};

function isDmisApiRequest(url: string): boolean {
  return String(url ?? '').startsWith('/api/');
}

function isLocalHarnessRequest(url: string): boolean {
  return String(url ?? '').startsWith('/api/v1/auth/local-harness/');
}
