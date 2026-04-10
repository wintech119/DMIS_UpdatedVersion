import { HttpInterceptorFn } from '@angular/common/http';

const LOCAL_HARNESS_USER_KEY = 'dmis_local_harness_user';
const LOCAL_HARNESS_USER_HEADER = 'X-DMIS-Local-User';

export const devUserInterceptor: HttpInterceptorFn = (req, next) => {
  const hostname = window.location.hostname;
  const isLocalHost = hostname === 'localhost'
    || hostname === '127.0.0.1'
    || hostname === '[::1]'
    || hostname.endsWith('.local');
  if (!isLocalHost) {
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
