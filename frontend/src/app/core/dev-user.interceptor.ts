import { HttpInterceptorFn } from '@angular/common/http';

const DEV_USER_KEY = 'dmis_dev_user';
const DEV_USER_HEADER = 'X-Dev-User';

export const devUserInterceptor: HttpInterceptorFn = (req, next) => {
  const requestedUser = localStorage.getItem(DEV_USER_KEY)?.trim();
  if (!requestedUser) {
    return next(req);
  }

  return next(
    req.clone({
      setHeaders: {
        [DEV_USER_HEADER]: requestedUser
      }
    })
  );
};
