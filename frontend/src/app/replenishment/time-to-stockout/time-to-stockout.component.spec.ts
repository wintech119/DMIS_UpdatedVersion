import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TimeToStockoutComponent } from './time-to-stockout.component';

describe('TimeToStockoutComponent', () => {
  let fixture: ComponentFixture<TimeToStockoutComponent>;
  let component: TimeToStockoutComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [TimeToStockoutComponent]
    }).compileComponents();

    fixture = TestBed.createComponent(TimeToStockoutComponent);
    component = fixture.componentInstance;
    component.data = {
      hours: 12,
      severity: 'WARNING',
      hasBurnRate: true
    };
  });

  it('applies compact mode as an explicit component contract', () => {
    component.compactMode = true;
    fixture.detectChanges();

    const container: HTMLElement | null = fixture.nativeElement.querySelector('.time-to-stockout-container');

    expect(container?.classList.contains('compact-mode')).toBeTrue();
  });
});
