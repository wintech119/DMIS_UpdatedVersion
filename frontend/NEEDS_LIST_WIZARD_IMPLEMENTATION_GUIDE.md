# Needs List Wizard - Implementation Guide

## Overview

Redesign the Needs List generation flow as a 3-step wizard to make the workflow clearer and more intuitive for field users like Kemar.

## Current State

- **Component**: `needs-list-preview.component.ts` (821 lines)
- **Problem**: All functionality in one component, unclear workflow, too many buttons
- **User feedback**: "Not sure what to do next", "Where do I adjust quantities?"

## Proposed Solution

Transform into a linear 3-step wizard with clear progression:

```text
┌─────────────────────────────────────────────────┐
│  [1] Review Scope  →  [2] Preview  →  [3] Submit │
└─────────────────────────────────────────────────┘
```

## Architecture

### Component Structure

```text
needs-list-wizard/
├── needs-list-wizard.component.ts       (Container with stepper)
├── needs-list-wizard.component.html
├── needs-list-wizard.component.scss
├── step1-scope/
│   ├── scope.component.ts               (Step 1: Review & Confirm Scope)
│   ├── scope.component.html
│   └── scope.component.scss
├── step2-preview/
│   ├── preview.component.ts             (Step 2: Preview Results)
│   ├── preview.component.html
│   └── preview.component.scss
├── step3-submit/
│   ├── submit.component.ts              (Step 3: Submit for Approval)
│   ├── submit.component.html
│   └── submit.component.scss
└── wizard.service.ts                    (Shared state management)
```

### State Management

Create `wizard.service.ts` to manage state across steps:

```typescript
interface WizardState {
  // Step 1 data
  event_id: number;
  warehouse_id: number;
  phase: 'SURGE' | 'STABILIZED' | 'BASELINE';
  selectedWarehouses: number[];  // For multi-warehouse support

  // Step 2 data
  items: NeedsListItem[];
  warnings: string[];
  adjustments: Record<number, {qty: number, reason: string}>;

  // Step 3 data
  notes: string;
  approval_summary: any;
}
```

## Step-by-Step Implementation

### Step 1: Review & Confirm Scope

**Purpose**: Set parameters before calculation

**UI Elements**:
```text
┌────────────────────────────────────────┐
│  Current Event Phase: SURGE            │
│  ├─ Demand Window: 6 hours            │
│  ├─ Planning Window: 72 hours         │
│  └─ Safety Factor: 1.5x               │
└────────────────────────────────────────┘

┌────────────────────────────────────────┐
│  Select Warehouses:                    │
│  [✓] National Warehouse (Kingston)     │
│  [✓] St. Catherine Depot              │
│  [ ] Portland Distribution Center      │
└────────────────────────────────────────┘

┌────────────────────────────────────────┐
│  Item Filters (Optional):              │
│  ☐ Critical Items Only                 │
│  ☐ Food & Water Only                   │
│  ☐ Medical Supplies Only               │
└────────────────────────────────────────┘

          [Calculate Gaps →]
```

**Key Logic**:
- Load event phase from backend
- Show phase parameters (read from `event_phase_config` table)
- Allow warehouse selection (default: primary warehouse only)
- Show item count estimate before calculation

**API Call**:
```typescript
// When user clicks "Calculate Gaps"
POST /api/v1/replenishment/needs-list/preview
{
  "event_id": 1,
  "warehouse_id": 1,  // Or array for multi-warehouse
  "phase": "SURGE",
  "filters": {
    "critical_only": false,
    "categories": []
  }
}
```

### Step 2: Preview Results

**Purpose**: Review gaps, adjust quantities, see recommendations

