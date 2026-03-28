import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';
import { of } from 'rxjs';

import { ReliefRequestWizardComponent } from './relief-request-wizard.component';
import { OperationsService } from '../services/operations.service';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';

describe('ReliefRequestWizardComponent', () => {
  let fixture: ComponentFixture<ReliefRequestWizardComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, ReliefRequestWizardComponent],
      providers: [
        {
          provide: OperationsService,
          useValue: jasmine.createSpyObj<OperationsService>('OperationsService', [
            'getRequestReferenceData',
            'getRequest',
            'createRequest',
            'updateRequest',
            'submitRequest',
          ]),
        },
        {
          provide: DmisNotificationService,
          useValue: jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
            'showError',
            'showWarning',
            'showSuccess',
          ]),
        },
        {
          provide: AuthRbacService,
          useValue: {
            load: jasmine.createSpy('load'),
            loaded: () => true,
            operationsCapabilities: () => ({
              can_create_relief_request: true,
              relief_request_submission_mode: 'self',
            }),
          },
        },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap: convertToParamMap({}),
            },
          },
        },
        {
          provide: Router,
          useValue: jasmine.createSpyObj('Router', ['navigate']),
        },
      ],
    }).compileComponents();

    const operationsService = TestBed.inject(OperationsService) as jasmine.SpyObj<OperationsService>;
    operationsService.getRequestReferenceData.and.returnValue(of({
      agencies: [{ value: 12, label: 'St. Mary Parish Council' }],
      events: [{ value: 44, label: 'Flood Response 2026' }],
      items: [{ value: 88, label: 'Tarps' }],
    }));

    fixture = TestBed.createComponent(ReliefRequestWizardComponent);
    fixture.detectChanges();
  });

  it('renders operations-specific header guidance instead of implementation-history copy', () => {
    const compiled = fixture.nativeElement as HTMLElement;

    expect(compiled.textContent).not.toContain('Stitch');
    expect(compiled.textContent).toContain('Create or update a relief request using the active request authority');
  });

  it('uses a destination-specific tooltip for the back button', () => {
    const tooltip = fixture.debugElement.query(By.css('.request-wizard-header__back')).injector.get(MatTooltip);

    expect(tooltip.message).toBe('Back to relief requests');
  });

  it('loads request reference data on init and applies the loaded options', () => {
    const operationsService = TestBed.inject(OperationsService) as jasmine.SpyObj<OperationsService>;

    expect(operationsService.getRequestReferenceData).toHaveBeenCalledTimes(1);
    expect(fixture.componentInstance.referenceLoading()).toBeFalse();
    expect(fixture.componentInstance.pageBusy()).toBeFalse();
    expect(fixture.componentInstance.agencyOptions()).toEqual([
      { value: 12, label: 'St. Mary Parish Council' },
    ]);
    expect(fixture.componentInstance.eventOptions()).toEqual([
      { value: 44, label: 'Flood Response 2026' },
    ]);
    expect(fixture.componentInstance.itemOptions()).toEqual([
      { value: 88, label: 'Tarps' },
    ]);
    expect(fixture.componentInstance.requestForm.get('agency_id')?.value).toBe(12);
  });

  it('updates the review snapshot with the selected event label', () => {
    const component = fixture.componentInstance;

    component.requestForm.get('eligible_event_id')?.setValue(44);
    fixture.detectChanges();

    expect(component.reviewFormValue().event_name).toBe('Flood Response 2026');
  });
});
