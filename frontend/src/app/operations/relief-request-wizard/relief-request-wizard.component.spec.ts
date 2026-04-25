import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';
import { of } from 'rxjs';

import { ReliefRequestWizardComponent } from './relief-request-wizard.component';
import { OperationsService } from '../services/operations.service';
import { RequestDetailResponse } from '../models/operations.model';
import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { AuthRbacService } from '../../replenishment/services/auth-rbac.service';

function createOperationsServiceSpy(): jasmine.SpyObj<OperationsService> {
  return jasmine.createSpyObj<OperationsService>('OperationsService', [
    'getRequestReferenceData',
    'getRequest',
    'createRequest',
    'updateRequest',
    'submitRequest',
  ]);
}

describe('ReliefRequestWizardComponent', () => {
  describe('with self-only submission mode', () => {
    let fixture: ComponentFixture<ReliefRequestWizardComponent>;
    let operationsService: jasmine.SpyObj<OperationsService>;

    beforeEach(async () => {
      operationsService = createOperationsServiceSpy();

      await TestBed.configureTestingModule({
        imports: [NoopAnimationsModule, ReliefRequestWizardComponent],
        providers: [
          { provide: OperationsService, useValue: operationsService },
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
                allowed_origin_modes: ['self'],
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
      expect(compiled.textContent).toContain('Create or update a relief request by selecting the agency');
    });

    it('uses a destination-specific tooltip for the back button', () => {
      const tooltip = fixture.debugElement.query(By.css('.request-wizard-header__back')).injector.get(MatTooltip);

      expect(tooltip.message).toBe('Back to relief requests');
    });

    it('loads request reference data on init and applies the loaded options', () => {
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

    it('requires request notes when overall urgency is High', () => {
      const component = fixture.componentInstance;
      const notes = component.requestForm.get('rqst_notes_text')!;

      component.requestForm.get('urgency_ind')?.setValue('H');
      fixture.detectChanges();

      expect(notes.hasError('required')).toBeTrue();

      notes.setValue('Shelter capacity breached; population of 400 without cover.');
      fixture.detectChanges();

      expect(notes.hasError('required')).toBeFalse();
    });

    it('preserves the 500-character request-notes limit when urgency toggles validators', () => {
      const component = fixture.componentInstance;
      const notes = component.requestForm.get('rqst_notes_text')!;

      notes.setValue('x'.repeat(501));
      fixture.detectChanges();
      expect(notes.hasError('maxlength')).toBeTrue();

      component.requestForm.get('urgency_ind')?.setValue('H');
      fixture.detectChanges();

      expect(notes.hasError('maxlength')).toBeTrue();
    });

    it('rejects whitespace-only notes as justification for high-urgency requests', () => {
      const component = fixture.componentInstance;
      const notes = component.requestForm.get('rqst_notes_text')!;
      const itemGroup = component.itemsArray.at(0);
      itemGroup.get('item_id')?.setValue(88);
      itemGroup.get('request_qty')?.setValue(4);
      component.requestForm.get('urgency_ind')?.setValue('H');
      notes.setValue('   ');
      fixture.detectChanges();

      expect(notes.hasError('required')).toBeTrue();
      expect(component.isStep1Valid()).toBeFalse();

      notes.setValue('Real justification text.');
      fixture.detectChanges();

      expect(notes.hasError('required')).toBeFalse();
      expect(component.isStep1Valid()).toBeTrue();
    });

    it('gates step-1 validity on request notes while urgency is High', () => {
      const component = fixture.componentInstance;
      const itemGroup = component.itemsArray.at(0);
      itemGroup.get('item_id')?.setValue(88);
      itemGroup.get('request_qty')?.setValue(5);
      component.requestForm.get('urgency_ind')?.setValue('H');
      fixture.detectChanges();

      expect(component.isStep1Valid()).toBeFalse();

      component.requestForm.get('rqst_notes_text')?.setValue('Critical shelter gap in zone 4.');
      fixture.detectChanges();

      expect(component.isStep1Valid()).toBeTrue();
    });

    it('drops the notes requirement when urgency is downgraded to Medium', () => {
      const component = fixture.componentInstance;
      const notes = component.requestForm.get('rqst_notes_text')!;

      component.requestForm.get('urgency_ind')?.setValue('H');
      fixture.detectChanges();
      expect(notes.hasError('required')).toBeTrue();

      component.requestForm.get('urgency_ind')?.setValue('M');
      fixture.detectChanges();

      expect(notes.hasError('required')).toBeFalse();
    });

    it('trims notes and item reason text before the create payload is dispatched', () => {
      const component = fixture.componentInstance;
      const savedResponse = {
        reliefrqst_id: 1,
        status_code: 'DRAFT',
        items: [],
      } as unknown as RequestDetailResponse;
      operationsService.createRequest.and.returnValue(of(savedResponse));

      const itemGroup = component.itemsArray.at(0);
      itemGroup.get('item_id')?.setValue(88);
      itemGroup.get('request_qty')?.setValue(3);
      itemGroup.get('rqst_reason_desc')?.setValue('  surge replenishment  ');
      component.requestForm.get('urgency_ind')?.setValue('M');
      component.requestForm.get('rqst_notes_text')?.setValue('   please expedite   ');
      fixture.detectChanges();

      component.onSaveAsDraft();

      expect(operationsService.createRequest).toHaveBeenCalledTimes(1);
      const payload = operationsService.createRequest.calls.mostRecent().args[0];
      expect(payload.rqst_notes_text).toBe('please expedite');
      expect(payload.items[0].rqst_reason_desc).toBe('surge replenishment');
    });

    it('recomputes step validity immediately after server control errors are applied', () => {
      const component = fixture.componentInstance;

      component.requestForm.get('urgency_ind')?.setValue('M');
      const itemGroup = component.itemsArray.at(0);
      itemGroup.get('item_id')?.setValue(88);
      itemGroup.get('request_qty')?.setValue(2);
      fixture.detectChanges();

      expect(component.isStep1Valid()).toBeTrue();

      (component as unknown as { handleSaveError: (err: HttpErrorResponse) => void }).handleSaveError(
        new HttpErrorResponse({
          error: {
            errors: {
              agency_id: ['Choose a valid agency.'],
            },
          },
        }),
      );
      fixture.detectChanges();

      expect(component.requestForm.get('agency_id')?.hasError('server')).toBeTrue();
      expect(component.isStep1Valid()).toBeFalse();
    });
  });

  describe('when dual-mode is available', () => {
    let fixture: ComponentFixture<ReliefRequestWizardComponent>;
    let operationsService: jasmine.SpyObj<OperationsService>;

    beforeEach(async () => {
      operationsService = createOperationsServiceSpy();
      operationsService.getRequestReferenceData.and.returnValue(of({
        agencies: [
          { value: 12, label: 'S07 TEST DISTRIBUTOR AGENCY - PARISH_KN' },
          { value: 13, label: 'S07 TEST DISTRIBUTOR AGENCY - FFP' },
        ],
        events: [],
        items: [],
      }));

      await TestBed.configureTestingModule({
        imports: [NoopAnimationsModule, ReliefRequestWizardComponent],
        providers: [
          { provide: OperationsService, useValue: operationsService },
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
                allowed_origin_modes: ['self', 'for_subordinate'],
              }),
            },
          },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { paramMap: convertToParamMap({}) },
            },
          },
          {
            provide: Router,
            useValue: jasmine.createSpyObj('Router', ['navigate']),
          },
        ],
      }).compileComponents();

      fixture = TestBed.createComponent(ReliefRequestWizardComponent);
      fixture.detectChanges();
    });

    it('shows dual-mode label when both self and for_subordinate modes are available', () => {
      expect(fixture.componentInstance.isDualMode()).toBeTrue();
      expect(fixture.componentInstance.explicitOriginMode()).toBeNull();
      expect(fixture.componentInstance.submissionModeLabel()).toBe('Your organisation or managed entity');
      expect(fixture.componentInstance.workflowLabel()).toBe('New request');
    });
  });

  describe('when ODPEM bridge intake is available', () => {
    let fixture: ComponentFixture<ReliefRequestWizardComponent>;
    let operationsService: jasmine.SpyObj<OperationsService>;

    beforeEach(async () => {
      operationsService = createOperationsServiceSpy();
      operationsService.getRequestReferenceData.and.returnValue(of({
        agencies: [{ value: 501, label: 'FFP Shelter' }],
        events: [{ value: 44, label: 'Flood Response 2026' }],
        items: [{ value: 88, label: 'Tarps' }],
      }));

      await TestBed.configureTestingModule({
        imports: [NoopAnimationsModule, ReliefRequestWizardComponent],
        providers: [
          { provide: OperationsService, useValue: operationsService },
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
                relief_request_submission_mode: 'on_behalf_bridge',
                allowed_origin_modes: ['on_behalf_bridge'],
              }),
            },
          },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { paramMap: convertToParamMap({}) },
            },
          },
          {
            provide: Router,
            useValue: jasmine.createSpyObj('Router', ['navigate']),
          },
        ],
      }).compileComponents();

      fixture = TestBed.createComponent(ReliefRequestWizardComponent);
      fixture.detectChanges();
    });

    it('labels intake as ODPEM-assisted while keeping the selected beneficiary agency in the payload', () => {
      const component = fixture.componentInstance;
      const compiled = fixture.nativeElement as HTMLElement;
      const savedResponse = {
        reliefrqst_id: 77,
        status_code: 'DRAFT',
        items: [],
      } as unknown as RequestDetailResponse;
      operationsService.createRequest.and.returnValue(of(savedResponse));

      const itemGroup = component.itemsArray.at(0);
      itemGroup.get('item_id')?.setValue(88);
      itemGroup.get('request_qty')?.setValue(6);
      component.requestForm.get('urgency_ind')?.setValue('M');
      fixture.detectChanges();

      expect(component.isDualMode()).toBeFalse();
      expect(component.explicitOriginMode()).toBe('ODPEM_BRIDGE');
      expect(component.requestingEntityLabel()).toBe('Represented requester');
      expect(component.submissionModeLabel()).toBe('ODPEM-assisted request');
      expect(component.submissionModeHint()).toContain('entering this request on their behalf');
      expect(component.workflowLabel()).toBe('New request (ODPEM-assisted)');
      expect(component.reviewFormValue().requester_label).toBe('Represented requester');
      expect(compiled.textContent).toContain('Represented requester');

      component.onSaveAsDraft();

      expect(operationsService.createRequest).toHaveBeenCalledTimes(1);
      const payload = operationsService.createRequest.calls.mostRecent().args[0];
      expect(payload.agency_id).toBe(501);
      expect(payload.beneficiary_agency_id).toBe(501);
      expect(payload.origin_mode).toBe('ODPEM_BRIDGE');
      expect(payload.items[0].item_id).toBe(88);
    });
  });
});
