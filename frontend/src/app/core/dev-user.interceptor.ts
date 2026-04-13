import { HttpInterceptorFn } from '@angular/common/http';

declare const DMIS_LOCAL_AUTH_HARNESS_BUILD: boolean;

const LOCAL_HARNESS_USER_KEY = 'dmis_local_harness_user';
const LOCAL_HARNESS_USER_HEADER = 'X-DMIS-Local-User';
const TEST_BUILD_FLAG_KEY = '__DMIS_LOCAL_AUTH_HARNESS_BUILD__';

type LocationLike = Pick<Location, 'hostname'> & Partial<Pick<Location, 'origin'>>;

function readLocalHarnessBuildOverride(): boolean | null {
  const globalScope = globalThis as typeof globalThis & Record<string, unknown>;
  const override = globalScope[TEST_BUILD_FLAG_KEY];

  return typeof override === 'boolean' ? override : null;
}

export function localAuthHarnessBuildEnabled(): boolean {
  const override = readLocalHarnessBuildOverride();
  if (override != null) {
    return override;
  }

  return typeof DMIS_LOCAL_AUTH_HARNESS_BUILD === 'undefined'
    ? false
    : DMIS_LOCAL_AUTH_HARNESS_BUILD;
}

export function isLocalAuthHarnessHost(locationLike: LocationLike = window.location): boolean {
  const hostname = locationLike.hostname;

  return hostname === 'localhost'
    || hostname === '127.0.0.1'
    || hostname === '[::1]'
    || hostname.endsWith('.local');
}

export function localAuthHarnessClientEnabled(
  locationLike: LocationLike = window.location,
): boolean {
  return localAuthHarnessBuildEnabled() && isLocalAuthHarnessHost(locationLike);
}

export function isLocalAuthHarnessRequestTarget(
  requestUrl: string,
  locationLike: LocationLike = window.location,
): boolean {
  try {
    if (requestUrl.startsWith('/')) {
      return true;
    }

    const origin = locationLike.origin ?? window.location.origin;
    const resolvedUrl = new URL(requestUrl, origin);
    return isLocalAuthHarnessHost({
      hostname: resolvedUrl.hostname,
      origin: resolvedUrl.origin,
    });
  } catch {
    return false;
  }
}

export const devUserInterceptor: HttpInterceptorFn = (req, next) => {
  if (!localAuthHarnessClientEnabled() || !isLocalAuthHarnessRequestTarget(req.url)) {
    return next(req);
  }

  const requestedUser = localStorage.getItem(LOCAL_HARNESS_USER_KEY)?.trim();
  if (!requestedUser) {
    return next(req);
  }

  return next(
    req.clone({
      setHeaders: {
        [LOCAL_HARNESS_USER_HEADER]: requestedUser
      }
    })
  );
};
