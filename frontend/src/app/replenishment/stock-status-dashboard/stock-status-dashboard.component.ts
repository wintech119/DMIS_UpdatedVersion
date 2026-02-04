import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';
import { ReplenishmentService } from '../services/replenishment.service';
import { StockStatusItem, StockStatusResponse, formatTimeToStockout, EventPhase, SeverityLevel, FreshnessLevel } from '../models/stock-status.model';
import { TimeToStockoutComponent, TimeToStockoutData } from '../time-to-stockout/time-to-stockout.component';

interface FilterState {
  categories: string[];
  severities: SeverityLevel[];
  sortBy: 'time_to_stockout' | 'item_name' | 'severity';
  sortDirection: 'asc' | 'desc';
}

@Component({
  selector: 'app-stock-status-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTableModule,
    MatTooltipModule,
    TimeToStockoutComponent
  ],
  templateUrl: './stock-status-dashboard.component.html',
  styleUrl: './stock-status-dashboard.component.scss'
})
export class StockStatusDashboardComponent implements OnInit {
  readonly phaseOptions: EventPhase[] = ['SURGE', 'STABILIZED', 'BASELINE'];
  readonly severityOptions: SeverityLevel[] = ['CRITICAL', 'WARNING', 'WATCH', 'OK'];

  form: FormGroup;
  loading = false;
  response: StockStatusResponse | null = null;
  allItems: StockStatusItem[] = [];
  items: StockStatusItem[] = [];
  criticalItems: StockStatusItem[] = [];
  warnings: string[] = [];
  errors: string[] = [];

  // Filters
  filtersExpanded = true;
  availableCategories: string[] = [];
  selectedCategories: string[] = [];
  selectedSeverities: SeverityLevel[] = [];
  sortBy: 'time_to_stockout' | 'item_name' | 'severity' = 'time_to_stockout';
  sortDirection: 'asc' | 'desc' = 'asc';

  displayedColumns = [
    'severity',
    'item',
    'available',
    'inbound',
    'burn',
    'stockout',
    'required',
    'gap',
    'freshness'
  ];

  constructor(
    private fb: FormBuilder,
    private replenishmentService: ReplenishmentService,
    private router: Router
  ) {
    this.form = this.fb.group({
      event_id: [null, [Validators.required, Validators.min(1)]],
      warehouse_id: [null, [Validators.required, Validators.min(1)]],
      phase: ['BASELINE', Validators.required]
    });
  }

  ngOnInit(): void {
    this.loadFilterState();
    this.loadFormState();
  }

  loadStockStatus(): void {
    this.errors = [];
    if (this.form.invalid) {
      this.errors = ['Please provide valid event_id, warehouse_id, and phase.'];
      return;
    }

    this.loading = true;
    const { event_id, warehouse_id, phase } = this.form.value;

    this.replenishmentService.getStockStatus(event_id, warehouse_id, phase).subscribe({
      next: (data) => {
        this.response = data;
        this.allItems = data.items;

        // Extract unique categories
        this.availableCategories = [...new Set(
          data.items
            .map(item => item.category)
            .filter((cat): cat is string => !!cat)
        )].sort();

        this.applyFiltersAndSort();
        this.warnings = data.warnings ?? [];
        this.loading = false;
        this.saveFormState();
      },
      error: (error) => {
        this.loading = false;
        this.errors = [error.message || 'Failed to load stock status.'];
      }
    });
  }

  applyFiltersAndSort(): void {
    let filtered = [...this.allItems];

    // Filter by category
    if (this.selectedCategories.length > 0) {
      filtered = filtered.filter(item =>
        item.category && this.selectedCategories.includes(item.category)
      );
    }

    // Filter by severity
    if (this.selectedSeverities.length > 0) {
      filtered = filtered.filter(item => {
        const sev = item.severity ?? 'OK';
        return this.selectedSeverities.includes(sev);
      });
    }

    // Sort
    filtered = this.sortItems(filtered);

    this.items = filtered;
    this.criticalItems = this.items.filter(item =>
      item.severity === 'CRITICAL' || item.severity === 'WARNING'
    );

    this.saveFilterState();
  }

  toggleCategory(category: string): void {
    const index = this.selectedCategories.indexOf(category);
    if (index >= 0) {
      this.selectedCategories.splice(index, 1);
    } else {
      this.selectedCategories.push(category);
    }
    this.applyFiltersAndSort();
  }

  toggleSeverity(severity: SeverityLevel): void {
    const index = this.selectedSeverities.indexOf(severity);
    if (index >= 0) {
      this.selectedSeverities.splice(index, 1);
    } else {
      this.selectedSeverities.push(severity);
    }
    this.applyFiltersAndSort();
  }

