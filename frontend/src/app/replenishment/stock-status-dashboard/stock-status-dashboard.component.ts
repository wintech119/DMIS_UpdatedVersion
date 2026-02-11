import { CommonModule } from '@angular/common';
import { Component, OnInit, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ReactiveFormsModule } from '@angular/forms';
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
import { MatExpansionModule } from '@angular/material/expansion';
import { MatMenuModule } from '@angular/material/menu';
import { MatDividerModule } from '@angular/material/divider';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Router } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ReplenishmentService, ActiveEvent, Warehouse } from '../services/replenishment.service';
import { DataFreshnessService } from '../services/data-freshness.service';
import { DashboardDataService, DashboardDataOptions } from '../services/dashboard-data.service';
import { DmisNotificationService } from '../services/notification.service';
import { StockStatusItem, formatTimeToStockout, EventPhase, SeverityLevel, FreshnessLevel, WarehouseStockGroup } from '../models/stock-status.model';
import { TimeToStockoutComponent, TimeToStockoutData } from '../time-to-stockout/time-to-stockout.component';
import { PhaseSelectDialogComponent } from '../phase-select-dialog/phase-select-dialog.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';

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
    MatExpansionModule,
    MatMenuModule,
    MatDividerModule,
    MatDialogModule,
    MatProgressSpinnerModule,
    TimeToStockoutComponent,
    DmisSkeletonLoaderComponent,
    DmisEmptyStateComponent
  ],
  templateUrl: './stock-status-dashboard.component.html',
  styleUrl: './stock-status-dashboard.component.scss'
})
export class StockStatusDashboardComponent implements OnInit {
  private destroyRef = inject(DestroyRef);
  private dataFreshnessService = inject(DataFreshnessService);
  private dashboardDataService = inject(DashboardDataService);
  private notificationService = inject(DmisNotificationService);

  readonly phaseOptions: EventPhase[] = ['SURGE', 'STABILIZED', 'BASELINE'];
  readonly severityOptions: SeverityLevel[] = ['CRITICAL', 'WARNING', 'WATCH', 'OK'];

  // Current context
  activeEvent: ActiveEvent | null = null;
  allWarehouses: Warehouse[] = [];
  selectedWarehouseIds: number[] = []; // Empty = all warehouses

  // View mode
  viewMode: 'multi' | 'single' = 'multi';

  loading = false;
  refreshing = false;
  dataLoadedSuccessfully = false;
  warehouseGroups: WarehouseStockGroup[] = [];
  warnings: string[] = [];
  errors: string[] = [];

  // Filters
  filtersExpanded = false; // Collapsed by default
  availableCategories: string[] = [];
  selectedCategories: string[] = [];
  selectedSeverities: SeverityLevel[] = [];
  sortBy: 'time_to_stockout' | 'item_name' | 'severity' = 'time_to_stockout';
  sortDirection: 'asc' | 'desc' = 'asc';

