import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';

import { NeedsListSummary, MySubmissionsResponse } from '../models/needs-list.model';
import { MySubmissionsComponent } from './my-submissions.component';
import { DmisNotificationService } from '../services/notification.service';
import { ReplenishmentService } from '../services/replenishment.service';
import { SubmissionSnapshotService } from '../services/submission-snapshot.service';

describe('MySubmissionsComponent', () => {
  let fixture: ComponentFixture<MySubmissionsComponent>;
  let component: MySubmissionsComponent;

  let replenishmentService: jasmine.SpyObj<ReplenishmentService>;
  let notifications: jasmine.SpyObj<DmisNotificationService>;
  let snapshotService: jasmine.SpyObj<SubmissionSnapshotService>;
  let router: jasmine.SpyObj<Router>;

  function createSubmission(index: number): NeedsListSummary {
    return {
      id: `NL-${index}`,
      reference_number: `REF-${index}`,
      warehouse: {
        id: 1,
        name: 'Central Warehouse',
        code: 'CW'
      },
      event: {
        id: 10,
        name: 'Storm',
        phase: 'SURGE'
      },
      selected_method: 'A',
      status: 'APPROVED',
      total_items: 5,
      fulfilled_items: 0,
      remaining_items: 5,
      horizon_summary: {
        horizon_a: { count: 1, estimated_value: 10 },
        horizon_b: { count: 1, estimated_value: 20 },
        horizon_c: { count: 1, estimated_value: 30 }
      },
      submitted_at: `2026-03-${String((index % 28) + 1).padStart(2, '0')}T12:00:00Z`,
      approved_at: null,
      last_updated_at: `2026-03-${String((index % 28) + 1).padStart(2, '0')}T13:00:00Z`,
      superseded_by_id: null,
      supersedes_id: null,
      has_external_updates: false,
      external_update_summary: [],
      created_by: {
        id: 99,
        name: 'Analyst'
      }
    };
  }

  function createResponse(results: NeedsListSummary[], count = results.length): MySubmissionsResponse {
    return {
      count,
      next: null,
      previous: null,
      results
    };
  }

  beforeEach(async () => {
    replenishmentService = jasmine.createSpyObj<ReplenishmentService>(
      'ReplenishmentService',
      ['getMySubmissions', 'bulkSubmitDrafts', 'bulkDeleteDrafts']
    );
    notifications = jasmine.createSpyObj<DmisNotificationService>(
      'DmisNotificationService',
      ['showError', 'showWarning', 'showSuccess']
    );
    snapshotService = jasmine.createSpyObj<SubmissionSnapshotService>(
      'SubmissionSnapshotService',
      ['detectChanges', 'markAsSeen']
    );
    router = jasmine.createSpyObj<Router>('Router', ['navigate']);

    snapshotService.detectChanges.and.returnValue(new Set<string>());

    await TestBed.configureTestingModule({
      imports: [MySubmissionsComponent],
      providers: [
        { provide: ReplenishmentService, useValue: replenishmentService },
        { provide: DmisNotificationService, useValue: notifications },
        { provide: SubmissionSnapshotService, useValue: snapshotService },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              queryParamMap: convertToParamMap({})
            }
          }
        }
      ]
    }).overrideComponent(MySubmissionsComponent, {
      set: { template: '' }
    }).compileComponents();
  });

  it('loads all backend pages before applying client-side filtering', () => {
    const firstPage = createResponse(
      Array.from({ length: 100 }, (_, index) => createSubmission(index + 1)),
      150
    );
    const secondPage = createResponse(
      Array.from({ length: 50 }, (_, index) => createSubmission(index + 101)),
      150
    );

    replenishmentService.getMySubmissions.and.returnValues(
      of(firstPage),
      of(secondPage)
    );

    fixture = TestBed.createComponent(MySubmissionsComponent);
    component = fixture.componentInstance;

    expect(replenishmentService.getMySubmissions.calls.count()).toBe(2);
    expect(replenishmentService.getMySubmissions.calls.argsFor(0)[0]).toEqual(
      jasmine.objectContaining({ page: 1, page_size: 100 })
    );
    expect(replenishmentService.getMySubmissions.calls.argsFor(1)[0]).toEqual(
      jasmine.objectContaining({ page: 2, page_size: 100 })
    );
    expect(component.allSubmissions().length).toBe(150);
    expect(component.filteredSubmissions().length).toBe(150);
    expect(component.totalCount()).toBe(150);
    expect(snapshotService.detectChanges).toHaveBeenCalledWith(component.allSubmissions());
  });

  it('does not request extra pages when the first page contains the full dataset', () => {
    const onlyPage = createResponse(
      Array.from({ length: 40 }, (_, index) => createSubmission(index + 1)),
      40
    );

    replenishmentService.getMySubmissions.and.returnValue(of(onlyPage));

    fixture = TestBed.createComponent(MySubmissionsComponent);
    component = fixture.componentInstance;

    expect(replenishmentService.getMySubmissions.calls.count()).toBe(1);
    expect(component.allSubmissions().length).toBe(40);
    expect(component.filteredSubmissions().length).toBe(40);
    expect(component.totalCount()).toBe(40);
  });
});
