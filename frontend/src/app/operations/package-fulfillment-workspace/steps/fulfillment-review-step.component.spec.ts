import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of } from 'rxjs';

import { FulfillmentReviewStepComponent } from './fulfillment-review-step.component';
import { MasterDataService } from '../../../master-data/services/master-data.service';
import { OperationsWorkspaceStateService } from '../../services/operations-workspace-state.service';

describe('FulfillmentReviewStepComponent — FR05.08 override actions', () => {
  beforeEach(async () => {
    const masterDataStub = { lookup: jasmine.createSpy('lookup').and.returnValue(of([])) };
    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, FulfillmentReviewStepComponent],
      providers: [
        { provide: MasterDataService, useValue: masterDataStub },
        OperationsWorkspaceStateService,
      ],
    }).compileComponents();
  });

  function createFixtureWithPendingOverride(canApprove: boolean) {
    const fixture = TestBed.createComponent(FulfillmentReviewStepComponent);
    const store = TestBed.inject(OperationsWorkspaceStateService);
    // Force hasPendingOverride() to return true by stubbing the signal property.
    (store as unknown as { hasPendingOverride: () => boolean }).hasPendingOverride = () => true;
    (store as unknown as { hasCommittedAllocation: () => boolean }).hasCommittedAllocation = () => false;
    fixture.componentInstance.canApproveOverride = canApprove;
    fixture.detectChanges();
    return fixture;
  }

  it('renders Approve, Return for Adjustments, and Reject when canApproveOverride is true', () => {
    const fixture = createFixtureWithPendingOverride(true);
    expect(fixture.debugElement.query(By.css('.ops-review-actions__btn--reject'))).not.toBeNull();
    expect(fixture.debugElement.query(By.css('.ops-review-actions__btn--return'))).not.toBeNull();
    expect(fixture.debugElement.query(By.css('.ops-review-actions__btn--approve'))).not.toBeNull();
  });

  it('keeps the DOM action order aligned with the intended visual order', () => {
    const fixture = createFixtureWithPendingOverride(true);
    const buttons = fixture.debugElement.queryAll(By.css('.ops-review-actions__btn'));

    expect(buttons[0].nativeElement.className).toContain('ops-review-actions__btn--approve');
    expect(buttons[1].nativeElement.className).toContain('ops-review-actions__btn--return');
    expect(buttons[2].nativeElement.className).toContain('ops-review-actions__btn--reject');
  });

  it('hides the three-action row when canApproveOverride is false', () => {
    const fixture = createFixtureWithPendingOverride(false);
    const footer = fixture.debugElement.query(By.css('.ops-review-actions'));
    expect(footer).toBeNull();
  });

  it('emits approveOverride / returnOverride / rejectOverride on click', () => {
    const fixture = createFixtureWithPendingOverride(true);
    const cmp = fixture.componentInstance;
    const approveSpy = spyOn(cmp.approveOverride, 'emit');
    const returnSpy = spyOn(cmp.returnOverride, 'emit');
    const rejectSpy = spyOn(cmp.rejectOverride, 'emit');

    fixture.debugElement.query(By.css('.ops-review-actions__btn--approve')).nativeElement.click();
    fixture.debugElement.query(By.css('.ops-review-actions__btn--return')).nativeElement.click();
    fixture.debugElement.query(By.css('.ops-review-actions__btn--reject')).nativeElement.click();

    expect(approveSpy).toHaveBeenCalledTimes(1);
    expect(returnSpy).toHaveBeenCalledTimes(1);
    expect(rejectSpy).toHaveBeenCalledTimes(1);
  });

  it('disables all three buttons while submitting', () => {
    const fixture = createFixtureWithPendingOverride(true);
    fixture.componentRef.setInput('submitting', true);
    fixture.detectChanges();
    const buttons = fixture.debugElement.queryAll(By.css('.ops-review-actions__btn'));
    for (const b of buttons) {
      expect((b.nativeElement as HTMLButtonElement).disabled).toBeTrue();
    }
  });
});
