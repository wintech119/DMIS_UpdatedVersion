import { ComponentFixture, TestBed } from '@angular/core/testing';
import { EMPTY } from 'rxjs';
import { Router } from '@angular/router';

import { SidenavComponent } from './sidenav.component';

describe('SidenavComponent', () => {
  let fixture: ComponentFixture<SidenavComponent>;
  let component: SidenavComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SidenavComponent],
      providers: [
        {
          provide: Router,
          useValue: {
            url: '/replenishment/dashboard',
            events: EMPTY
          }
        }
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
});
