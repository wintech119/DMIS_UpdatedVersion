import { HttpInterceptorFn } from '@angular/common/http';

import { devUserInterceptor } from './dev-user.interceptor';

export const DMIS_HTTP_INTERCEPTORS: HttpInterceptorFn[] = [devUserInterceptor];
