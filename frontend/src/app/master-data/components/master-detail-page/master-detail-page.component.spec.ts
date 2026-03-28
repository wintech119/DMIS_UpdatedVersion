import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router } from '@angular/router';
import { Clipboard } from '@angular/cdk/clipboard';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { of } from 'rxjs';

import { MasterDetailPageComponent } from './master-detail-page.component';
import { MasterEditGateDialogComponent } from '../master-edit-gate-dialog/master-edit-gate-dialog.component';
import { CatalogEditGuidance } from '../../models/master-data.models';
import { MasterDataAccessService } from '../../services/master-data-access.service';
import { MasterDataService } from '../../services/master-data.service';
import { MasterEditGateService } from '../../services/master-edit-gate.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';

describe('MasterDetailPageComponent', () => {
  function setup(
    routePath = 'events',
    record: Record<string, unknown> = {},
    pk = '14',
    editGuidance: CatalogEditGuidance | null = null,
  ) {
    const masterDataService = jasmine.createSpyObj<MasterDataService>('MasterDataService', ['get', 'inactivate', 'activate', 'lookup']);
    const notificationService = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showSuccess',
      'showError',
      'showWarning',
    ]);
    const access = jasmine.createSpyObj<MasterDataAccessService>('MasterDataAccessService', [
      'canEditRoutePath',
      'canToggleStatusRoutePath',
    ]);
    const router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    const dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    const clipboard = jasmine.createSpyObj<Clipboard>('Clipboard', ['copy']);

    masterDataService.get.and.returnValue(of({
      record: {
        event_id: 14,
        item_id: 17,
        event_name: 'Kingston Floods',
        status_code: 'I',
        closed_date: '2026-03-15',
        reason_desc: 'Event closed after handover.',
        version_nbr: 2,
        ...record,
      },
      warnings: [],
      edit_guidance: editGuidance ?? undefined,
    }));
    masterDataService.lookup.and.callFake((tableKey: string) => {
      if (tableKey === 'uom') {
        return of([
          { value: 'EA', label: 'Each' },
          { value: 'BX', label: 'Box' },
          { value: 'CS', label: 'Case' },
        ]);
      }
      return of([]);
    });
    dialog.open.and.returnValue({ afterClosed: () => of(true) } as never);
    access.canEditRoutePath.and.returnValue(true);
    access.canToggleStatusRoutePath.and.returnValue(true);

    TestBed.configureTestingModule({
      imports: [MasterDetailPageComponent, NoopAnimationsModule],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: {
            data: of({ routePath }),
            params: of({ pk }),
          },
        },
        { provide: Router, useValue: router },
        { provide: Clipboard, useValue: clipboard },
        { provide: MasterDataAccessService, useValue: access },
        { provide: MasterDataService, useValue: masterDataService },
        { provide: DmisNotificationService, useValue: notificationService },
      ],
    });

    TestBed.overrideComponent(MasterDetailPageComponent, {
      remove: { imports: [MatDialogModule] },
      add: { providers: [{ provide: MatDialog, useValue: dialog }] },
    });

    const fixture = TestBed.createComponent(MasterDetailPageComponent);
    fixture.detectChanges();

    return {
      fixture,
      component: fixture.componentInstance,
      dialog,
      router,
      access,
      editGate: TestBed.inject(MasterEditGateService),
    };
  }

  it('keeps all configured Status fields in the dedicated status section', () => {
    const { component } = setup();

    expect(component.statusGroup()?.map((field) => field.field)).toEqual([
      'status_code',
      'closed_date',
      'reason_desc',
    ]);
  });

  it('marks the detail edit gate as passed before navigating to the edit form', () => {
    const { component, dialog, editGate, router, access } = setup('ifrc-item-references', {
      ifrc_item_ref_id: 77,
      reference_desc: 'Water purification tablet',
      status_code: 'A',
    }, '77', {
      warning_required: true,
      warning_text: 'Shared governed edit guidance.',
      locked_fields: ['ifrc_family_id', 'ifrc_code', 'category_code', 'spec_segment'],
      replacement_supported: true,
    });
    const editGateMarkSpy = spyOn(editGate, 'markDetailEditGatePassed').and.callThrough();

    component.onEdit();

    const openArgs = dialog.open.calls.mostRecent().args;
    const dialogConfig = openArgs[1] as {
      ariaLabelledBy?: string;
      data: {
        warningText?: string;
        lockedFields?: string[];
      };
    };

    expect(openArgs[0]).toBe(MasterEditGateDialogComponent);
    expect(dialogConfig.ariaLabelledBy).toBe('gate-dialog-title');
    expect(dialogConfig.data.warningText).toBe('Shared governed edit guidance.');
    expect(dialogConfig.data.lockedFields).toEqual(jasmine.arrayContaining([
      'IFRC Family',
      'IFRC Code',
      'Category Code',
      'Spec Segment',
    ]));
    expect(access.canEditRoutePath).toHaveBeenCalledWith('ifrc-item-references', false);
    expect(editGateMarkSpy).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'ifrc-item-references', '77', 'edit']);
    expect(editGate.consumeGovernedEditWarningSkip()).toBeTrue();
  });

  it('does not arm the governed-edit skip token for non-governed tables', () => {
    const { component, editGate, router } = setup('events');
    const editGateMarkSpy = spyOn(editGate, 'markDetailEditGatePassed').and.callThrough();

    component.onEdit();

    expect(editGateMarkSpy).not.toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'events', '14', 'edit']);
    expect(editGate.consumeGovernedEditWarningSkip()).toBeFalse();
  });

  it('only shows copy success feedback when the clipboard write succeeds', () => {
    const { component, fixture } = setup();
    const clipboard = TestBed.inject(Clipboard) as jasmine.SpyObj<Clipboard>;
    const notifications = TestBed.inject(DmisNotificationService) as jasmine.SpyObj<DmisNotificationService>;

    clipboard.copy.and.returnValue(false);
    component.copyValue('EVT-14');
    fixture.detectChanges();

    expect(notifications.showSuccess).not.toHaveBeenCalled();
  });

  it('displays UOM conversions when present in the item record', () => {
    const { fixture, component } = setup('items', {
      item_id: 17,
      item_name: 'Water Tabs',
      default_uom_code: 'EA',
      default_uom_desc: 'Each',
      status_code: 'A',
      uom_options: [
        { uom_code: 'EA', conversion_factor: 1, is_default: true, sort_order: 0, status_code: 'A' },
        { uom_code: 'BX', conversion_factor: 24, is_default: false, sort_order: 1, status_code: 'A' },
        { uom_code: 'CS', conversion_factor: 144, is_default: false, sort_order: 2, status_code: 'A' },
      ],
    }, '17');

    expect(component.itemUomConversions().length).toBe(3);

    const conversionsSection = fixture.nativeElement.querySelector('.detail-uom-conversions') as HTMLElement | null;
    expect(conversionsSection).toBeTruthy();
    expect(conversionsSection?.textContent).toContain('Each');
    expect(conversionsSection?.textContent).toContain('Box');
    expect(conversionsSection?.textContent).toContain('Case');
    expect(conversionsSection?.textContent).toContain('24');
    expect(conversionsSection?.textContent).toContain('144');
  });

  it('does not render storage assignment section on the detail page', () => {
    const { fixture } = setup('items', {
      item_id: 17,
      item_name: 'Water Tabs',
      status_code: 'A',
    }, '17');

    const assignmentSection = fixture.nativeElement.querySelector('.location-assignment-section') as HTMLElement | null;
    expect(assignmentSection).toBeNull();
  });
});
