import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';

import { AppAccessService } from '../../core/app-access.service';
import { OperationsService } from '../services/operations.service';
import { OperationsDashboardComponent } from './operations-dashboard.component';

describe('OperationsDashboardComponent', () => {
  const operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', [
    'listRequests',
    'getEligibilityQueue',
    'getPackagesQueue',
    'getDispatchQueue',
    'getTasks',
  ]);
  const appAccess = jasmine.createSpyObj<AppAccessService>('AppAccessService', ['canAccessNavKey']);
  const router = jasmine.createSpyObj<Router>('Router', ['navigateByUrl']);

  beforeEach(async () => {
    operationsService.listRequests.and.returnValue(of({ results: [] }));
    operationsService.getEligibilityQueue.and.returnValue(of({ results: [] }));
    operationsService.getPackagesQueue.and.returnValue(of({ results: [] }));
    operationsService.getDispatchQueue.and.returnValue(of({ results: [] }));
    operationsService.getTasks.and.returnValue(of({
      queue_assignments: [],
      notifications: [],
      results: [],
    }));
    appAccess.canAccessNavKey.and.callFake(() => true);

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, OperationsDashboardComponent],
      providers: [
        { provide: AppAccessService, useValue: appAccess },
        { provide: OperationsService, useValue: operationsService },
        { provide: Router, useValue: router },
      ],
    }).compileComponents();
  });

  afterEach(() => {
    operationsService.listRequests.calls.reset();
    operationsService.getEligibilityQueue.calls.reset();
    operationsService.getPackagesQueue.calls.reset();
    operationsService.getDispatchQueue.calls.reset();
    operationsService.getTasks.calls.reset();
    appAccess.canAccessNavKey.calls.reset();
    router.navigateByUrl.calls.reset();
  });

  it('shows an explicit auth-sensitive dashboard failure instead of an empty queue state', () => {
    operationsService.getPackagesQueue.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 403, statusText: 'Forbidden' })),
    );

    const fixture = TestBed.createComponent(OperationsDashboardComponent);
    fixture.detectChanges();
    fixture.detectChanges();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('backend denied one or more feeds');
    expect(element.textContent).toContain('does not look like an empty but successful dashboard');
    expect(element.textContent).not.toContain('The current queues are empty or the backend is unavailable.');
  });

  it('requests only the dashboard lanes available to the signed-in role', () => {
    appAccess.canAccessNavKey.and.callFake((accessKey: string) => (
      accessKey === 'operations.relief-requests' || accessKey === 'operations.tasks'
    ));

    const fixture = TestBed.createComponent(OperationsDashboardComponent);
    fixture.detectChanges();
    fixture.detectChanges();

    expect(operationsService.listRequests).toHaveBeenCalled();
    expect(operationsService.getTasks).toHaveBeenCalled();
    expect(operationsService.getEligibilityQueue).not.toHaveBeenCalled();
    expect(operationsService.getPackagesQueue).not.toHaveBeenCalled();
    expect(operationsService.getDispatchQueue).not.toHaveBeenCalled();

    const element = fixture.nativeElement as HTMLElement;
    expect(element.textContent).toContain('showing only the operations lanes available to your account');
    expect(element.textContent).toContain('Hidden lanes: eligibility review, package fulfillment, dispatch.');
    expect(element.textContent).toContain('Not available to your role.');
  });
});