**UI Elements**:
```text
┌────────────────────────────────────────────────────────────────────┐
│  Gap Analysis Results                                              │
│  Total Items: 42 | Critical: 8 | Warning: 15 | Watch: 12 | OK: 7  │
└────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ Item Name         │ Warehouse │ Gap  │ Source   │ Lead Time │ Est. Cost    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 🚨 Bottled Water  │ National  │ 500  │ [🚚] A   │ 8 hours   │ $2,500       │
│ ⚠ MRE Meals       │ National  │ 300  │ [📦] B   │ 72 hours  │ $4,500       │
│ ⚠ First Aid Kits  │ St.Cath   │ 150  │ [📦] B   │ 72 hours  │ $1,200       │
│ ⚠ Blankets        │ National  │ 200  │ [📦] B   │ 72 hours  │ $800         │
│ 👀 Flashlights    │ St.Cath   │ 50   │ [🛒] C   │ 336 hrs   │ $300         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                              Total Estimated Cost: $9,300    │
└─────────────────────────────────────────────────────────────────────────────┘

[Adjust Quantity Button] - Opens inline editor:
┌────────────────────────────────────────┐
│  Original Qty: 500                     │
│  Adjusted Qty: [___400_____________]   │
│  Reason: [Partial Coverage ▼]         │
│           - Demand Adjusted            │
│           - Partial Coverage           │
│           - Priority Change            │
│           - Budget Constraint          │
│           - Other                      │
│  Notes: [Budget limit for this phase] │
│  [Cancel] [Apply Adjustment]           │
└────────────────────────────────────────┘

⚠ Items That Can't Be Fully Covered:
• Generator Fuel: Only 200/500 units available (40% coverage)
• Heavy Tarps: Lead time exceeds event phase (procurement too slow)

   [← Back to Scope]  [Continue to Submit →]
```

**Key Features**:
- **Color-coded severity**: Critical (red), Warning (amber), Watch (yellow), OK (green)
- **Recommended source icon**: 🚚 Transfer, 📦 Donation, 🛒 Procurement
- **Lead time display**: In hours for Transfer/Donation, days for Procurement
- **Inline editing**: Click row to adjust quantity with mandatory reason
- **Coverage warnings**: Highlight items that can't be fully covered
- **Running total**: Update cost as quantities are adjusted

**State Updates**:
```typescript
// Store adjustments in wizard service
adjustments[item_id] = {
  qty: 400,
  reason: 'BUDGET_CONSTRAINT',
  notes: 'Budget limit for this phase'
};
```

### Step 3: Submit for Approval

**Purpose**: Final review and submission

**UI Elements**:
```text
┌────────────────────────────────────────────────┐
│  Needs List Summary                            │
├────────────────────────────────────────────────┤
│  Event: Hurricane Response 2026                │
│  Phase: SURGE (72-hour planning window)        │
│  Warehouses: National, St. Catherine           │
│                                                │
│  📊 Totals:                                    │
│  • Items: 42                                   │
│  • Total Units: 3,850                          │
│  • Estimated Cost: $9,300 JMD                  │
│  • Adjustments Made: 5 items adjusted          │
│                                                │
│  📦 Breakdown by Source:                       │
│  • Horizon A (Transfers): 12 items, 1,200 u   │
│  • Horizon B (Donations): 25 items, 2,200 u   │
│  • Horizon C (Procurement): 5 items, 450 u     │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  Approval Path                                 │
├────────────────────────────────────────────────┤
│  💼 This needs list will be approved by:       │
│                                                │
│  [Phase: SURGE] → Immediate Authority          │
│  • Approver: Warehouse Manager                 │
│  • Authority: Up to $10,000 JMD               │
│  • Expected Response: 2-4 hours                │
│                                                │
│  ℹ️ Your request ($9,300) is within limits    │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│  Additional Notes (Optional)                   │
│  [                                            ]│
│  [  E.g., "Urgent: Flooding in Kingston      ]│
│  [  area requires immediate water supply"    ]│
│  [                                            ]│
└────────────────────────────────────────────────┘

⚠ Review Before Submitting:
• All critical items will be processed first
• Transfers will start within 8 hours of approval
• You will be notified when approved/rejected

   [← Back to Preview]  [Save as Draft]  [Submit for Approval]
```

**Key Logic**:
- Calculate totals from adjusted quantities
- Determine approval tier based on:
  - Event phase (SURGE/STABILIZED/BASELINE)
  - Total estimated cost
  - Procurement involvement
