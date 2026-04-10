import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { AppComponent } from './app.component';

describe('AppComponent', () => {
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    flushInitialRequests(httpMock);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render topbar root label', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    flushInitialRequests(httpMock);
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.breadcrumb-root')?.textContent).toContain('DMIS');
  });

  it('shows local test mode options when the harness endpoint is enabled', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    httpMock.expectOne('/api/v1/auth/whoami/').flush({
      user_id: '27',
      username: 'local_system_admin_tst',
      roles: ['SYSTEM_ADMINISTRATOR'],
      permissions: ['masterdata.view'],
    });
    httpMock.expectOne('/api/v1/auth/local-harness/').flush({
      enabled: true,
      default_user: 'local_system_admin_tst',
      users: [
        {
          user_id: '42',
          username: 'local_odpem_deputy_director_tst',
          email: 'natalie.williams+national.deputy-director@odpem.gov.jm',
          roles: ['ODPEM_DDG'],
          memberships: [
            {
              tenant_id: 2,
              tenant_code: 'ODPEM-NEOC',
              tenant_name: 'ODPEM NEOC',
              tenant_type: 'NEOC',
              is_primary: true,
              access_level: 'FULL',
            },
          ],
        },
        {
          user_id: '64',
          username: 'local_odpem_logistics_manager_tst',
          email: 'kemar.campbell+national.logistics-manager@odpem.gov.jm',
          roles: ['ODPEM_LOGISTICS_MANAGER'],
          memberships: [
            {
              tenant_id: 2,
              tenant_code: 'ODPEM-NEOC',
              tenant_name: 'ODPEM NEOC',
              tenant_type: 'NEOC',
              is_primary: true,
              access_level: 'FULL',
            },
          ],
        },
        {
          user_id: '91',
          username: 'relief_jrc_requester_tst',
          email: 'alicia.bennett+jrc.requester@agency.example.org',
          roles: ['AGENCY_DISTRIBUTOR'],
          memberships: [
            {
              tenant_id: 19,
              tenant_code: 'JRC',
              tenant_name: 'Jamaica Red Cross',
              tenant_type: 'NGO',
              is_primary: true,
              access_level: 'FULL',
            },
          ],
        },
      ],
    });
    fixture.detectChanges();

    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.dev-user-label')?.textContent).toContain('Local test mode');
    const select = compiled.querySelector('#dev-user-select') as HTMLSelectElement | null;
    expect(select).not.toBeNull();
    expect(select?.options[0].textContent).toContain('local_system_admin_tst');
    expect(select?.options[1].textContent).toContain('ODPEM_DDG');
    expect(select?.options[1].textContent).toContain('ODPEM-NEOC');
    expect(select?.options[2].textContent).toContain('ODPEM_LOGISTICS_MANAGER');
    expect(select?.options[2].textContent).toContain('ODPEM-NEOC');
    expect(select?.options[3].textContent).toContain('AGENCY_DISTRIBUTOR');
    expect(select?.options[3].textContent).toContain('JRC');
  });
});

function flushInitialRequests(httpMock: HttpTestingController): void {
  httpMock.expectOne('/api/v1/auth/whoami/').flush({
    user_id: '27',
    username: 'local_system_admin_tst',
    roles: ['SYSTEM_ADMINISTRATOR'],
    permissions: ['masterdata.view'],
  });
  httpMock.expectOne('/api/v1/auth/local-harness/').flush({ enabled: false });
}
