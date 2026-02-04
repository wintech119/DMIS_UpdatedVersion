import { Component, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatStepperModule, MatStepper } from '@angular/material/stepper';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatTooltipModule } from '@angular/material/tooltip';

import { WizardStateService } from './services/wizard-state.service';

@Component({
  selector: 'app-needs-list-wizard',
  standalone: true,
  imports: [
    CommonModule,
    MatStepperModule,
    MatButtonModule,
    MatIconModule,
    MatCardModule,
    MatTooltipModule
  ],
  templateUrl: './needs-list-wizard.component.html',
  styleUrl: './needs-list-wizard.component.scss'
})
export class NeedsListWizardComponent implements OnInit {
  @ViewChild('stepper') stepper!: MatStepper;

  constructor(
    public wizardService: WizardStateService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit(): void {
    // Load query params from dashboard navigation
    this.route.queryParams.subscribe(params => {
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

  onStepChange(event: any): void {
    // Track step changes for analytics
    console.log('Step changed:', event.selectedIndex);
  }
}
