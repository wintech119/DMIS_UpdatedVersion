import { TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { Router } from '@angular/router';
import { of } from 'rxjs';

import { OperationsTask, OperationsTaskListResponse } from '../models/operations.model';
import { OperationsService } from '../services/operations.service';
import { TaskCenterComponent } from './task-center.component';

describe('TaskCenterComponent', () => {
  const operationsService = jasmine.createSpyObj<OperationsService>('OperationsService', ['getTasks']);
  const router = jasmine.createSpyObj<Router>('Router', ['navigate', 'navigateByUrl']);

  function buildTask(overrides: Partial<OperationsTask> = {}): OperationsTask {
    return {
      id: 1,
      source: 'QUEUE_ASSIGNMENT',
      task_type: 'REVIEW_REQUEST',
      title: 'Review relief request',
      description: 'Relief request awaiting eligibility review.',
      status: 'PENDING',
      priority: 'H',
      related_entity_type: 'RELIEF_REQUEST',
      related_entity_id: 101,
      created_at: '2026-04-10T09:00:00Z',
      due_date: null,
      assigned_to: 'kemar.logistics',
      queue_code: 'ELIGIBILITY_REVIEW',
      ...overrides,
    };
  }

  function buildFeed(overrides: Partial<OperationsTaskListResponse> = {}): OperationsTaskListResponse {
    return {
      queue_assignments: [],
      notifications: [],
      results: [],
      ...overrides,
    };
  }

  beforeEach(async () => {
    operationsService.getTasks.calls.reset();
    router.navigate.calls.reset();
    router.navigateByUrl.calls.reset();

    operationsService.getTasks.and.returnValue(of(buildFeed()));

    await TestBed.configureTestingModule({
      imports: [NoopAnimationsModule, TaskCenterComponent],
      providers: [
        { provide: OperationsService, useValue: operationsService },
        { provide: Router, useValue: router },
      ],
    }).compileComponents();
  });

  it('sets the matching status filter when an interactive metric card is clicked', () => {
    operationsService.getTasks.and.returnValue(of(buildFeed({
      results: [
        buildTask({ id: 1, status: 'PENDING' }),
        buildTask({ id: 2, status: 'COMPLETED' }),
      ],
    })));

    const fixture = TestBed.createComponent(TaskCenterComponent);
    fixture.detectChanges();

    const host: HTMLElement = fixture.nativeElement;
    const cards = host.querySelectorAll<HTMLElement>('.ops-flow-strip__card--interactive');
    const openCard = Array.from(cards).find((card) => card.textContent?.includes('Open'));
    expect(openCard).toBeDefined();

    openCard!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    fixture.detectChanges();

    expect(fixture.componentInstance.activeFilter()).toBe('PENDING');
  });

  it('activates a metric card when Enter or Space is pressed on the focused element', () => {
    operationsService.getTasks.and.returnValue(of(buildFeed({
      results: [buildTask({ id: 3, status: 'COMPLETED' })],
    })));

    const fixture = TestBed.createComponent(TaskCenterComponent);
    fixture.detectChanges();

    const host: HTMLElement = fixture.nativeElement;
    const cards = host.querySelectorAll<HTMLElement>('.ops-flow-strip__card--interactive');
    const completedCard = Array.from(cards).find((card) => card.textContent?.includes('Completed'));
    expect(completedCard).toBeDefined();

    completedCard!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    fixture.detectChanges();
    expect(fixture.componentInstance.activeFilter()).toBe('COMPLETED');

    fixture.componentInstance.setFilter('all');
    fixture.detectChanges();

    completedCard!.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    fixture.detectChanges();
    expect(fixture.componentInstance.activeFilter()).toBe('COMPLETED');
  });

  it('marks the selected interactive metric tile as active', () => {
    operationsService.getTasks.and.returnValue(of(buildFeed({
      results: [
        buildTask({ id: 21, status: 'PENDING' }),
        buildTask({ id: 22, status: 'COMPLETED' }),
      ],
    })));

    const fixture = TestBed.createComponent(TaskCenterComponent);
    fixture.detectChanges();

    fixture.componentInstance.setFilter('PENDING');
    fixture.detectChanges();

    const openMetric = fixture.componentInstance.metricStrip().find((item) => item.label === 'Open');
    const completedMetric = fixture.componentInstance.metricStrip().find((item) => item.label === 'Completed');
    const assignmentsMetric = fixture.componentInstance.metricStrip().find((item) => item.label === 'Assignments');

    expect(openMetric?.active).toBeTrue();
    expect(completedMetric?.active).toBeFalse();
    expect(assignmentsMetric?.active).toBeFalse();
  });

  it('renders non-interactive cards for Assignments and Notifications summary counts', () => {
    operationsService.getTasks.and.returnValue(of(buildFeed({
      queue_assignments: [buildTask({ id: 10, source: 'QUEUE_ASSIGNMENT' })],
      notifications: [buildTask({ id: 11, source: 'NOTIFICATION' })],
      results: [buildTask({ id: 10 }), buildTask({ id: 11, status: 'COMPLETED' })],
    })));

    const fixture = TestBed.createComponent(TaskCenterComponent);
    fixture.detectChanges();

    const host: HTMLElement = fixture.nativeElement;
    const strip = host.querySelector<HTMLElement>('.ops-flow-strip');
    const cards = Array.from(host.querySelectorAll<HTMLElement>('.ops-flow-strip__card'));
    const assignmentsCard = cards.find((card) => card.textContent?.includes('Assignments'));
    const notificationsCard = cards.find((card) => card.textContent?.includes('Notifications'));

    expect(strip?.getAttribute('role')).toBe('group');
    expect(assignmentsCard).toBeDefined();
    expect(notificationsCard).toBeDefined();
    expect(assignmentsCard!.classList.contains('ops-flow-strip__card--interactive')).toBeFalse();
    expect(notificationsCard!.classList.contains('ops-flow-strip__card--interactive')).toBeFalse();
    expect(assignmentsCard!.getAttribute('role')).toBeNull();
    expect(notificationsCard!.getAttribute('role')).toBeNull();
  });
});
