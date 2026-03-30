import { ComponentFixture, TestBed } from '@angular/core/testing';
import { EMPTY } from 'rxjs';
import { Router } from '@angular/router';

import { AppAccessService } from '../../core/app-access.service';
import { SidenavComponent } from './sidenav.component';
import { MasterDataAccessService } from '../../master-data/services/master-data-access.service';

describe('SidenavComponent', () => {
  let fixture: ComponentFixture<SidenavComponent>;
  let component: SidenavComponent;
  let appAccess: jasmine.SpyObj<AppAccessService>;
  let masterDataAccess: jasmine.SpyObj<MasterDataAccessService>;

  beforeEach(async () => {
    appAccess = jasmine.createSpyObj<AppAccessService>('AppAccessService', [
      'canAccessNavKey',
    ]);
    appAccess.canAccessNavKey.and.returnValue(true);
    masterDataAccess = jasmine.createSpyObj<MasterDataAccessService>('MasterDataAccessService', [
      'isSystemAdmin',
      'canAccessDomain',
    ]);
    masterDataAccess.isSystemAdmin.and.returnValue(true);
    masterDataAccess.canAccessDomain.and.returnValue(true);

    await TestBed.configureTestingModule({
      imports: [SidenavComponent],
      providers: [
        {
          provide: Router,
          useValue: {
            url: '/replenishment/dashboard',
            events: EMPTY
          }
        },
        { provide: AppAccessService, useValue: appAccess },
        { provide: MasterDataAccessService, useValue: masterDataAccess },
      ]
    }).overrideComponent(SidenavComponent, {
      set: { template: '' }
    }).compileComponents();

    fixture = TestBed.createComponent(SidenavComponent);
    component = fixture.componentInstance;
  });

  it('returns full tooltips for enabled and disabled menu groups', () => {
    expect(component.getGroupTooltip({ label: 'Stock Status Dashboard', icon: 'monitoring' })).toBe(
      'Stock Status Dashboard'
    );
    expect(component.getGroupTooltip({ label: 'Reports', icon: 'assessment', disabled: true })).toBe(
      'Reports (Coming Soon)'
    );
  });

  it('returns full tooltips for enabled and disabled child items', () => {
    expect(component.getChildTooltip({ label: 'My Drafts & Submissions', icon: 'assignment' })).toBe(
      'My Drafts & Submissions'
    );
    expect(component.getChildTooltip({ label: 'Donation Reports', icon: 'receipt_long', disabled: true })).toBe(
      'Donation Reports (Coming Soon)'
    );
  });

  it('filters master data menu items by the shared access policy', () => {
    masterDataAccess.canAccessDomain.and.callFake((domain) => domain === 'operational');

    const masterGroup = component.navSections
      .find((section) => section.sectionLabel === 'MANAGEMENT')
      ?.groups.find((group) => group.label === 'Master Data');

    expect(masterGroup).toBeDefined();
    if (!masterGroup) {
      throw new Error('Expected Master Data navigation group to exist.');
    }

    expect(component.visibleChildren(masterGroup).map((item) => item.label)).toEqual([
      'Operational Masters',
    ]);
  });

  it('filters replenishment and operations items through the shared nav access policy', () => {
    appAccess.canAccessNavKey.and.callFake((accessKey?: string) =>
      accessKey !== 'replenishment.review' && accessKey !== 'operations.dispatch'
    );

    const replenishmentGroup = component.navSections
      .find((section) => section.sectionLabel === 'REPLENISHMENT')
      ?.groups.find((group) => group.label === 'Supply Replenishment');
    const operationsGroup = component.navSections
      .find((section) => section.sectionLabel === 'OPERATIONS')
      ?.groups.find((group) => group.label === 'Operations');

    if (!replenishmentGroup || !operationsGroup) {
      throw new Error('Expected replenishment and operations navigation groups to exist.');
    }

    expect(component.visibleChildren(replenishmentGroup).map((item) => item.label)).toEqual([
      'Stock Status Dashboard',
      'My Drafts & Submissions',
      'Needs List Wizard',
    ]);
    expect(component.visibleChildren(operationsGroup).map((item) => item.label)).toEqual([
      'Dashboard',
      'Relief Requests',
      'Eligibility Review',
      'Package Fulfillment',
      'Task Center',
    ]);
  });
});
