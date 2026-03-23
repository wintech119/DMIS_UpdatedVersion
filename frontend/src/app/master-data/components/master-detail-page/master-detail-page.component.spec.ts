import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router } from '@angular/router';
import { Clipboard } from '@angular/cdk/clipboard';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { of, Subject } from 'rxjs';

import { MasterDetailPageComponent } from './master-detail-page.component';
import { MasterEditGateDialogComponent } from '../master-edit-gate-dialog/master-edit-gate-dialog.component';
import { CatalogEditGuidance } from '../../models/master-data.models';
import { MasterDataService } from '../../services/master-data.service';
import { MasterEditGateService } from '../../services/master-edit-gate.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { ReplenishmentService } from '../../../replenishment/services/replenishment.service';

function buildStorageAssignmentOptions(overrides: Partial<{
  item_id: number;
  is_batched: boolean;
  inventories: { value: number; label: string; detail?: string }[];
  locations: { value: number; inventory_id: number; label: string; detail?: string }[];
  batches: { value: number; inventory_id: number; label: string; detail?: string }[];
}> = {}) {
  return {
    item_id: 17,
    is_batched: true,
    inventories: [
      { value: 1, label: 'Kingston Central Depot', detail: 'Internal inventory ID 1' },
      { value: 2, label: 'Montego Bay Hub', detail: 'Internal inventory ID 2' },
    ],
    locations: [
      { value: 11, inventory_id: 1, label: 'Rack A-01', detail: 'Internal location ID 11' },
      { value: 22, inventory_id: 2, label: 'Cold Room B-02', detail: 'Internal location ID 22' },
    ],
    batches: [
      { value: 101, inventory_id: 1, label: 'LOT-101 · Expires 2026-04-01', detail: 'Internal batch ID 101' },
      { value: 202, inventory_id: 2, label: 'LOT-202 · Expires 2026-05-15', detail: 'Internal batch ID 202' },
    ],
    ...overrides,
  };
}

describe('MasterDetailPageComponent', () => {
  function setup(
    routePath = 'events',
    record: Record<string, unknown> = {},
    pk = '14',
    editGuidance: CatalogEditGuidance | null = null,
  ) {
    const masterDataService = jasmine.createSpyObj<MasterDataService>('MasterDataService', ['get', 'inactivate', 'activate']);
    const replenishmentService = jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', [
      'assignStorageLocation',
      'getStorageAssignmentOptions',
    ]);
    const notificationService = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showSuccess',
      'showError',
      'showWarning',
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
    replenishmentService.getStorageAssignmentOptions.and.returnValue(of(buildStorageAssignmentOptions()));
    dialog.open.and.returnValue({ afterClosed: () => of(true) } as never);

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
        { provide: MasterDataService, useValue: masterDataService },
        { provide: ReplenishmentService, useValue: replenishmentService },
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
      replenishmentService,
      router,
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
    const { component, dialog, editGate, router } = setup('ifrc-item-references', {
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

  it('shows warehouse-friendly storage assignment options for item records', () => {
    const { fixture } = setup('items', {
      item_id: 17,
      item_name: 'Water Tabs',
      is_batched_flag: true,
      status_code: 'A',
    }, '17');

    const assignmentSection = fixture.nativeElement.querySelector('.location-assignment-section') as HTMLElement | null;

    expect(assignmentSection?.textContent).toContain('Kingston Central Depot');
    expect(assignmentSection?.textContent).not.toContain('Inventory ID');
  });

  it('ignores stale storage-assignment option responses after a newer detail request starts', () => {
    const { component, replenishmentService } = setup('items', {
      item_id: 17,
      item_name: 'Water Tabs',
      is_batched_flag: true,
      status_code: 'A',
    }, '17');
    const firstResponse$ = new Subject<ReturnType<typeof buildStorageAssignmentOptions>>();
    const secondResponse$ = new Subject<ReturnType<typeof buildStorageAssignmentOptions>>();
    const testAccess = component as unknown as {
      loadStorageAssignmentOptions(itemId: number | null): void;
    };

    replenishmentService.getStorageAssignmentOptions.and.returnValues(
      firstResponse$.asObservable(),
      secondResponse$.asObservable(),
    );

    testAccess.loadStorageAssignmentOptions(17);
    testAccess.loadStorageAssignmentOptions(18);

    secondResponse$.next(buildStorageAssignmentOptions({
      item_id: 18,
      inventories: [{ value: 18, label: 'Shelter Warehouse', detail: 'Internal inventory ID 18' }],
      locations: [{ value: 181, inventory_id: 18, label: 'Zone S-01', detail: 'Internal location ID 181' }],
      batches: [{ value: 1801, inventory_id: 18, label: 'LOT-1801 · Expires 2026-06-01', detail: 'Internal batch ID 1801' }],
    }));

    expect(component.storageAssignmentOptions()?.item_id).toBe(18);
    expect(component.inventoryAssignmentOptions().map((option) => option.label)).toEqual(['Shelter Warehouse']);
    expect(component.storageAssignmentLoading()).toBeFalse();

    firstResponse$.next(buildStorageAssignmentOptions({
      item_id: 17,
      inventories: [{ value: 17, label: 'Stale Warehouse', detail: 'Internal inventory ID 17' }],
      locations: [{ value: 171, inventory_id: 17, label: 'Stale Location', detail: 'Internal location ID 171' }],
      batches: [{ value: 1701, inventory_id: 17, label: 'LOT-1701 · Expires 2026-05-01', detail: 'Internal batch ID 1701' }],
    }));

    expect(component.storageAssignmentOptions()?.item_id).toBe(18);
    expect(component.inventoryAssignmentOptions().map((option) => option.label)).toEqual(['Shelter Warehouse']);
    expect(component.storageAssignmentLoading()).toBeFalse();
  });
});
