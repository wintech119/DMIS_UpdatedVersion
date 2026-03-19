import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ActivatedRoute, Router } from '@angular/router';
import { Clipboard } from '@angular/cdk/clipboard';
import { MatDialog } from '@angular/material/dialog';
import { of } from 'rxjs';

import { MasterDetailPageComponent } from './master-detail-page.component';
import { MasterDataService } from '../../services/master-data.service';
import { MasterEditGateService } from '../../services/master-edit-gate.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { ReplenishmentService } from '../../../replenishment/services/replenishment.service';

describe('MasterDetailPageComponent', () => {
  function setup(
    routePath = 'events',
    record: Record<string, unknown> = {},
    pk = '14',
  ) {
    const masterDataService = jasmine.createSpyObj<MasterDataService>('MasterDataService', ['get', 'inactivate', 'activate']);
    const replenishmentService = jasmine.createSpyObj<ReplenishmentService>('ReplenishmentService', ['assignStorageLocation']);
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
        event_name: 'Kingston Floods',
        status_code: 'I',
        closed_date: '2026-03-15',
        reason_desc: 'Event closed after handover.',
        version_nbr: 2,
        ...record,
      },
      warnings: [],
    }));
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
        { provide: MatDialog, useValue: dialog },
        { provide: Clipboard, useValue: clipboard },
        { provide: MasterDataService, useValue: masterDataService },
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DmisNotificationService, useValue: notificationService },
      ],
    });

    const fixture = TestBed.createComponent(MasterDetailPageComponent);
    fixture.detectChanges();

    return {
      fixture,
      component: fixture.componentInstance,
      dialog,
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
    const { component, editGate, router } = setup('ifrc-item-references', {
      ifrc_item_ref_id: 77,
      reference_desc: 'Water purification tablet',
      status_code: 'A',
    }, '77');
    const editGateMarkSpy = spyOn(editGate, 'markDetailEditGatePassed').and.callThrough();

    component.onEdit();

    expect(editGateMarkSpy).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/master-data', 'ifrc-item-references', '77', 'edit']);
    expect(editGate.consumeGovernedEditWarningSkip()).toBeTrue();
  });
});
