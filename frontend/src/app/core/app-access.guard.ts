import { inject } from '@angular/core';
import {
  CanActivateFn,
  CanMatchFn,
  Router,
  UrlSegment,
  UrlTree,
} from '@angular/router';
import { map, Observable } from 'rxjs';

import { AuthSessionService } from './auth-session.service';
import { AppAccessService } from './app-access.service';

export const appAccessGuard: CanActivateFn = (route, state) =>
  evaluateProtectedRouteAccess(
    state.url,
    () => isRouteAllowed(inject(AppAccessService), route.data ?? {}),
  );

export const appAccessMatchGuard: CanMatchFn = (route, segments) =>
  evaluateProtectedRouteAccess(
    normalizeRequestedUrl(segments, route.path),
    () => isRouteAllowed(inject(AppAccessService), route.data ?? {}),
  );

export function evaluateProtectedRouteAccess(
  requestedUrl: string,
  accessCheck: () => boolean,
): Observable<boolean | UrlTree> {
  const router = inject(Router);
  const authSession = inject(AuthSessionService);

  return authSession.ensureInitialized().pipe(
    map(() => {
      const state = authSession.state();
      const normalizedReturnUrl = normalizeRequestedUrlString(requestedUrl);

      if (state.status !== 'authenticated') {
        return router.createUrlTree(['/auth/login'], {
          queryParams: {
            reason: state.status === 'bootstrapping' ? 'unauthenticated' : state.status,
            returnUrl: normalizedReturnUrl,
          },
        });
      }

      if (accessCheck()) {
        return true;
      }

      return router.createUrlTree(['/access-denied'], {
        queryParams: {
          returnUrl: normalizedReturnUrl,
        },
      });
    }),
  );
}

function isRouteAllowed(access: AppAccessService, data: Record<string, unknown>): boolean {
  const accessKey = typeof data['accessKey'] === 'string' ? data['accessKey'] : null;
  if (accessKey) {
    return access.canAccessNavKey(accessKey);
  }

  const routePath = typeof data['routePath'] === 'string' ? data['routePath'] : null;
  const action = typeof data['masterAction'] === 'string' ? data['masterAction'] : 'view';

  if (!routePath) {
    return true;
  }

  if (action === 'create') {
    return access.canCreateMasterRoutePath(routePath);
  }
  if (action === 'edit') {
    return access.canEditMasterRoutePath(routePath);
  }
  return access.canAccessMasterRoutePath(routePath);
}

function normalizeRequestedUrl(segments: UrlSegment[], routePath?: string | null): string {
  if (segments.length > 0) {
    return normalizeRequestedUrlString(`/${segments.map((segment) => segment.path).join('/')}`);
  }
  if (routePath) {
    return normalizeRequestedUrlString(`/${routePath}`);
  }
  return '/';
}

function normalizeRequestedUrlString(value: string): string {
  const normalized = String(value ?? '').trim();
  if (!normalized.startsWith('/') || normalized.startsWith('//')) {
    return '/';
  }
  if (normalized.startsWith('/auth/login') || normalized.startsWith('/auth/callback')) {
    return '/';
  }
  return normalized || '/';
}