  isCategorySelected(category: string): boolean {
    return this.selectedCategories.includes(category);
  }

  isSeveritySelected(severity: SeverityLevel): boolean {
    return this.selectedSeverities.includes(severity);
  }

  changeSortBy(field: 'time_to_stockout' | 'item_name' | 'severity'): void {
    if (this.sortBy === field) {
      this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortBy = field;
      this.sortDirection = 'asc';
    }
    this.applyFiltersAndSort();
  }

  resetFilters(): void {
    this.selectedCategories = [];
    this.selectedSeverities = [];
    this.sortBy = 'time_to_stockout';
    this.sortDirection = 'asc';
    this.applyFiltersAndSort();
  }

  hasActiveFilters(): boolean {
    return this.selectedCategories.length > 0 || this.selectedSeverities.length > 0;
  }

  toggleFilters(): void {
    this.filtersExpanded = !this.filtersExpanded;
  }

  generateNeedsList(): void {
    if (!this.response) return;

    // Navigate to needs list preview with pre-filled form data
    this.router.navigate(['/replenishment/needs-list-preview'], {
      queryParams: {
        event_id: this.response.event_id,
        warehouse_id: this.response.warehouse_id,
        phase: this.response.phase
      }
    });
  }

  getSeverityIcon(severity: SeverityLevel | undefined): string {
    switch (severity) {
      case 'CRITICAL': return 'error';
      case 'WARNING': return 'warning';
      case 'WATCH': return 'visibility';
      case 'OK': return 'check_circle';
      default: return 'help';
    }
  }

  getSeverityClass(severity: SeverityLevel | undefined): string {
    return `severity-${severity?.toLowerCase() ?? 'unknown'}`;
  }

  getFreshnessIcon(level: FreshnessLevel | undefined): string {
    switch (level) {
      case 'HIGH': return 'check_circle';
      case 'MEDIUM': return 'warning';
      case 'LOW': return 'error';
      default: return 'help';
    }
  }

  getFreshnessClass(level: FreshnessLevel | undefined): string {
    return `freshness-${level?.toLowerCase() ?? 'unknown'}`;
  }

  formatTimeToStockout(item: StockStatusItem): string {
    const value = item.time_to_stockout_hours ?? item.time_to_stockout;
    return formatTimeToStockout(value !== undefined ? value : null);
  }

  formatBurnRate(item: StockStatusItem): string {
    const rate = item.burn_rate_per_hour.toFixed(2);
    const estimated = item.is_estimated ? ' (est.)' : '';
    return `${rate} units/hr${estimated}`;
  }

  getBurnRateDisplay(item: StockStatusItem): string {
    const rate = item.burn_rate_per_hour.toFixed(2);

    // Handle zero burn rate cases
    if (item.burn_rate_per_hour === 0) {
      const freshness = item.freshness?.state;
      if (freshness === 'LOW' || freshness === 'MEDIUM') {
        return '0 units/hr (estimated - no recent data)';
      }
      return '0 units/hr - No current demand';
    }

    return `${rate} units/hr`;
  }

  getBurnRateConfidence(item: StockStatusItem): FreshnessLevel {
    return item.freshness?.state ?? 'HIGH';
  }

  getBurnRateConfidenceClass(level: FreshnessLevel): string {
    const classMap: Record<FreshnessLevel, string> = {
      'HIGH': 'confidence-high',
      'MEDIUM': 'confidence-medium',
      'LOW': 'confidence-low'
    };
    return classMap[level];
  }

  getBurnRateTooltip(item: StockStatusItem): string {
    const freshness = item.freshness;
    const rate = item.burn_rate_per_hour.toFixed(2);

    // Build tooltip text
    let tooltip = `Burn Rate: ${rate} units/hr\n`;

    if (item.is_estimated) {
      tooltip += 'Status: Estimated (limited data)\n';
    }

    if (freshness) {
      tooltip += `Data Freshness: ${freshness.state}\n`;
      if (freshness.age_hours !== null) {
        tooltip += `Age: ${freshness.age_hours.toFixed(1)} hours old\n`;
      }
      if (freshness.inventory_as_of) {
        tooltip += `Last Updated: ${new Date(freshness.inventory_as_of).toLocaleString()}\n`;
      }
    }

    // Add context about trend
    if (item.burn_rate_trend) {
      const trendText = {
        'up': 'Demand increasing',
        'down': 'Demand decreasing',
        'stable': 'Demand stable'
      };
      tooltip += `Trend: ${trendText[item.burn_rate_trend]}`;
    }

    return tooltip;
  }

