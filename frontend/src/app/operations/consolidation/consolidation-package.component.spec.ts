import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { ActivatedRoute, ParamMap, Router, convertToParamMap } from '@angular/router';
import { Subject, of } from 'rxjs';

import { DmisNotificationService } from '../../replenishment/services/notification.service';
import { OperationsWorkspaceStateService } from '../services/operations-workspace-state.service';
import { ConsolidationPackageComponent } from './consolidation-package.component';

describe('ConsolidationPackageComponent', () => {
  let fixture: ComponentFixture<ConsolidationPackageComponent>;
  let component: ConsolidationPackageComponent;
  let paramMap$: Subject<ParamMap>;
  let router: jasmine.SpyObj<Router>;
  let dialog: jasmine.SpyObj<MatDialog>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;
  let state: {
    loadConsolidationLegs: jasmine.Spy;
    refreshConsolidationLegs: jasmine.Spy;
    requestPartialRelease: jasmine.Spy;
    approvePartialRelease: jasmine.Spy;
    reliefpkgId: ReturnType<typeof signal<number>>;
    reliefrqstId: ReturnType<typeof signal<number>>;
    packageDetail: ReturnType<typeof signal<unknown>>;
    consolidationLegs: ReturnType<typeof signal<unknown[]>>;
    legsLoading: ReturnType<typeof signal<boolean>>;
    legsError: ReturnType<typeof signal<string | null>>;
    parentSplitInfo: ReturnType<typeof signal<unknown>>;
    splitChildren: ReturnType<typeof signal<unknown[]>>;
    fulfillmentMode: ReturnType<typeof signal<string>>;
  };

  beforeEach(async () => {
    paramMap$ = new Subject<ParamMap>();
    router = jasmine.createSpyObj<Router>('Router', ['navigate']);
    dialog = jasmine.createSpyObj<MatDialog>('MatDialog', ['open']);
    notifications = jasmine.createSpyObj<DmisNotificationService>('DmisNotificationService', [
      'showSuccess',
      'showError',
    ]);
    state = {
      loadConsolidationLegs: jasmine.createSpy('loadConsolidationLegs'),
      refreshConsolidationLegs: jasmine.createSpy('refreshConsolidationLegs'),
      requestPartialRelease: jasmine.createSpy('requestPartialRelease').and.returnValue(
        of({ status: 'PARTIAL_RELEASE_REQUESTED', package: null }),
      ),
      approvePartialRelease: jasmine.createSpy('approvePartialRelease').and.returnValue(
        of({ parent: null, residual: null, released: null }),
      ),
      reliefpkgId: signal(90),
      reliefrqstId: signal(12),
      packageDetail: signal(null),
      consolidationLegs: signal([]),
      legsLoading: signal(false),
      legsError: signal<string | null>(null),
      parentSplitInfo: signal(null),
      splitChildren: signal([]),
      fulfillmentMode: signal('DIRECT'),
    };

    await TestBed.configureTestingModule({
      imports: [ConsolidationPackageComponent],
      providers: [
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: paramMap$.asObservable(),
            snapshot: { paramMap: convertToParamMap({ reliefpkgId: '0' }) },
          },
        },
        { provide: Router, useValue: router },
        { provide: MatDialog, useValue: dialog },
        { provide: DmisNotificationService, useValue: notifications },
        { provide: OperationsWorkspaceStateService, useValue: state },
      ],
    })
      .overrideComponent(ConsolidationPackageComponent, {
        set: { template: '' },
      })
      .compileComponents();

    fixture = TestBed.createComponent(ConsolidationPackageComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('reacts to reliefpkgId route changes without reloading the same id twice', () => {
    paramMap$.next(convertToParamMap({ reliefpkgId: '90' }));
    paramMap$.next(convertToParamMap({ reliefpkgId: '90' }));
    paramMap$.next(convertToParamMap({ reliefpkgId: '91' }));

    expect(state.loadConsolidationLegs.calls.allArgs()).toEqual([[90], [91]]);
  });

  it('does not trigger an extra consolidation refresh after partial approval succeeds', () => {
    dialog.open.and.returnValue({
      afterClosed: () => of({ reason: 'Approved for release' }),
    } as MatDialog['open'] extends (...args: never[]) => infer T ? T : never);

    component.onApprovePartial();

    expect(state.approvePartialRelease).toHaveBeenCalledWith({
      approval_reason: 'Approved for release',
    });
    expect(state.refreshConsolidationLegs).not.toHaveBeenCalled();
    expect(notifications.showSuccess).toHaveBeenCalledWith('Partial release approved.');
  });
});
