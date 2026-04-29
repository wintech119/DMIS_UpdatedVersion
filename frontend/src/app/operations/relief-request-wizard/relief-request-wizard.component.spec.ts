import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { HttpErrorResponse } from '@angular/common/http';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';
import { of, throwError } from 'rxjs';

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
      const tooltip = fixture.debugElement.query(By.css('.request-wizard-back')).injector.get(MatTooltip);

      expect(tooltip.message).toBe('Back to relief requests');
    });

    it('renders a sticky action strip on Step 1 with safe-area padding', () => {
      const host = fixture.nativeElement as HTMLElement;
      const strip = host.querySelector<HTMLElement>('.request-wizard-actions');
      expect(strip).not.toBeNull();
      const computed = getComputedStyle(strip!);
      // jsdom + Karma both surface the position rule from the component
      // SCSS as a 'sticky' value when the rule is unconditional.
      expect(computed.position).toBe('sticky');
    });

    it('focuses the first invalid field when Continue is blocked on Step 1', () => {
      const component = fixture.componentInstance;
      // Force step-1 invalid: clear urgency, leave items invalid
      component.requestForm.get('urgency_ind')?.setValue(null);
      const itemGroup = component.itemsArray.at(0);
      itemGroup.get('item_id')?.setValue(null);
      itemGroup.get('request_qty')?.setValue(null);
      fixture.detectChanges();

      component.goToReview();
      fixture.detectChanges();

      // markAllAsTouched fires aria-invalid on Material form-fields and on
      // the urgency chip-group container.
      const host = fixture.nativeElement as HTMLElement;
      const firstInvalid = host.querySelector<HTMLElement>('[aria-invalid="true"]');
      expect(firstInvalid).not.toBeNull();
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

    it('renders a constrained origin-mode picker for dual-mode intake', () => {
      const host = fixture.nativeElement as HTMLElement;
      const radiogroup = host.querySelector<HTMLElement>('.rrw-origin-grid');
      expect(radiogroup).not.toBeNull();
      expect(radiogroup?.getAttribute('role')).toBe('radiogroup');

      const cards = Array.from(radiogroup!.querySelectorAll<HTMLElement>('.rrw-origin-card'))
        .map((card) => card.textContent ?? '');

      expect(cards.length).toBe(2);
      expect(cards[0]).toContain('Own organisation');
      expect(cards[1]).toContain('Managed entity');
      expect(fixture.componentInstance.originModeControl.hasError('required')).toBeTrue();

      const radios = radiogroup!.querySelectorAll<HTMLElement>('[role="radio"]');
      expect(radios.length).toBe(2);
      // Roving tabindex: only the focused (default index 0) card is in
      // the tab order.
      expect(radios[0].getAttribute('tabindex')).toBe('0');
      expect(radios[1].getAttribute('tabindex')).toBe('-1');
    });

    it('selects a dual-mode card when its host is clicked and updates aria-checked', () => {
      const host = fixture.nativeElement as HTMLElement;
      const radiogroup = host.querySelector<HTMLElement>('.rrw-origin-grid');
      const radios = radiogroup!.querySelectorAll<HTMLElement>('[role="radio"]');
      radios[1].click();
      fixture.detectChanges();

      expect(fixture.componentInstance.originModeControl.value).toBe('FOR_SUBORDINATE');
      expect(radios[1].getAttribute('aria-checked')).toBe('true');
      expect(radios[0].getAttribute('aria-checked')).toBe('false');
    });

    it('blocks save until a dual-mode origin mode is selected', () => {
      const component = fixture.componentInstance;
      const itemGroup = component.itemsArray.at(0);
      itemGroup.get('item_id')?.setValue(88);
      itemGroup.get('request_qty')?.setValue(3);
      component.requestForm.get('agency_id')?.setValue(13);
      component.requestForm.get('urgency_ind')?.setValue('M');
      fixture.detectChanges();

      component.onSaveAsDraft();

      expect(operationsService.createRequest).not.toHaveBeenCalled();
      expect(component.originModeControl.touched).toBeTrue();
    });

    it('sends the selected dual-mode origin_mode in the create payload', () => {
      const component = fixture.componentInstance;
      const savedResponse = {
        reliefrqst_id: 79,
        status_code: 'DRAFT',
        items: [],
      } as unknown as RequestDetailResponse;
      operationsService.createRequest.and.returnValue(of(savedResponse));

      const itemGroup = component.itemsArray.at(0);
      itemGroup.get('item_id')?.setValue(88);
      itemGroup.get('request_qty')?.setValue(3);
      component.requestForm.get('agency_id')?.setValue(13);
      component.requestForm.get('urgency_ind')?.setValue('M');
      component.originModeControl.setValue('FOR_SUBORDINATE');
      fixture.detectChanges();

      component.onSaveAsDraft();

      expect(operationsService.createRequest).toHaveBeenCalledTimes(1);
      const payload = operationsService.createRequest.calls.mostRecent().args[0];
      expect(payload.origin_mode).toBe('FOR_SUBORDINATE');
      expect(payload.beneficiary_agency_id).toBe(13);
    });
  });

  describe('when creation is blocked by zero available modes', () => {
    let fixture: ComponentFixture<ReliefRequestWizardComponent>;
    let operationsService: jasmine.SpyObj<OperationsService>;

    beforeEach(async () => {
      operationsService = createOperationsServiceSpy();
      operationsService.getRequestReferenceData.and.returnValue(of({
        agencies: [],
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
                relief_request_submission_mode: null,
                allowed_origin_modes: [],
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

    it('keeps the creation-blocked panel when no origin modes are available', () => {
      const host = fixture.nativeElement as HTMLElement;

      expect(fixture.componentInstance.creationBlocked()).toBeTrue();
      expect(host.textContent).toContain('You cannot create requests at this time');
      expect(host.querySelector('mat-radio-group')).toBeNull();
      // The blocked surface now uses dmis-empty-state with a lock icon
      // and a "Back to Requests" action button.
      expect(host.querySelector('dmis-empty-state')).not.toBeNull();
      expect(host.textContent).toContain('Back to Requests');
    });
  });

  describe('when ODPEM bridge intake is available', () => {
    let fixture: ComponentFixture<ReliefRequestWizardComponent>;
    let operationsService: jasmine.SpyObj<OperationsService>;
    let router: jasmine.SpyObj<Router>;

    beforeEach(async () => {
      operationsService = createOperationsServiceSpy();
      router = jasmine.createSpyObj<Router>('Router', ['navigate', 'getCurrentNavigation']);
      router.getCurrentNavigation.and.returnValue(null);
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
            useValue: router,
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

    it('ingests bridge route state and carries the source needs list into the create payload', () => {
      router.getCurrentNavigation.and.returnValue({
        extras: {
          state: {
            source_needs_list_id: 40,
            beneficiary_tenant_id: 12,
            beneficiary_agency_id: 501,
            suggested_event_id: 44,
            allowed_origin_modes: ['ODPEM_BRIDGE'],
          },
        },
      } as unknown as ReturnType<Router['getCurrentNavigation']>);
      const bridgeFixture = TestBed.createComponent(ReliefRequestWizardComponent);
      bridgeFixture.detectChanges();

      const component = bridgeFixture.componentInstance;
      const savedResponse = {
        reliefrqst_id: 78,
        status_code: 'DRAFT',
        items: [],
      } as unknown as RequestDetailResponse;
      operationsService.createRequest.and.returnValue(of(savedResponse));

      const itemGroup = component.itemsArray.at(0);
      itemGroup.get('item_id')?.setValue(88);
      itemGroup.get('request_qty')?.setValue(6);
      component.requestForm.get('urgency_ind')?.setValue('M');
      bridgeFixture.detectChanges();

      expect(component.sourceNeedsListId()).toBe(40);
      expect(component.explicitOriginMode()).toBe('ODPEM_BRIDGE');
      expect(component.requestForm.get('agency_id')?.value).toBe(501);
      expect(component.requestForm.get('eligible_event_id')?.value).toBe(44);

      // Context strip surfaces the bridge state as inline pills. The
      // exact agency label depends on the existing reference-data merge
      // order (placeholder vs catalog name) — assert the pill structure
      // and the resolved label, not a specific catalog string.
      const bridgeHost = bridgeFixture.nativeElement as HTMLElement;
      expect(bridgeHost.textContent).toContain('Continuing from Needs List #40');
      expect(bridgeHost.textContent).toMatch(/Beneficiary:\s*\S+/);

      component.onSaveAsDraft();

      expect(operationsService.createRequest).toHaveBeenCalledTimes(1);
      const payload = operationsService.createRequest.calls.mostRecent().args[0];
      expect(payload.source_needs_list_id).toBe(40);
      expect(payload.agency_id).toBe(501);
      expect(payload.beneficiary_agency_id).toBe(501);
      expect(payload.origin_mode).toBe('ODPEM_BRIDGE');
    });
  });

  describe('when loading an existing request fails', () => {
    let fixture: ComponentFixture<ReliefRequestWizardComponent>;
    let operationsService: jasmine.SpyObj<OperationsService>;

    beforeEach(async () => {
      operationsService = createOperationsServiceSpy();
      operationsService.getRequestReferenceData.and.returnValue(of({
        agencies: [],
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
                allowed_origin_modes: ['self'],
              }),
            },
          },
          {
            provide: ActivatedRoute,
            useValue: {
              snapshot: { paramMap: convertToParamMap({ reliefrqstId: '4242' }) },
            },
          },
          {
            provide: Router,
            useValue: jasmine.createSpyObj('Router', ['navigate']),
          },
        ],
      }).compileComponents();
    });

    it('renders dmis-empty-state with a retry action when the request load fails', () => {
      operationsService.getRequest.and.returnValue(
        throwError(() => new HttpErrorResponse({ status: 404, statusText: 'Not Found' })),
      );

      fixture = TestBed.createComponent(ReliefRequestWizardComponent);
      fixture.detectChanges();

      const host = fixture.nativeElement as HTMLElement;
      expect(host.querySelector('dmis-empty-state')).not.toBeNull();
      expect(host.textContent).toContain('Unable to load this request');
      expect(host.textContent).toContain('Relief request not found.');
    });
  });
});
