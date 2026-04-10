import { ApplicationConfig, inject, provideAppInitializer, provideZoneChangeDetection } from '@angular/core';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { provideAnimations } from '@angular/platform-browser/animations';

import { routes } from './app.routes';
import { AuthSessionService } from './core/auth-session.service';
import { DMIS_HTTP_INTERCEPTORS } from './core/http-interceptors';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(withInterceptors(DMIS_HTTP_INTERCEPTORS)),
    provideAnimations(),
    provideAppInitializer(() => inject(AuthSessionService).initializeApp()),
  ]
};
