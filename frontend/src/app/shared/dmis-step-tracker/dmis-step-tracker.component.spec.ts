import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import {
  DmisStepTrackerComponent,
  StepDefinition,
} from './dmis-step-tracker.component';

describe('DmisStepTrackerComponent', () => {
  let fixture: ComponentFixture<DmisStepTrackerComponent>;
  let component: DmisStepTrackerComponent;

  const threeSteps: StepDefinition[] = [
    { label: 'Scope' },
    { label: 'Preview' },
    { label: 'Submit' },
  ];

  function createComponent(
    steps: StepDefinition[],
    activeIndex: number,
    linear = true,
  ): void {
    fixture = TestBed.createComponent(DmisStepTrackerComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('steps', steps);
    fixture.componentRef.setInput('activeIndex', activeIndex);
    fixture.componentRef.setInput('linear', linear);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DmisStepTrackerComponent],
    }).compileComponents();
  });

  it('should create', () => {
    createComponent(threeSteps, 0);
    expect(component).toBeTruthy();
  });

  // ── resolvedSteps state derivation ────────────────────────────────

  describe('resolvedSteps', () => {
    it('marks the first step as active and the rest as future when activeIndex is 0', () => {
      createComponent(threeSteps, 0);
      const resolved = component.resolvedSteps();

      expect(resolved[0].state).toBe('active');
      expect(resolved[1].state).toBe('future');
      expect(resolved[2].state).toBe('future');
    });

    it('marks steps before activeIndex as completed and the active step correctly', () => {
      createComponent(threeSteps, 1);
      const resolved = component.resolvedSteps();

      expect(resolved[0].state).toBe('completed');
      expect(resolved[1].state).toBe('active');
      expect(resolved[2].state).toBe('future');
    });

    it('marks all prior steps as completed when activeIndex is the last step', () => {
      createComponent(threeSteps, 2);
      const resolved = component.resolvedSteps();

      expect(resolved[0].state).toBe('completed');
      expect(resolved[1].state).toBe('completed');
      expect(resolved[2].state).toBe('active');
    });

    it('respects completed=false override for a step before activeIndex', () => {
      const steps: StepDefinition[] = [
        { label: 'Scope', completed: false },
        { label: 'Preview' },
        { label: 'Submit' },
      ];
      createComponent(steps, 2);
      const resolved = component.resolvedSteps();

      expect(resolved[0].state).toBe('future');
      expect(resolved[1].state).toBe('completed');
      expect(resolved[2].state).toBe('active');
    });

    it('assigns correct index values to resolved steps', () => {
      createComponent(threeSteps, 0);
      const resolved = component.resolvedSteps();

      expect(resolved.map((s) => s.index)).toEqual([0, 1, 2]);
    });
  });

  // ── progressPercent ───────────────────────────────────────────────

  describe('progressPercent', () => {
    it('returns 0% when on the first step', () => {
      createComponent(threeSteps, 0);
      expect(component.progressPercent()).toBe(0);
    });

    it('returns 50% when on the middle step of 3', () => {
      createComponent(threeSteps, 1);
      expect(component.progressPercent()).toBe(50);
    });

    it('returns 100% when on the last step', () => {
      createComponent(threeSteps, 2);
      expect(component.progressPercent()).toBe(100);
    });

    it('handles a single step gracefully', () => {
      createComponent([{ label: 'Only' }], 0);
      expect(component.progressPercent()).toBe(0);
    });
  });

  // ── stepClick interaction ─────────────────────────────────────────

  describe('stepClick', () => {
    it('emits when a completed step is clicked in linear mode', () => {
      createComponent(threeSteps, 2);
      const emitted: number[] = [];
      component.stepClick.subscribe((idx: number) => emitted.push(idx));

      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));
      pills[0].nativeElement.click();

      expect(emitted).toEqual([0]);
    });

    it('emits when the active step is clicked', () => {
      createComponent(threeSteps, 1);
      const emitted: number[] = [];
      component.stepClick.subscribe((idx: number) => emitted.push(idx));

      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));
      pills[1].nativeElement.click();

      expect(emitted).toEqual([1]);
    });

    it('does NOT emit when a future step is clicked in linear mode', () => {
      createComponent(threeSteps, 0, true);
      const emitted: number[] = [];
      component.stepClick.subscribe((idx: number) => emitted.push(idx));

      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));
      pills[2].nativeElement.click();

      expect(emitted).toEqual([]);
    });

    it('emits when a future step is clicked in non-linear mode', () => {
      createComponent(threeSteps, 0, false);
      const emitted: number[] = [];
      component.stepClick.subscribe((idx: number) => emitted.push(idx));

      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));
      pills[2].nativeElement.click();

      expect(emitted).toEqual([2]);
    });

    it('does NOT emit when a disabled step is clicked', () => {
      const steps: StepDefinition[] = [
        { label: 'Scope' },
        { label: 'Preview', disabled: true },
        { label: 'Submit' },
      ];
      createComponent(steps, 0, false);
      const emitted: number[] = [];
      component.stepClick.subscribe((idx: number) => emitted.push(idx));

      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));
      pills[1].nativeElement.click();

      expect(emitted).toEqual([]);
    });
  });

  // ── Keyboard navigation ───────────────────────────────────────────

  describe('keyboard navigation', () => {
    it('ArrowRight moves focus to the next pill', () => {
      createComponent(threeSteps, 1);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      // Focus the active pill first
      pills[1].nativeElement.focus();

      const event = new KeyboardEvent('keydown', {
        key: 'ArrowRight',
        bubbles: true,
      });
      pills[1].nativeElement.dispatchEvent(event);

      expect(document.activeElement).toBe(pills[2].nativeElement);
    });

    it('ArrowLeft moves focus to the previous pill', () => {
      createComponent(threeSteps, 1);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      pills[1].nativeElement.focus();

      const event = new KeyboardEvent('keydown', {
        key: 'ArrowLeft',
        bubbles: true,
      });
      pills[1].nativeElement.dispatchEvent(event);

      expect(document.activeElement).toBe(pills[0].nativeElement);
    });

    it('ArrowRight does not go past the last pill', () => {
      createComponent(threeSteps, 2);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      pills[2].nativeElement.focus();

      const event = new KeyboardEvent('keydown', {
        key: 'ArrowRight',
        bubbles: true,
      });
      pills[2].nativeElement.dispatchEvent(event);

      expect(document.activeElement).toBe(pills[2].nativeElement);
    });

    it('ArrowLeft does not go before the first pill', () => {
      createComponent(threeSteps, 0);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      pills[0].nativeElement.focus();

      const event = new KeyboardEvent('keydown', {
        key: 'ArrowLeft',
        bubbles: true,
      });
      pills[0].nativeElement.dispatchEvent(event);

      expect(document.activeElement).toBe(pills[0].nativeElement);
    });

    it('Home moves focus to the first pill', () => {
      createComponent(threeSteps, 2);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      pills[2].nativeElement.focus();

      const event = new KeyboardEvent('keydown', {
        key: 'Home',
        bubbles: true,
      });
      pills[2].nativeElement.dispatchEvent(event);

      expect(document.activeElement).toBe(pills[0].nativeElement);
    });

    it('End moves focus to the last pill', () => {
      createComponent(threeSteps, 0);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      pills[0].nativeElement.focus();

      const event = new KeyboardEvent('keydown', {
        key: 'End',
        bubbles: true,
      });
      pills[0].nativeElement.dispatchEvent(event);

      expect(document.activeElement).toBe(pills[2].nativeElement);
    });

    it('Enter triggers stepClick for the focused step', () => {
      createComponent(threeSteps, 2);
      const emitted: number[] = [];
      component.stepClick.subscribe((idx: number) => emitted.push(idx));

      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));
      pills[0].nativeElement.focus();

      const event = new KeyboardEvent('keydown', {
        key: 'Enter',
        bubbles: true,
      });
      pills[0].nativeElement.dispatchEvent(event);

      expect(emitted).toEqual([0]);
    });

    it('Space triggers stepClick for the focused step', () => {
      createComponent(threeSteps, 2);
      const emitted: number[] = [];
      component.stepClick.subscribe((idx: number) => emitted.push(idx));

      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));
      pills[1].nativeElement.focus();

      const event = new KeyboardEvent('keydown', {
        key: ' ',
        bubbles: true,
      });
      pills[1].nativeElement.dispatchEvent(event);

      expect(emitted).toEqual([1]);
    });
  });

  // ── Template rendering ────────────────────────────────────────────

  describe('template rendering', () => {
    it('renders the correct number of pills', () => {
      createComponent(threeSteps, 0);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));
      expect(pills.length).toBe(3);
    });

    it('shows a check icon for completed steps', () => {
      createComponent(threeSteps, 2);
      const checkIcons = fixture.debugElement.queryAll(By.css('.tracker__check'));
      expect(checkIcons.length).toBe(2);
    });

    it('shows step numbers for non-completed steps', () => {
      createComponent(threeSteps, 0);
      const numbers = fixture.debugElement.queryAll(By.css('.tracker__number'));

      expect(numbers[0].nativeElement.textContent.trim()).toBe('1');
      expect(numbers[1].nativeElement.textContent.trim()).toBe('2');
      expect(numbers[2].nativeElement.textContent.trim()).toBe('3');
    });

    it('renders step labels', () => {
      createComponent(threeSteps, 0);
      const labels = fixture.debugElement.queryAll(By.css('.tracker__label'));

      expect(labels[0].nativeElement.textContent.trim()).toBe('Scope');
      expect(labels[1].nativeElement.textContent.trim()).toBe('Preview');
      expect(labels[2].nativeElement.textContent.trim()).toBe('Submit');
    });

    it('applies correct CSS classes based on step state', () => {
      createComponent(threeSteps, 1);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      expect(pills[0].nativeElement.classList.contains('tracker__pill--completed')).toBeTrue();
      expect(pills[1].nativeElement.classList.contains('tracker__pill--active')).toBeTrue();
      expect(pills[2].nativeElement.classList.contains('tracker__pill--future')).toBeTrue();
    });

    it('applies disabled CSS class for disabled steps', () => {
      const steps: StepDefinition[] = [
        { label: 'Scope' },
        { label: 'Preview', disabled: true },
        { label: 'Submit' },
      ];
      createComponent(steps, 0);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      expect(pills[1].nativeElement.classList.contains('tracker__pill--disabled')).toBeTrue();
    });

    it('sets aria-selected=true only on the active pill', () => {
      createComponent(threeSteps, 1);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      expect(pills[0].nativeElement.getAttribute('aria-selected')).toBe('false');
      expect(pills[1].nativeElement.getAttribute('aria-selected')).toBe('true');
      expect(pills[2].nativeElement.getAttribute('aria-selected')).toBe('false');
    });

    it('sets tabindex=0 only on the active pill', () => {
      createComponent(threeSteps, 1);
      const pills = fixture.debugElement.queryAll(By.css('.tracker__pill'));

      expect(pills[0].nativeElement.getAttribute('tabindex')).toBe('-1');
      expect(pills[1].nativeElement.getAttribute('tabindex')).toBe('0');
      expect(pills[2].nativeElement.getAttribute('tabindex')).toBe('-1');
    });

    it('renders the progress connector bar', () => {
      createComponent(threeSteps, 1);
      const fill = fixture.debugElement.query(By.css('.tracker__connector-fill'));
      expect(fill).toBeTruthy();
      expect(fill.nativeElement.style.width).toBe('50%');
    });

    it('renders a nav with correct aria-label', () => {
      createComponent(threeSteps, 0);
      const nav = fixture.debugElement.query(By.css('nav.tracker'));
      expect(nav.nativeElement.getAttribute('aria-label')).toBe('Wizard progress');
    });

    it('renders role=tablist on the pills container', () => {
      createComponent(threeSteps, 0);
      const container = fixture.debugElement.query(By.css('.tracker__pills'));
      expect(container.nativeElement.getAttribute('role')).toBe('tablist');
    });
  });
});
