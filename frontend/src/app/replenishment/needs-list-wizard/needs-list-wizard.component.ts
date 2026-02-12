import { Component, OnInit, ViewChild, DestroyRef, ChangeDetectorRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatStepperModule, MatStepper } from '@angular/material/stepper';
import { StepperSelectionEvent } from '@angular/cdk/stepper';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatTooltipModule } from '@angular/material/tooltip';

import { WizardStateService } from './services/wizard-state.service';
import { ScopeStepComponent } from './steps/step1-scope/scope-step.component';
import { PreviewStepComponent } from './steps/step2-preview/preview-step.component';
import { SubmitStepComponent } from './steps/step3-submit/submit-step.component';

interface SubmitStepCompleteEvent {
  action: 'draft_saved' | 'submitted_for_approval';
  totalItems: number;
  completedAt: string;
  approver?: string;
}

interface WizardConfirmationState {
  action: 'draft_saved' | 'submitted_for_approval';
  totalItems: number;
  completedAt: string;
  approver?: string;
}

@Component({
  selector: 'app-needs-list-wizard',
  standalone: true,
  imports: [
    CommonModule,
    MatStepperModule,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatTooltipModule,
    ScopeStepComponent,
    PreviewStepComponent,
    SubmitStepComponent
  ],
  templateUrl: './needs-list-wizard.component.html',
  styleUrls: ['./needs-list-wizard.component.scss']
})
export class NeedsListWizardComponent implements OnInit {
  @ViewChild('stepper') stepper!: MatStepper;
  private destroyRef = inject(DestroyRef);
  private cdr = inject(ChangeDetectorRef);
  public wizardService = inject(WizardStateService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  readonly isStep1Valid$ = this.wizardService.isStep1Valid$();
  readonly isStep2Valid$ = this.wizardService.isStep2Valid$();
  confirmationState: WizardConfirmationState | null = null;

  ngOnInit(): void {
    // Load query params from dashboard navigation
    this.route.queryParams.pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(params => {
      if (params['event_id']) {
        // Convert single warehouse_id to array for multi-warehouse support
        const warehouseId = params['warehouse_id'];
        const warehouseIds = warehouseId ? [Number(warehouseId)] : [];

        this.wizardService.updateState({
          event_id: Number(params['event_id']),
          warehouse_ids: warehouseIds,
          phase: params['phase'] || 'BASELINE'
        });
      }
    });
  }

  backToDashboard(): void {
    // Confirm if user wants to abandon wizard
    const state = this.wizardService.getState();
    const hasData = state.event_id || (state.warehouse_ids && state.warehouse_ids.length > 0);

    if (hasData) {
      const confirmed = confirm('Are you sure you want to leave? Any unsaved changes will be lost.');
      if (!confirmed) {
        return;
      }
    }

    this.wizardService.reset();
    this.router.navigate(['/replenishment/dashboard']);
  }

  onStepChange(event: StepperSelectionEvent): void {
    // Track step changes for analytics
    console.log('Step changed:', event.selectedIndex);
  }

  onComplete(event: SubmitStepCompleteEvent): void {
    this.confirmationState = {
      action: event.action,
      totalItems: event.totalItems,
      completedAt: event.completedAt,
      approver: event.approver
    };

    // Force navigation to step 4 confirmation without requiring header click.
    this.cdr.detectChanges();
    queueMicrotask(() => {
      if (this.stepper) {
        this.stepper.selectedIndex = 3;
      }
    });
  }

  returnToDashboardFromConfirmation(): void {
    this.wizardService.reset();
    this.confirmationState = null;
    this.router.navigate(['/replenishment/dashboard']);
  }

  returnToSubmitStepFromConfirmation(): void {
    this.confirmationState = null;
    if (this.stepper) {
      this.stepper.selectedIndex = 2;
    }
  }

  startNewNeedsList(): void {
    this.wizardService.reset();
    this.confirmationState = null;
    if (this.stepper) {
      this.stepper.reset();
    }
  }
}