  isStaleDataBurnRate(item: StockStatusItem): boolean {
    return item.freshness?.state === 'LOW';
  }

  shouldShowZeroWarning(item: StockStatusItem): boolean {
    return item.burn_rate_per_hour === 0 &&
           (item.freshness?.state === 'LOW' || item.freshness?.state === 'MEDIUM');
  }

  getTrendIcon(trend?: 'up' | 'down' | 'stable'): string {
    switch (trend) {
      case 'up': return 'trending_up';
      case 'down': return 'trending_down';
      case 'stable': return 'trending_flat';
      default: return '';
    }
  }

  getTrendClass(trend?: 'up' | 'down' | 'stable'): string {
    switch (trend) {
      case 'up': return 'trend-up';
      case 'down': return 'trend-down';
      case 'stable': return 'trend-stable';
      default: return '';
    }
  }

  getTimeToStockoutData(item: StockStatusItem): TimeToStockoutData {
    const hours = item.time_to_stockout_hours ?? null;
    const severity = item.severity ?? 'OK';
    const hasBurnRate = item.burn_rate_per_hour > 0;

    return {
      hours,
      severity,
      hasBurnRate
    };
  }

  hasCriticalItems(): boolean {
    return this.criticalItems.length > 0;
  }

  getDataFreshnessWarning(): string | null {
    if (!this.response?.data_freshness) return null;

    const overall = this.response.data_freshness.overall;
    const lastSync = this.response.data_freshness.last_sync;

    if (overall === 'LOW') {
      return `STALE DATA ALERT: Inventory data exceeds freshness threshold. Last sync: ${lastSync}`;
    }
    if (overall === 'MEDIUM') {
      return `Warning: Data is aging. Last sync: ${lastSync}. Calculations may not reflect current stock levels.`;
    }
    return null;
  }

  getPhaseLabel(): string {
    return this.response?.phase ?? 'Unknown';
  }

  getAsOfTime(): string {
    return this.response?.as_of_datetime ?? 'N/A';
  }

  private sortItems(items: StockStatusItem[]): StockStatusItem[] {
    const severityOrder: Record<SeverityLevel, number> = {
      CRITICAL: 0,
      WARNING: 1,
      WATCH: 2,
      OK: 3
    };

    return [...items].sort((a, b) => {
      let comparison = 0;

      switch (this.sortBy) {
        case 'time_to_stockout': {
          const normalizeTime = (value: unknown): number => {
            const numeric = typeof value === 'number' ? value : Number(value);
            return Number.isFinite(numeric) ? numeric : Infinity;
          };
          const timeA = normalizeTime(a.time_to_stockout_hours ?? a.time_to_stockout);
          const timeB = normalizeTime(b.time_to_stockout_hours ?? b.time_to_stockout);
          comparison = timeA - timeB;
          break;
        }
        case 'severity': {
          const severityA = severityOrder[a.severity ?? 'OK'];
          const severityB = severityOrder[b.severity ?? 'OK'];
          comparison = severityA - severityB;
          break;
        }
        case 'item_name': {
          const nameA = (a.item_name || `Item ${a.item_id}`).toLowerCase();
          const nameB = (b.item_name || `Item ${b.item_id}`).toLowerCase();
          comparison = nameA.localeCompare(nameB);
          break;
        }
      }

      return this.sortDirection === 'asc' ? comparison : -comparison;
    });
  }

  private saveFilterState(): void {
    const state: FilterState = {
      categories: this.selectedCategories,
      severities: this.selectedSeverities,
      sortBy: this.sortBy,
      sortDirection: this.sortDirection
    };
    localStorage.setItem('dmis_stock_filters', JSON.stringify(state));
  }

  private loadFilterState(): void {
    const saved = localStorage.getItem('dmis_stock_filters');
    if (saved) {
      try {
        const state: FilterState = JSON.parse(saved);
        this.selectedCategories = state.categories || [];
        this.selectedSeverities = state.severities || [];
        this.sortBy = state.sortBy || 'time_to_stockout';
        this.sortDirection = state.sortDirection || 'asc';
      } catch (e) {
        console.error('Failed to load filter state:', e);
      }
    }
  }

  private saveFormState(): void {
    const formValue = this.form.value;
    localStorage.setItem('dmis_stock_form', JSON.stringify(formValue));
  }

  private loadFormState(): void {
    const saved = localStorage.getItem('dmis_stock_form');
    if (saved) {
      try {
        const formValue = JSON.parse(saved);
        if (formValue.event_id && formValue.warehouse_id) {
          this.form.patchValue(formValue);
        }
      } catch (e) {
        console.error('Failed to load form state:', e);
      }
    }
  }
}
