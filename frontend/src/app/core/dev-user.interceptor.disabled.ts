import { HttpInterceptorFn } from '@angular/common/http';

type LocationLike = Pick<Location, 'hostname'>;

export function localAuthHarnessBuildEnabled(): boolean {
  return false;
}

export function isLocalAuthHarnessHost(_locationLike?: LocationLike): boolean {
  return false;
}

export function localAuthHarnessClientEnabled(_locationLike?: LocationLike): boolean {
  return false;
}

export const devUserInterceptor: HttpInterceptorFn = (req, next) => next(req);
