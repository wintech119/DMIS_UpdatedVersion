import { TestBed } from '@angular/core/testing';

import { OpsStockAvailabilityStateComponent } from './ops-stock-availability-state.component';

describe('OpsStockAvailabilityStateComponent', () => {
  it('renders the request-level missing warehouse copy', async () => {
    await TestBed.configureTestingModule({
      imports: [OpsStockAvailabilityStateComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(OpsStockAvailabilityStateComponent);
    fixture.componentRef.setInput('kind', 'missing-warehouse');
    fixture.componentRef.setInput('scope', 'request');
    fixture.componentRef.setInput('detail', 'Source warehouse context is missing.');
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent.replace(/\s+/g, ' ').trim();
    expect(text).toContain('Warehouse setup is needed before stock can be reserved');
    expect(text).toContain('Request-level blocker');
    expect(text).toContain('Source warehouse context is missing.');
  });

  it('renders the item-level empty warehouse copy with remaining quantity', async () => {
    await TestBed.configureTestingModule({
      imports: [OpsStockAvailabilityStateComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(OpsStockAvailabilityStateComponent);
    fixture.componentRef.setInput('kind', 'no-candidates');
    fixture.componentRef.setInput('scope', 'item');
    fixture.componentRef.setInput('itemName', 'Portable Water Container');
    fixture.componentRef.setInput('remainingQty', 42);
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent.replace(/\s+/g, ' ').trim();
    expect(text).toContain('Portable Water Container is not stocked in an available warehouse');
    expect(text).toContain('Item-level blocker');
    expect(text).toContain('42');
  });
});