- Show expected approver and timeline
- Allow saving as draft (creates record but doesn't submit)

**API Calls**:
```typescript
// Save as Draft
POST /api/v1/replenishment/needs-list/draft
{
  "event_id": 1,
  "warehouse_id": 1,
  "phase": "SURGE",
  "items": [...],  // With adjustments applied
  "notes": "Urgent: Flooding in Kingston..."
}

// Submit for Approval
POST /api/v1/replenishment/needs-list/{draft_id}/submit
{
  "notes": "Urgent: Flooding in Kingston..."
}
```

## Wizard Container Implementation

### TypeScript (needs-list-wizard.component.ts)

```typescript
import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatStepperModule } from '@angular/material/stepper';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { ActivatedRoute, Router } from '@angular/router';

import { WizardService } from './wizard.service';
import { ScopeComponent } from './step1-scope/scope.component';
import { PreviewComponent } from './step2-preview/preview.component';
import { SubmitComponent } from './step3-submit/submit.component';

@Component({
  selector: 'app-needs-list-wizard',
  standalone: true,
  imports: [
    CommonModule,
    MatStepperModule,
    MatButtonModule,
    MatIconModule,
    ScopeComponent,
    PreviewComponent,
    SubmitComponent,
  ],
  templateUrl: './needs-list-wizard.component.html',
  styleUrl: './needs-list-wizard.component.scss',
})
export class NeedsListWizardComponent implements OnInit {
  constructor(
    public wizardService: WizardService,
    private route: ActivatedRoute,
    private router: Router
  ) {}

  ngOnInit() {
    // Load query params (event_id, warehouse_id, phase)
    this.route.queryParams.subscribe(params => {
      if (params['event_id']) {
        this.wizardService.setState({
          event_id: Number(params['event_id']),
          warehouse_id: Number(params['warehouse_id']),
          phase: params['phase'] || 'BASELINE'
        });
      }
    });
  }

  backToDashboard() {
    this.router.navigate(['/replenishment/dashboard']);
  }
}
```

### HTML (needs-list-wizard.component.html)

```html
<div class="wizard-container">
  <div class="wizard-header">
    <button mat-icon-button (click)="backToDashboard()" class="back-button">
      <mat-icon>arrow_back</mat-icon>
    </button>
    <h1>Generate Needs List</h1>
  </div>

  <mat-stepper linear #stepper>
    <!-- Step 1: Review & Confirm Scope -->
    <mat-step [stepControl]="wizardService.step1Valid$">
      <ng-template matStepLabel>Review Scope</ng-template>
      <app-scope
        (next)="stepper.next()"
      ></app-scope>
    </mat-step>

    <!-- Step 2: Preview Results -->
    <mat-step [stepControl]="wizardService.step2Valid$">
      <ng-template matStepLabel>Preview Results</ng-template>
      <app-preview
        (back)="stepper.previous()"
        (next)="stepper.next()"
      ></app-preview>
    </mat-step>

    <!-- Step 3: Submit for Approval -->
    <mat-step>
      <ng-template matStepLabel>Submit</ng-template>
      <app-submit
        (back)="stepper.previous()"
        (complete)="backToDashboard()"
      ></app-submit>
    </mat-step>
  </mat-stepper>
</div>
```

### SCSS (needs-list-wizard.component.scss)

```scss
.wizard-container {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;

  .wizard-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;

    .back-button {
      color: #666;
    }

    h1 {
      margin: 0;
      font-size: 24px;
      font-weight: 600;
    }
  }

  ::ng-deep mat-stepper {
    background: transparent;

    .mat-step-header {
      padding: 16px 24px;

      &.cdk-keyboard-focused,
      &.cdk-program-focused,
      &:hover {
        background-color: rgba(0, 0, 0, 0.04);
      }

      .mat-step-icon {
        background-color: #6c757d;

        &.mat-step-icon-selected {
          background-color: #007bff;
        }

        &.mat-step-icon-state-done {
          background-color: #28a745;
        }
      }

      .mat-step-label {
        font-size: 16px;
        font-weight: 500;
      }
    }

    .mat-stepper-horizontal-line {
      border-top-color: #dee2e6;
    }
  }
}

// Mobile responsive
@media (max-width: 768px) {
  .wizard-container {
    padding: 10px;

    .wizard-header h1 {
      font-size: 18px;
    }

    ::ng-deep mat-stepper {
      .mat-step-header {
        padding: 12px 8px;

        .mat-step-label {
          font-size: 12px;
        }
      }
    }
  }
}
```

## Wizard Service (wizard.service.ts)

```typescript
import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { map } from 'rxjs/operators';

interface WizardState {
  // Step 1
  event_id?: number;
  warehouse_id?: number;
  phase?: 'SURGE' | 'STABILIZED' | 'BASELINE';
  selectedWarehouses: number[];
  filters: {
    critical_only: boolean;
    categories: string[];
  };

  // Step 2
  items: any[];
  warnings: string[];
  adjustments: Record<number, { qty: number; reason: string; notes?: string }>;

  // Step 3
  notes: string;
  draft_id?: string;
}

@Injectable({
  providedIn: 'root'
})
export class WizardService {
  private state$ = new BehaviorSubject<WizardState>({
    selectedWarehouses: [],
    filters: { critical_only: false, categories: [] },
    items: [],
    warnings: [],
    adjustments: {},
    notes: ''
  });

  // Observables for step validation
  step1Valid$ = this.state$.pipe(
    map(state => !!(state.event_id && state.warehouse_id && state.phase))
  );

  step2Valid$ = this.state$.pipe(
    map(state => state.items.length > 0)
  );

  getState() {
    return this.state$.value;
  }

  setState(partial: Partial<WizardState>) {
    this.state$.next({ ...this.state$.value, ...partial });
  }

  reset() {
    this.state$.next({
      selectedWarehouses: [],
      filters: { critical_only: false, categories: [] },
      items: [],
      warnings: [],
      adjustments: {},
      notes: ''
    });
  }
}
```

## Migration Path

### Phase 1: Create Wizard Components (Week 1)
1. Create wizard container with stepper
2. Create Step 1 component (scope selection)
3. Test Step 1 in isolation

### Phase 2: Implement Steps 2 & 3 (Week 2)
4. Create Step 2 component (preview with adjustments)
5. Create Step 3 component (submit for approval)
6. Integrate with existing API endpoints

### Phase 3: Update Navigation (Week 3)
7. Update dashboard to route to wizard instead of preview
8. Add wizard route to app routing
9. Update needs-list-preview route to redirect to wizard

### Phase 4: Testing & Refinement (Week 4)
10. End-to-end testing
11. Mobile testing (key for Kemar!)
12. UAT with logistics team
13. Deploy to production

## Benefits

### For Users (Kemar)
- ✅ Clear progression through workflow
- ✅ No confusion about "what to do next"
- ✅ Mobile-friendly with larger touch targets
- ✅ Visual progress indicator (stepper)
- ✅ Can go back and forth between steps
- ✅ Clear approval path visibility

### For Developers
- ✅ Separation of concerns (one component per step)
- ✅ Easier to test individual steps
- ✅ Reusable step components
- ✅ Shared state management
- ✅ Linear flow prevents invalid states

### For Product Team
- ✅ Better analytics (track step completion rates)
- ✅ Identify drop-off points
- ✅ A/B test individual steps
- ✅ Easier to add/remove steps
- ✅ Clear user journey mapping

## Technical Considerations

### State Persistence
- Use `localStorage` to save wizard state
- Allow users to resume if they navigate away
- Clear state after successful submission

### Error Handling
- Validate each step before allowing "Next"
- Show errors inline within each step
- Don't let users proceed with invalid data

### Performance
- Lazy load step components
- Cache API responses for back/forward navigation
- Debounce quantity adjustments

### Accessibility
- Use proper ARIA labels for stepper
- Keyboard navigation support
- Screen reader announcements for step changes

## Next Steps

1. **Review this guide** with the team
2. **Prioritize which features** are MVP vs nice-to-have
3. **Create detailed tickets** for each step component
4. **Set up development environment** with Angular Material Stepper
5. **Begin implementation** starting with wizard container

---

**Estimated Effort**: 3-4 weeks for full implementation
**Priority**: High (improves core workflow)
**Risk**: Medium (requires refactoring existing component)
**User Impact**: High (significantly better UX for field users)
