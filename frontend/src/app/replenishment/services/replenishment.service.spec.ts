import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { fakeAsync, TestBed, tick } from '@angular/core/testing';

import { ReplenishmentService } from './replenishment.service';
import { AsyncJobResponse, QueuedNeedsListExportResponse } from '../models/needs-list.model';

describe('ReplenishmentService async exports', () => {
  let service: ReplenishmentService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ReplenishmentService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });

    service = TestBed.inject(ReplenishmentService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('queues, polls, and downloads donation exports', fakeAsync(() => {
    let exportedBlob: Blob | undefined;

    service.exportDonationNeeds('NL-1').subscribe((blob) => {
      exportedBlob = blob;
    });

    const queueRequest = httpMock.expectOne('/api/v1/replenishment/needs-list/NL-1/donations/export');
    expect(queueRequest.request.method).toBe('POST');
    expect(queueRequest.request.body).toEqual({ format: 'csv' });
    queueRequest.flush(buildQueuedExport('job-1'));
    tick();

    const runningStatus = httpMock.expectOne('/api/v1/jobs/job-1');
    expect(runningStatus.request.method).toBe('GET');
    runningStatus.flush(buildAsyncJob('job-1', 'RUNNING'));

    tick(2000);

    const succeededStatus = httpMock.expectOne('/api/v1/jobs/job-1');
    succeededStatus.flush(buildAsyncJob('job-1', 'SUCCEEDED', { artifact_ready: true }));

    const downloadRequest = httpMock.expectOne('/api/v1/jobs/job-1/download');
    expect(downloadRequest.request.method).toBe('GET');
    downloadRequest.flush(new Blob(['item_id,item_name\n1,Water\n'], { type: 'text/csv' }));

    tick();

    expect(exportedBlob).toEqual(jasmine.any(Blob));
  }));

  it('surfaces failed job references from queued export polling', fakeAsync(() => {
    let exportError: Error | undefined;

    service.exportProcurementNeeds('NL-2').subscribe({
      next: () => fail('expected export to fail'),
      error: (error: Error) => {
        exportError = error;
      },
    });

    const queueRequest = httpMock.expectOne('/api/v1/replenishment/needs-list/NL-2/procurement/export');
    queueRequest.flush(buildQueuedExport('job-2', { job_type: 'needs_list_procurement_export' }));
    tick();

    const failedStatus = httpMock.expectOne('/api/v1/jobs/job-2');
    failedStatus.flush(
      buildAsyncJob('job-2', 'FAILED', {
        job_type: 'needs_list_procurement_export',
        error_message: 'artifact generation failed',
      })
    );

    tick();

    expect(exportError).toEqual(jasmine.any(Error));
    expect(exportError?.message).toContain('job-2');
    expect(exportError?.message).toContain('artifact generation failed');
  }));

  it('times out when a queued export never reaches a terminal state', fakeAsync(() => {
    let exportError: Error | undefined;

    service.waitForAsyncJob('job-3', 5000, 1000).subscribe({
      next: () => fail('expected waitForAsyncJob to time out'),
      error: (error: Error) => {
        exportError = error;
      },
    });
    tick();

    const runningStatus = httpMock.expectOne('/api/v1/jobs/job-3');
    runningStatus.flush(buildAsyncJob('job-3', 'RUNNING'));

    tick(1000);

    expect(exportError).toEqual(jasmine.any(Error));
    expect(exportError?.message).toContain('job-3');
    expect(exportError?.message).toContain('did not finish within 60 seconds');
  }));
});

function buildQueuedExport(
  jobId: string,
  overrides: Partial<QueuedNeedsListExportResponse> = {}
): QueuedNeedsListExportResponse {
  return {
    needs_list_id: 'NL-1',
    format: 'csv',
    data_version: 'NL-1|2026-04-10T12:00:00Z|APPROVED',
    job_id: jobId,
    job_type: 'needs_list_donation_export',
    status: 'QUEUED',
    queued_at: '2026-04-10T12:00:00Z',
    started_at: null,
    finished_at: null,
    expires_at: null,
    retry_count: 0,
    max_retries: 3,
    error_message: null,
    artifact_ready: false,
    status_url: `/api/v1/jobs/${jobId}`,
    ...overrides,
  };
}

function buildAsyncJob(
  jobId: string,
  status: AsyncJobResponse['status'],
  overrides: Partial<AsyncJobResponse> = {}
): AsyncJobResponse {
  return {
    job_id: jobId,
    job_type: 'needs_list_donation_export',
    status,
    queued_at: '2026-04-10T12:00:00Z',
    started_at: status === 'QUEUED' ? null : '2026-04-10T12:00:01Z',
    finished_at: status === 'SUCCEEDED' || status === 'FAILED' ? '2026-04-10T12:00:05Z' : null,
    expires_at: status === 'SUCCEEDED' ? '2026-04-11T12:00:05Z' : null,
    retry_count: 0,
    max_retries: 3,
    error_message: null,
    artifact_ready: false,
    status_url: `/api/v1/jobs/${jobId}`,
    ...overrides,
  };
}
