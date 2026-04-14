import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';

import { DonationAllocationComponent } from './donation-allocation.component';
import { DonationsResponse } from '../models/needs-list.model';
import { DmisNotificationService } from '../services/notification.service';
import { ReplenishmentService } from '../services/replenishment.service';

describe('DonationAllocationComponent', () => {
  let fixture: ComponentFixture<DonationAllocationComponent>;
  let component: DonationAllocationComponent;

  let replenishmentService: jasmine.SpyObj<ReplenishmentService>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;
  let router: jasmine.SpyObj<Router>;

  beforeEach(async () => {
    replenishmentService = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      ['getDonations', 'exportDonationNeeds']
    );
    notifications = jasmine.createSpyObj<DmisNotificationService>(
      'DmisNotificationService',
      ['showError', 'showSuccess']
    );
    router = jasmine.createSpyObj<Router>('Router', ['navigate']);

    replenishmentService.getDonations.and.returnValue(of({
      needs_list_id: 'NL-1',
      lines: [
        {
          item_id: 200,
          item_name: 'Water',
          uom: 'EA',
          required_qty: 5,
          allocated_qty: 2,
          available_donations: [],
        },
      ],
    } satisfies DonationsResponse));
    replenishmentService.exportDonationNeeds.and.returnValue(of(new Blob(['csv'])));

    await TestBed.configureTestingModule({
      imports: [DonationAllocationComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DmisNotificationService, useValue: notifications },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: of(convertToParamMap({ id: 'NL-1' })),
          },
        },
      ],
    }).overrideComponent(DonationAllocationComponent, {
      set: { template: '' },
    }).compileComponents();

    fixture = TestBed.createComponent(DonationAllocationComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('downloads a queued export and shows success feedback', () => {
    const anchor = {
      click: jasmine.createSpy('click'),
      href: '',
      download: '',
    } as unknown as HTMLAnchorElement;
    const createElement = document.createElement.bind(document);
    spyOn(URL, 'createObjectURL').and.returnValue('blob:donation');
    spyOn(URL, 'revokeObjectURL');
    spyOn(document, 'createElement').and.callFake((tagName: string) => {
      if (tagName.toLowerCase() === 'a') {
        return anchor;
      }
      return createElement(tagName);
    });

    component.exportNeeds('csv');

    expect(replenishmentService.exportDonationNeeds).toHaveBeenCalledWith('NL-1', 'csv');
    expect(anchor.download).toBe('donation_needs_NL-1.csv');
    expect(anchor.click).toHaveBeenCalled();
    expect(notifications.showSuccess).toHaveBeenCalledWith('Donation needs exported as CSV.');
    expect(component.exporting()).toBeFalse();
  });
});
