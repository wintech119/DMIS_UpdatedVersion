import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { of } from 'rxjs';

import { MasterFormDialogComponent } from './master-form-dialog.component';
import { MasterDataService } from '../../services/master-data.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { UOM_CONFIG } from '../../models/table-configs/uom.config';

describe('MasterFormDialogComponent', () => {
  function setup() {
    const dialogRef = jasmine.createSpyObj<MatDialogRef<MasterFormDialogComponent>>('MatDialogRef', ['close']);
    const masterDataService = jasmine.createSpyObj<MasterDataService>('MasterDataService', [
      'lookup',
      'get',
      'create',
      'update',
    ]);
    const notificationService = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showSuccess',
      'showError',
      'showWarning',
    ]);

    masterDataService.lookup.and.returnValue(of([]));
    masterDataService.create.and.returnValue(of({ record: { uom_code: 'EA' }, warnings: [] }));
    masterDataService.update.and.returnValue(of({ record: { uom_code: 'EA' }, warnings: [] }));

    TestBed.configureTestingModule({
      imports: [MasterFormDialogComponent, NoopAnimationsModule],
      providers: [
        { provide: MAT_DIALOG_DATA, useValue: { config: UOM_CONFIG, pk: null } },
        { provide: MatDialogRef, useValue: dialogRef },
        { provide: MasterDataService, useValue: masterDataService },
        { provide: DmisNotificationService, useValue: notificationService },
      ],
    });

    const fixture = TestBed.createComponent(MasterFormDialogComponent);
    fixture.detectChanges();

    return {
      fixture,
      dialogRef,
      masterDataService,
      notificationService,
    };
  }

  it('shows the approved UOM inline governance note in the dialog', () => {
    const { fixture } = setup();

    const note = fixture.nativeElement.querySelector('.governance-inline-note') as HTMLElement | null;

    expect(note).not.toBeNull();
    expect(note?.textContent).toContain('UOM is how stock is counted or issued in operations.');
    expect(note?.textContent).toContain('It may not match the IFRC product form.');
  });
});
