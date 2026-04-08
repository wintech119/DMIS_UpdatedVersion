import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { OpsPackageLockStateComponent } from './ops-package-lock-state.component';
import { PackageLockConflict } from '../models/operations.model';

describe('OpsPackageLockStateComponent', () => {
  const BASE_CONFLICT: PackageLockConflict = {
    lock: 'Package is locked by another fulfillment actor.',
    lock_owner_user_id: 'kemar.logistics',
    lock_owner_role_code: 'LOGISTICS_MANAGER',
    lock_expires_at: '2026-04-07T16:00:00+00:00',
  };

  async function setUp(
    overrides: {
      conflict?: PackageLockConflict;
      currentUserRef?: string | null;
      currentUserRoles?: readonly string[];
    } = {},
  ): Promise<ComponentFixture<OpsPackageLockStateComponent>> {
    await TestBed.configureTestingModule({
      imports: [OpsPackageLockStateComponent],
    }).compileComponents();

    const fixture = TestBed.createComponent(OpsPackageLockStateComponent);
    fixture.componentRef.setInput('conflict', overrides.conflict ?? BASE_CONFLICT);
    fixture.componentRef.setInput('currentUserRef', overrides.currentUserRef ?? null);
    fixture.componentRef.setInput('currentUserRoles', overrides.currentUserRoles ?? []);
    fixture.detectChanges();
    return fixture;
  }

  function buttonTexts(fixture: ComponentFixture<OpsPackageLockStateComponent>): string[] {
    return fixture.debugElement
      .queryAll(By.css('button'))
      .map((el) => (el.nativeElement.textContent as string).replace(/\s+/g, ' ').trim());
  }

  it('renders "Release my lock" when the current user matches the lock owner', async () => {
    const fixture = await setUp({
      currentUserRef: 'kemar.logistics',
      currentUserRoles: ['LOGISTICS_OFFICER'],
    });

    const texts = buttonTexts(fixture);
    expect(texts.some((t) => t.includes('Release my lock'))).toBeTrue();
    expect(texts.some((t) => t.includes('Take over package'))).toBeFalse();
  });

  it('renders "Take over package" when a LOGISTICS_MANAGER is not the owner', async () => {
    const fixture = await setUp({
      currentUserRef: 'manager.one',
      currentUserRoles: ['LOGISTICS_MANAGER'],
    });

    const texts = buttonTexts(fixture);
    expect(texts.some((t) => t.includes('Take over package'))).toBeTrue();
    expect(texts.some((t) => t.includes('Release my lock'))).toBeFalse();
  });

  it('renders "Take over package" for SYSTEM_ADMINISTRATOR', async () => {
    const fixture = await setUp({
      currentUserRef: 'admin.one',
      currentUserRoles: ['SYSTEM_ADMINISTRATOR'],
    });

    const texts = buttonTexts(fixture);
    expect(texts.some((t) => t.includes('Take over package'))).toBeTrue();
  });

  it('renders "Take over package" for dev-mode TST_LOGISTICS_MANAGER', async () => {
    const fixture = await setUp({
      currentUserRef: 'kemar_tst',
      currentUserRoles: ['TST_LOGISTICS_MANAGER'],
    });

    const texts = buttonTexts(fixture);
    expect(texts.some((t) => t.includes('Take over package'))).toBeTrue();
  });

  it('renders "Take over package" for ODPEM_LOGISTICS_MANAGER', async () => {
    const fixture = await setUp({
      currentUserRef: 'manager.odpem',
      currentUserRoles: ['ODPEM_LOGISTICS_MANAGER'],
    });

    const texts = buttonTexts(fixture);
    expect(texts.some((t) => t.includes('Take over package'))).toBeTrue();
  });

  it('renders only Refresh for a non-owner without force-release roles', async () => {
    const fixture = await setUp({
      currentUserRef: 'officer.one',
      currentUserRoles: ['LOGISTICS_OFFICER'],
    });

    const texts = buttonTexts(fixture);
    expect(texts.some((t) => t.includes('Refresh'))).toBeTrue();
    expect(texts.some((t) => t.includes('Release my lock'))).toBeFalse();
    expect(texts.some((t) => t.includes('Take over package'))).toBeFalse();
  });

  it('shows "Not set" when lock_expires_at is null and does not throw', async () => {
    const fixture = await setUp({
      conflict: {
        ...BASE_CONFLICT,
        lock_expires_at: null,
      },
    });

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Not set');
  });

  it('shows an expired relative label for past timestamps', async () => {
    const pastIso = new Date(Date.now() - 10 * 60_000).toISOString();
    const fixture = await setUp({
      conflict: {
        ...BASE_CONFLICT,
        lock_expires_at: pastIso,
      },
    });

    const text = (fixture.nativeElement.textContent as string).toLowerCase();
    expect(text).toContain('expired');
  });

  it('shows an "in N min" relative label for future timestamps', async () => {
    const futureIso = new Date(Date.now() + 10 * 60_000).toISOString();
    const fixture = await setUp({
      conflict: {
        ...BASE_CONFLICT,
        lock_expires_at: futureIso,
      },
    });

    const text = fixture.nativeElement.textContent as string;
    expect(text).toMatch(/in \d+ min/);
  });

  it('uses a friendly role label for known role codes', async () => {
    const fixture = await setUp();
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Logistics Manager');
  });

  it('falls back to the raw code for unknown role codes', async () => {
    const fixture = await setUp({
      conflict: {
        ...BASE_CONFLICT,
        lock_owner_role_code: 'MYSTERY_ROLE',
      },
    });
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('MYSTERY_ROLE');
  });

  it('falls back to "Another fulfillment actor" when owner user id is missing', async () => {
    const fixture = await setUp({
      conflict: {
        ...BASE_CONFLICT,
        lock_owner_user_id: null,
      },
    });
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Another fulfillment actor');
  });
});
