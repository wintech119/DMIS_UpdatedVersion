import { CommonModule } from '@angular/common';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Component } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatDividerModule } from '@angular/material/divider';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';

type HorizonBlock = { recommended_qty: number | null };

interface NeedsListItem {
  item_id: number;
  available_qty: number;
  inbound_strict_qty: number;
  burn_rate_per_hour: number;
  required_qty?: number;
  gap_qty: number;
  time_to_stockout?: string | number;
  horizon?: { A: HorizonBlock; B: HorizonBlock; C: HorizonBlock };
  triggers?: { activate_B: boolean; activate_C: boolean; activate_all: boolean };
  confidence?: { level: string; reasons: string[] };
  warnings?: string[];
  freshness_state?: string;
  freshness?: { state: string; age_hours: number | null; inventory_as_of: string | null };
  procurement_status?: string | null;
  procurement?: {
    recommended_qty: number;
    est_unit_cost?: number | null;
    est_total_cost?: number | null;
    lead_time_hours_default: number;
    approval?: { tier: string; approver_role: string; methods_allowed: string[] };
    gojep_note?: { label: string; url: string };
  };
}

interface NeedsListResponse {
  as_of_datetime: string;
  planning_window_days: number;
  event_id: number;
  warehouse_id: number;
  phase: string;
  items: NeedsListItem[];
  warnings: string[];
}

@Component({
  selector: 'app-needs-list-preview',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatDividerModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTableModule
  ],
  templateUrl: './needs-list-preview.component.html',
  styleUrl: './needs-list-preview.component.scss'
})
export class NeedsListPreviewComponent {
  readonly phaseOptions = ['SURGE', 'STABILIZED', 'BASELINE'] as const;

  readonly form: FormGroup;
  private readonly warningLabels: Record<string, string> = {
    burn_data_missing: 'No recent burn data found in the demand window.',
    burn_fallback_unavailable: 'No category fallback rate is available for this item.',
    burn_rate_estimated: 'Burn rate is estimated from fallback data.',
    burn_no_rows_in_window: 'No validated fulfillments in the demand window.',
    db_unavailable_preview_stub: 'Database unavailable; showing preview stub values.',
    donation_in_transit_unmodeled: 'Donation in-transit data is not modeled yet.',
    procurement_unavailable_in_schema: 'Procurement data is not modeled yet.',
    procurement_cost_unavailable: 'Procurement cost estimates are unavailable.',
    procurement_category_unavailable: 'Procurement category is missing; using defaults.',
    procurement_cost_invalid: 'Procurement cost estimate is invalid.',
    procurement_phase_invalid: 'Procurement phase value is invalid; using baseline.',
    strict_inbound_mapping_best_effort: 'Inbound status mapping uses best-effort rules.',
    critical_flag_unavailable: 'Critical item flag not configured.',
    inventory_timestamp_unavailable: 'Inventory timestamp is unavailable.',
    burn_fallback_unavailable_in_schema: 'Fallback burn rate data is missing in schema.'
  };

  loading = false;
  response: NeedsListResponse | null = null;
  items: NeedsListItem[] = [];
  topWarnings: string[] = [];
  perItemWarnings: { item_id: number; warnings: string[] }[] = [];
  errors: string[] = [];

  displayedColumns = [
    'item',
    'available',
    'inbound',
    'burn',
    'required',
    'gap',
    'stockout',
    'horizonA',
    'horizonB',
    'horizonC',
    'confidence',
    'freshness'
  ];

  constructor(private readonly fb: FormBuilder, private readonly http: HttpClient) {
    this.form = this.fb.group({
      event_id: [null, [Validators.required, Validators.min(1)]],
      warehouse_id: [null, [Validators.required, Validators.min(1)]],
      phase: ['BASELINE', Validators.required],
      as_of_datetime: ['']
    });
  }

  generatePreview(): void {
    this.errors = [];
    if (this.form.invalid) {
      this.errors = ['Please provide valid event_id, warehouse_id, and phase.'];
      return;
    }

    const payload: Record<string, unknown> = {
      event_id: Number(this.form.value.event_id),
      warehouse_id: Number(this.form.value.warehouse_id),
      phase: this.form.value.phase
    };

    if (this.form.value.as_of_datetime) {
      payload['as_of_datetime'] = this.form.value.as_of_datetime;
    }

    this.loading = true;
    this.http.post<NeedsListResponse>('/api/v1/replenishment/needs-list/preview', payload).subscribe({
      next: (data) => {
        this.response = data;
        this.items = data.items ?? [];
        this.topWarnings = data.warnings ?? [];
        this.perItemWarnings = this.items
          .filter((item) => item.warnings && item.warnings.length)
          .map((item) => ({ item_id: item.item_id, warnings: item.warnings ?? [] }));
        this.loading = false;
      },
      error: (error: HttpErrorResponse) => {
        this.loading = false;
        if (error.error?.errors) {
          const errors = error.error.errors;
          this.errors = Object.entries(errors).map(([field, message]) => `${field}: ${message}`);
          return;
        }
        this.errors = [error.message || 'Preview request failed.'];
      }
    });
  }

  requiredQty(item: NeedsListItem): number {
    if (typeof item.required_qty === 'number') {
      return Number(item.required_qty.toFixed(2));
    }
    const available = item.available_qty ?? 0;
    const inbound = item.inbound_strict_qty ?? 0;
    const gap = item.gap_qty ?? 0;
    return Number((available + inbound + gap).toFixed(2));
  }

  horizonValue(block?: HorizonBlock): string {
    if (!block || block.recommended_qty === null || block.recommended_qty === undefined) {
      return 'N/A';
    }
    return block.recommended_qty.toFixed(2);
  }

  confidenceLevel(item: NeedsListItem): string {
    return item.confidence?.level ?? 'unknown';
  }

  freshnessState(item: NeedsListItem): string {
    const state = item.freshness_state ?? item.freshness?.state ?? 'unknown';
    return String(state).toLowerCase();
  }

  freshnessLabel(item: NeedsListItem): string {
    const state = this.freshnessState(item);
    return state.charAt(0).toUpperCase() + state.slice(1);
  }

  timeToStockout(item: NeedsListItem): string {
    const value = item.time_to_stockout ?? '';
    if (typeof value === 'number') {
      return value.toFixed(2);
    }
    return value || 'N/A';
  }

  isEstimated(item: NeedsListItem): boolean {
    return (item.warnings ?? []).includes('burn_rate_estimated');
  }

  warningList(source: string[]): string {
    return source.join(', ');
  }

  warningLabel(code: string): string {
    return this.warningLabels[code] ?? this.humanizeWarning(code);
  }

  private humanizeWarning(code: string): string {
    return code
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  dataNotes(): string[] {
    if (!this.response) {
      return [];
    }
    const warnings = new Set<string>([
      ...(this.topWarnings ?? []),
      ...this.perItemWarnings.flatMap((entry) => entry.warnings ?? [])
    ]);
    const hasMissingDataWarning =
      warnings.has('burn_data_missing') ||
      warnings.has('donation_in_transit_unmodeled') ||
      warnings.has('db_unavailable_preview_stub');

    if (!hasMissingDataWarning) {
      return [];
    }

    return [
      'Burn rate and/or inbound may be zero because relief package, transfer, or donation in-transit data is missing or not modeled yet.'
    ];
  }
}
