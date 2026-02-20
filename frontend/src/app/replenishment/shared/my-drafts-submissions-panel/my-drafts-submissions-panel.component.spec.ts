import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { NeedsListSummary, NeedsListSummaryStatus } from '../../models/needs-list.model';
import { MyDraftsSubmissionsPanelComponent } from './my-drafts-submissions-panel.component';

describe('MyDraftsSubmissionsPanelComponent', () => {
  let fixture: ComponentFixture<MyDraftsSubmissionsPanelComponent>;
  let component: MyDraftsSubmissionsPanelComponent;
  let router: jasmine.SpyObj<Router>;

  function createSummary(status: NeedsListSummaryStatus): NeedsListSummary {
    return {
      id: 'NL-1',
      reference_number: 'NL-1',
      warehouse: { id: 1, name: 'Warehouse 1', code: '1' },
      event: { id: 1, name: 'Event 1', phase: 'SURGE' },
      status,
      total_items: 1,
      fulfilled_items: 0,
      remaining_items: 1,
      horizon_summary: {
        horizon_a: { count: 0, estimated_value: 0 },
        horizon_b: { count: 0, estimated_value: 0 },
        horizon_c: { count: 0, estimated_value: 0 }
      },
      submitted_at: null,
      approved_at: null,
      last_updated_at: null,
      superseded_by_id: null,
      supersedes_id: null,
      has_external_updates: false,
      external_update_summary: [],
      created_by: { id: null, name: 'submitter' }
    };
  }

  beforeEach(async () => {
    router = jasmine.createSpyObj<Router>('Router', ['navigate']);

    await TestBed.configureTestingModule({
      imports: [MyDraftsSubmissionsPanelComponent],
      providers: [{ provide: Router, useValue: router }]
    }).overrideComponent(MyDraftsSubmissionsPanelComponent, {
      set: { template: '' }
    }).compileComponents();

    fixture = TestBed.createComponent(MyDraftsSubmissionsPanelComponent);
    component = fixture.componentInstance;
  });

  it('navigates to drafts including modified and returned statuses', () => {
    component.navigateToDrafts();

    expect(router.navigate).toHaveBeenCalledWith(['/replenishment/my-submissions'], {
      queryParams: { status: 'DRAFT,MODIFIED,RETURNED' }
    });
  });

  it('treats modified records as drafts', () => {
    fixture.componentRef.setInput('submissions', [createSummary('MODIFIED')]);
    fixture.detectChanges();

    expect(component.hasDrafts()).toBeTrue();
  });

  it('treats returned records as drafts', () => {
    fixture.componentRef.setInput('submissions', [createSummary('RETURNED')]);
    fixture.detectChanges();

    expect(component.hasDrafts()).toBeTrue();
  });

  it('groups returned records under drafts', () => {
    fixture.componentRef.setInput('submissions', [createSummary('RETURNED')]);
    fixture.detectChanges();

    expect(component.statusGroups()).toEqual([
      jasmine.objectContaining({ label: 'Drafts', count: 1 })
    ]);
  });
});
