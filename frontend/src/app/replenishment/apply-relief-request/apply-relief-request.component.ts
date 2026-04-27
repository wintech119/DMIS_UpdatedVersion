import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { take } from 'rxjs';

import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { RequestAuthorityPreviewResponse } from '../../operations/models/operations.model';
import { OperationsService } from '../../operations/services/operations.service';

@Component({
  selector: 'app-apply-relief-request',
  standalone: true,
  imports: [
    MatButtonModule,
    MatCardModule,
    MatIconModule,
    MatProgressBarModule,
  ],
  template: `
    <section class="ops-page-shell">
      <mat-card>
        @if (loading()) {
          <mat-progress-bar mode="indeterminate" />
          <mat-card-header>
            <mat-icon mat-card-avatar aria-hidden="true">assignment</mat-icon>
            <mat-card-title>Checking relief request authority</mat-card-title>
            <mat-card-subtitle>Needs list {{ sourceNeedsListId() ?? 'pending' }}</mat-card-subtitle>
          </mat-card-header>
        } @else if (preview(); as result) {
          <mat-card-header>
            <mat-icon mat-card-avatar aria-hidden="true">lock</mat-icon>
            <mat-card-title>Relief request cannot be created from this needs list</mat-card-title>
            <mat-card-subtitle>Needs list {{ sourceNeedsListId() }}</mat-card-subtitle>
          </mat-card-header>
          <mat-card-content>
            <p>Reason: {{ blockedReasonLabel(result.blocked_reason_code) }}</p>
            <p>Required authority tenant: {{ requiredAuthorityTenantLabel(result) }}</p>
          </mat-card-content>
          <mat-card-actions>
            <button mat-stroked-button type="button" (click)="goBack()">
              <mat-icon>arrow_back</mat-icon>
              Back to Needs List
            </button>
          </mat-card-actions>
        } @else {
          <mat-card-header>
            <mat-icon mat-card-avatar aria-hidden="true">error_outline</mat-icon>
            <mat-card-title>Authority preview unavailable</mat-card-title>
            <mat-card-subtitle>{{ errorMessage() }}</mat-card-subtitle>
          </mat-card-header>
          <mat-card-actions>
            <button mat-stroked-button type="button" (click)="goBack()">
              <mat-icon>arrow_back</mat-icon>
              Back to Needs List
            </button>
          </mat-card-actions>
        }
      </mat-card>
    </section>
  `,
  styleUrls: ['../../operations/operations-shell.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplyReliefRequestComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly operations = inject(OperationsService);

  readonly loading = signal(true);
  readonly preview = signal<RequestAuthorityPreviewResponse | null>(null);
  readonly errorMessage = signal<string | null>(null);
  readonly sourceNeedsListId = signal<number | null>(null);

  ngOnInit(): void {
    const sourceNeedsListId = Number(this.route.snapshot.paramMap.get('id'));
    if (!Number.isFinite(sourceNeedsListId) || sourceNeedsListId <= 0) {
      this.loading.set(false);
      this.errorMessage.set('Invalid needs list ID.');
      return;
    }

    this.sourceNeedsListId.set(sourceNeedsListId);
    this.operations.getRequestAuthorityPreview(sourceNeedsListId)
      .pipe(take(1))
      .subscribe({
        next: (preview) => this.handlePreview(preview, sourceNeedsListId),
        error: () => {
          this.loading.set(false);
          this.errorMessage.set('The authority pre-check could not be completed.');
        },
      });
  }

  goBack(): void {
    const sourceNeedsListId = this.sourceNeedsListId();
    if (sourceNeedsListId) {
      this.router.navigate(['/replenishment/needs-list', sourceNeedsListId, 'review']);
      return;
    }
    this.router.navigate(['/replenishment/needs-list-review']);
  }

  blockedReasonLabel(code: string | null): string {
    return BLOCKED_REASON_LABELS[code ?? ''] ?? 'Agency is outside your relief-request authority.';
  }

  requiredAuthorityTenantLabel(result: RequestAuthorityPreviewResponse): string {
    if (result.required_authority_tenant_name?.trim()) {
      return result.required_authority_tenant_name.trim();
    }
    return result.required_authority_tenant_id
      ? `Tenant ${result.required_authority_tenant_id}`
      : 'Not available';
  }

  private handlePreview(preview: RequestAuthorityPreviewResponse, sourceNeedsListId: number): void {
    this.loading.set(false);
    if (!preview.can_create) {
      this.preview.set(preview);
      return;
    }

    this.router.navigate(['/operations/relief-requests/new'], {
      state: {
        source_needs_list_id: sourceNeedsListId,
        beneficiary_tenant_id: preview.beneficiary_tenant_id,
        beneficiary_agency_id: preview.beneficiary_agency_id,
        suggested_event_id: preview.suggested_event_id,
        allowed_origin_modes: preview.allowed_origin_modes,
      },
    });
  }
}

const BLOCKED_REASON_LABELS: Record<string, string> = {
  odpem_replenishment_only_needs_list: 'ODPEM HQ needs lists are replenishment-only.',
  agency_out_of_scope: 'Agency is outside your relief-request authority.',
  escalation_required: 'A higher-level tenant must create this relief request.',
  self_request_disabled: 'Self-service relief requests are disabled for this tenant.',
};
