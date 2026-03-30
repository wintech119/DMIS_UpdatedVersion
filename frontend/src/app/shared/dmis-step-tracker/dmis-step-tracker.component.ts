import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  computed,
  ElementRef,
  inject,
  input,
  NgZone,
  OnDestroy,
  output,
  signal,
  ViewChild,
} from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

export interface StepDefinition {
  label: string;
  /**
   * Controls whether a step before the active index is treated as completed.
   * When omitted, prior steps default to completed in the tracker. Set this to
   * false to keep an earlier step incomplete in linear flows.
   */
  completed?: boolean;
  disabled?: boolean;
}

export interface ResolvedStep extends StepDefinition {
  state: 'completed' | 'active' | 'future';
  index: number;
}

@Component({
  selector: 'dmis-step-tracker',
  standalone: true,
  imports: [MatIconModule],
  templateUrl: './dmis-step-tracker.component.html',
  styleUrl: './dmis-step-tracker.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DmisStepTrackerComponent implements AfterViewInit, OnDestroy {
  private zone = inject(NgZone);

  /** Ordered list of step definitions. */
  steps = input.required<StepDefinition[]>();

  /** Zero-based index of the currently active step. */
  activeIndex = input.required<number>();

  /** When true, only completed and active steps are clickable. */
  linear = input(true);

  /** Emits the index of the step the user clicked. */
  stepClick = output<number>();

  @ViewChild('scrollContainer')
  scrollContainer!: ElementRef<HTMLElement>;

  canScrollLeft = signal(false);
  canScrollRight = signal(false);

  private resizeObserver: ResizeObserver | null = null;

  // Prior steps default to completed unless callers explicitly set completed: false.
  // That keeps existing trackers concise, but linear flows should opt out when a
  // previous step must remain incomplete for navigation and accessibility.
  resolvedSteps = computed<ResolvedStep[]>(() => {
    const allSteps = this.steps();
    const active = this.activeIndex();

    return allSteps.map((step, index) => {
      let state: ResolvedStep['state'];

      if (index < active) {
        // Steps before activeIndex default to completed unless explicitly marked otherwise
        state = step.completed === false ? 'future' : 'completed';
      } else if (index === active) {
        state = 'active';
      } else {
        state = 'future';
      }

      return { ...step, state, index };
    });
  });

  progressPercent = computed(() => {
    const total = this.steps().length;
    const active = this.activeIndex();
    return Math.round((active / Math.max(total - 1, 1)) * 100);
  });

  ngAfterViewInit(): void {
    this.zone.runOutsideAngular(() => {
      const container = this.scrollContainer.nativeElement;

      this.resizeObserver = new ResizeObserver(() => {
        this.updateScrollFlags();
      });
      this.resizeObserver.observe(container);

      // Initial check
      this.updateScrollFlags();
    });
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
  }

  onScroll(): void {
    this.updateScrollFlags();
  }

  scrollLeft(): void {
    this.scrollContainer.nativeElement.scrollBy({ left: -200, behavior: 'smooth' });
  }

  scrollRight(): void {
    this.scrollContainer.nativeElement.scrollBy({ left: 200, behavior: 'smooth' });
  }

  onStepClick(index: number): void {
    const resolved = this.resolvedSteps();
    const step = resolved[index];
    if (!step) return;
    if (step.disabled) return;

    if (this.linear()) {
      // In linear mode, only completed or active steps are clickable
      if (step.state !== 'completed' && step.state !== 'active') {
        return;
      }
    }

    this.stepClick.emit(index);
  }

  isAriaDisabled(step: ResolvedStep): boolean {
    return !!step.disabled || (this.linear() && step.state === 'future');
  }

  onKeydown(event: KeyboardEvent, index: number): void {
    const resolved = this.resolvedSteps();
    const pills = this.scrollContainer?.nativeElement?.querySelectorAll<HTMLElement>(
      '.tracker__pill',
    );
    if (!pills?.length) return;

    let targetIndex: number | null = null;

    switch (event.key) {
      case 'ArrowRight':
        event.preventDefault();
        targetIndex = Math.min(index + 1, resolved.length - 1);
        break;

      case 'ArrowLeft':
        event.preventDefault();
        targetIndex = Math.max(index - 1, 0);
        break;

      case 'Home':
        event.preventDefault();
        targetIndex = 0;
        break;

      case 'End':
        event.preventDefault();
        targetIndex = resolved.length - 1;
        break;

      case 'Enter':
      case ' ':
        event.preventDefault();
        this.onStepClick(index);
        return;

      default:
        return;
    }

    if (targetIndex !== null && pills[targetIndex]) {
      pills[targetIndex].focus();
    }
  }

  private updateScrollFlags(): void {
    const el = this.scrollContainer?.nativeElement;
    if (!el) return;

    const left = el.scrollLeft > 0;
    const right = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;

    this.zone.run(() => {
      this.canScrollLeft.set(left);
      this.canScrollRight.set(right);
    });
  }
}