  // For single warehouse drill-down
  selectedWarehouseId: number | null = null;
  private singleWarehouseRequestToken = 0;

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
    private replenishmentService: ReplenishmentService,
    private router: Router,
    private dialog: MatDialog
  ) {}

  ngOnInit(): void {
    this.loadFilterState();
    this.autoLoadDashboard();

    // Listen for refresh requests from the freshness banner
    this.dataFreshnessService.onRefreshRequested$().pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(() => {
      this.dashboardDataService.invalidateCache();
      this.loadMultiWarehouseStatus();
    });
  }

  /**
   * Auto-load dashboard with active event and all warehouses
   */
  autoLoadDashboard(): void {
    this.loading = true;
    this.errors = [];

    forkJoin({
      event: this.replenishmentService.getActiveEvent(),
      warehouses: this.replenishmentService.getAllWarehouses()
    }).subscribe({
      next: ({ event, warehouses }) => {
        this.activeEvent = event;
        this.allWarehouses = warehouses;

        // If no active event, stop loading and show empty state
        if (!event) {
          this.loading = false;
          return;
        }

        // Load stock status for all warehouses
        this.loadMultiWarehouseStatus();
      },
      error: (error) => {
        this.loading = false;
        const msg = error.error?.errors?.event || error.message || 'Failed to load dashboard data.';
        this.notificationService.showNetworkError(msg, () => this.autoLoadDashboard());
      }
    });
  }

  /**
   * Load stock status for all warehouses (or filtered warehouses)
   * via the DashboardDataService (handles enrichment, grouping, sorting, caching)
   */
  loadMultiWarehouseStatus(): void {
    if (!this.activeEvent) return;

    this.errors = [];
    const warehouseIds = this.selectedWarehouseIds.length > 0
      ? this.selectedWarehouseIds
      : this.allWarehouses.map(w => w.warehouse_id);

    if (warehouseIds.length === 0) {
      this.loading = false;
      this.notificationService.showWarning('No warehouses available.');
      return;
    }

    this.dataLoadedSuccessfully = false;

    // Use refreshing for subsequent loads (when data already exists)
    if (this.warehouseGroups.length > 0) {
      this.refreshing = true;
    } else {
      this.loading = true;
    }

    this.dashboardDataService.getDashboardData(
      this.activeEvent.event_id,
      warehouseIds,
      this.activeEvent.phase as EventPhase,
      this.buildFilterOptions()
    ).subscribe({
      next: (data) => {
        this.warehouseGroups = data.groups;
        this.warnings = data.warnings;
        this.availableCategories = data.availableCategories;

        this.dataFreshnessService.updateFromWarehouseGroups(this.warehouseGroups);
        this.dataFreshnessService.refreshComplete();
        this.dataLoadedSuccessfully = true;
        this.errors = [];
        this.loading = false;
        this.refreshing = false;
      },
      error: (error) => {
        this.loading = false;
        this.refreshing = false;
        this.dataFreshnessService.refreshComplete();
        this.dataLoadedSuccessfully = false;
        const msg = error.message || 'Failed to load stock status.';
        this.errors = [msg];
        this.notificationService.showNetworkError(msg, () => this.loadMultiWarehouseStatus());
      }
    });
  }

  /** Build DashboardDataOptions from current filter state */
  private buildFilterOptions(): DashboardDataOptions {
    return {
      categories: this.selectedCategories,
      severities: this.selectedSeverities,
      sortBy: this.sortBy,
      sortDirection: this.sortDirection
    };
  }

  /**
   * Reload data when filters change.
   * The service caches enriched items, so filter changes are served locally
   * (no API call) as long as the base data is still fresh.
   */
  onFiltersChanged(): void {
    this.saveFilterState();
    if (this.viewMode === 'multi') {
      this.loadMultiWarehouseStatus();
    } else {
      this.loadSingleWarehouseStatus();
    }
  }

  /**
   * Load single-warehouse view via the service.
   * Uses the same cache as multi-warehouse if the base params match.
   */
  private loadSingleWarehouseStatus(): void {
    if (!this.activeEvent || this.selectedWarehouseId == null) return;

    const requestedWarehouseId = this.selectedWarehouseId;
    const requestedEventId = this.activeEvent.event_id;
    const requestToken = ++this.singleWarehouseRequestToken;

    this.errors = [];
    this.dataLoadedSuccessfully = false;
    if (this.warehouseGroups.length > 0) {
      this.refreshing = true;
    } else {
      this.loading = true;
    }

    this.dashboardDataService.getDashboardData(
      requestedEventId,
      [requestedWarehouseId],
      this.activeEvent.phase as EventPhase,
      this.buildFilterOptions()
    ).subscribe({
      next: (data) => {
        if (!this.shouldApplySingleWarehouseResult(requestToken, requestedWarehouseId, requestedEventId)) {
          return;
        }

        // Filter to just the selected warehouse
        this.warehouseGroups = data.groups.filter(
          g => g.warehouse_id === requestedWarehouseId
        );
        this.warnings = data.warnings;
        this.availableCategories = data.availableCategories;
        this.dataFreshnessService.updateFromWarehouseGroups(this.warehouseGroups);
        this.dataFreshnessService.refreshComplete();
        this.dataLoadedSuccessfully = true;
        this.errors = [];
        this.loading = false;
        this.refreshing = false;
      },
      error: (error) => {
        if (!this.shouldApplySingleWarehouseResult(requestToken, requestedWarehouseId, requestedEventId)) {
          return;
        }

        this.loading = false;
        this.refreshing = false;
        this.dataFreshnessService.refreshComplete();
        this.dataLoadedSuccessfully = false;
        const msg = error.message || 'Failed to load stock status.';
        this.errors = [msg];
        this.notificationService.showNetworkError(msg, () => this.retryCurrentView());
      }
    });
  }

  private shouldApplySingleWarehouseResult(
    requestToken: number,
    requestedWarehouseId: number,
    requestedEventId: number
  ): boolean {
    return this.viewMode === 'single' &&
      this.singleWarehouseRequestToken === requestToken &&
      this.selectedWarehouseId === requestedWarehouseId &&
      this.activeEvent?.event_id === requestedEventId;
  }

  private invalidateSingleWarehouseRequest(): void {
    this.singleWarehouseRequestToken++;
  }

  retryCurrentView(): void {
    if (this.viewMode === 'single') {
      this.loadSingleWarehouseStatus();
      return;
    }
    this.loadMultiWarehouseStatus();
  }

  /**
   * Toggle warehouse selection for filtering
   */
  toggleWarehouseFilter(warehouseId: number): void {
    const index = this.selectedWarehouseIds.indexOf(warehouseId);
    if (index >= 0) {
      this.selectedWarehouseIds.splice(index, 1);
    } else {
      this.selectedWarehouseIds.push(warehouseId);
    }
    this.onFiltersChanged();
  }

  isWarehouseSelected(warehouseId: number): boolean {
    return this.selectedWarehouseIds.length === 0 || this.selectedWarehouseIds.includes(warehouseId);
  }

  /**
   * Clear warehouse filter (show all)
   */
  clearWarehouseFilter(): void {
    this.selectedWarehouseIds = [];
    this.onFiltersChanged();
  }

  /**
   * Drill down to single warehouse detail view
   */
  drillDownToWarehouse(warehouseId: number): void {
    this.invalidateSingleWarehouseRequest();
    this.viewMode = 'single';
    this.selectedWarehouseId = warehouseId;
    this.loadSingleWarehouseStatus();
  }

  /**
   * Return to multi-warehouse view
   */
  returnToMultiView(): void {
    this.invalidateSingleWarehouseRequest();
    this.viewMode = 'multi';
    this.selectedWarehouseId = null;
    this.loadMultiWarehouseStatus();
  }

  /**
   * Change event or phase
   */
  changeEventOrPhase(): void {
    if (!this.activeEvent) {
      return;
    }
    const dialogRef = this.dialog.open(PhaseSelectDialogComponent, {
      data: { currentPhase: this.activeEvent?.phase },
      ariaLabel: 'Select event phase'
    });

    dialogRef.afterClosed().subscribe((newPhase?: EventPhase) => {
      if (!newPhase) {
        return;
      }
      if (!this.activeEvent) {
        return;
      }
      this.activeEvent = { ...this.activeEvent, phase: newPhase };
      this.dashboardDataService.invalidateCache();
      this.loadMultiWarehouseStatus();
    });
  }

  toggleCategory(category: string): void {
    const index = this.selectedCategories.indexOf(category);
    if (index >= 0) {
      this.selectedCategories.splice(index, 1);
    } else {
      this.selectedCategories.push(category);
    }
    this.onFiltersChanged();
  }

  toggleSeverity(severity: SeverityLevel): void {
    const index = this.selectedSeverities.indexOf(severity);
    if (index >= 0) {
      this.selectedSeverities.splice(index, 1);
    } else {
      this.selectedSeverities.push(severity);
    }
    this.onFiltersChanged();
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
    this.onFiltersChanged();
  }

  resetFilters(): void {
    this.selectedCategories = [];
    this.selectedSeverities = [];
    this.selectedWarehouseIds = [];
    this.sortBy = 'time_to_stockout';
    this.sortDirection = 'asc';
    this.onFiltersChanged();
  }

  hasActiveFilters(): boolean {
    return this.selectedCategories.length > 0 ||
           this.selectedSeverities.length > 0 ||
           this.selectedWarehouseIds.length > 0;
  }

  toggleFilters(): void {
    this.filtersExpanded = !this.filtersExpanded;
  }

  generateNeedsList(warehouseId?: number): void {
    if (!this.activeEvent) return;

    // Navigate to needs list wizard with pre-filled form data
    this.router.navigate(['/replenishment/needs-list-wizard'], {
      queryParams: {
        event_id: this.activeEvent.event_id,
        event_name: this.activeEvent.event_name,
        warehouse_id: warehouseId || this.selectedWarehouseId,
        phase: this.activeEvent.phase
      }
    });
  }

  getTotalCriticalCount(): number {
    return this.warehouseGroups.reduce((sum, g) => sum + g.critical_count, 0);
  }

  getTotalWarningCount(): number {
    return this.warehouseGroups.reduce((sum, g) => sum + g.warning_count, 0);
  }

  hasCriticalItems(): boolean {
    return this.getTotalCriticalCount() > 0;
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

  getSeverityTooltip(severity: SeverityLevel): string {
    switch (severity) {
      case 'CRITICAL':
        return 'CRITICAL: Less than 8 hours of stock remaining. Immediate replenishment action required using transfers (Horizon A).';
      case 'WARNING':
        return 'WARNING: 8-24 hours of stock remaining. Replenishment should be initiated soon using transfers or donations (Horizon A/B).';
      case 'WATCH':
        return 'WATCH: 24-72 hours of stock remaining. Monitor closely and plan replenishment using donations or procurement (Horizon B/C).';
      case 'OK':
        return 'OK: More than 72 hours of stock remaining. Stock levels are healthy.';
      default:
        return 'Unknown severity level';
    }
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

  getBurnRateDisplay(item: StockStatusItem): string {
    const rate = item.burn_rate_per_hour.toFixed(2);

    // Handle zero burn rate cases
    if (item.burn_rate_per_hour === 0) {
      const freshness = item.freshness?.state;
      if (freshness === 'LOW' || freshness === 'MEDIUM') {
        return '0 units/hr (no recent data)';
      }
      return '0 units/hr';
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

  getDataFreshnessWarning(group: WarehouseStockGroup): string | null {
    const overall = group.overall_freshness;

    if (overall === 'LOW') {
      return `STALE DATA ALERT: Inventory data exceeds freshness threshold for ${group.warehouse_name}`;
    }
    if (overall === 'MEDIUM') {
      return `Warning: Data is aging for ${group.warehouse_name}. Calculations may not reflect current stock levels.`;
    }
    return null;
  }

  getPhaseLabel(): string {
    return this.activeEvent?.phase ?? 'Unknown';
  }

  getEventName(): string {
    return this.activeEvent?.event_name ?? 'No Active Event';
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
}
