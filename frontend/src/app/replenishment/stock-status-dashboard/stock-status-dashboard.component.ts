import { CommonModule } from '@angular/common';
import { Component, OnInit, DestroyRef, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipSelectionChange, MatChipsModule } from '@angular/material/chips';
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
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ReplenishmentService, ActiveEvent, Warehouse } from '../services/replenishment.service';
import { DataFreshnessService } from '../services/data-freshness.service';
import { DashboardDataService, DashboardDataOptions } from '../services/dashboard-data.service';
import { DmisNotificationService } from '../services/notification.service';
import { StockStatusItem, formatTimeToStockout, EventPhase, SeverityLevel, FreshnessLevel, WarehouseStockGroup } from '../models/stock-status.model';
import { NeedsListResponse } from '../models/needs-list.model';
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
  private replenishmentService = inject(ReplenishmentService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private dialog = inject(MatDialog);
  private http = inject(HttpClient);

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
  canAccessReviewQueue = false;
  mySubmissionUpdates: NeedsListResponse[] = [];

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
  private multiWarehouseRequestToken = 0;
  private singleWarehouseRequestToken = 0;
  private currentUserRef: string | null = null;
  private readonly seenSubmitterUpdateStorageKey = 'dmis_needs_list_submitter_updates_seen';
  private seenSubmitterUpdateKeys = new Set<string>();
  private requestedEventId: number | null = null;
  private requestedPhase: EventPhase | null = null;

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

  ngOnInit(): void {
    this.loadSeenSubmitterUpdateKeys();
    const context = String(this.route.snapshot.queryParamMap.get('context') ?? '').trim().toLowerCase();
    if (context === 'wizard') {
      const requestedEvent = Number(this.route.snapshot.queryParamMap.get('event_id'));
      if (Number.isFinite(requestedEvent) && requestedEvent > 0) {
        this.requestedEventId = requestedEvent;
      }
      const requestedPhase = String(this.route.snapshot.queryParamMap.get('phase') ?? '').trim().toUpperCase();
      if (requestedPhase === 'SURGE' || requestedPhase === 'STABILIZED' || requestedPhase === 'BASELINE') {
        this.requestedPhase = requestedPhase as EventPhase;
      }
      this.clearWizardReturnContext();
    }

    this.loadReviewQueueAccess();
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
        if (event) {
          const selectedEventId = this.requestedEventId ?? event.event_id;
          const selectedPhase = this.requestedPhase ?? (event.phase as EventPhase);
          this.activeEvent = {
            ...event,
            event_id: selectedEventId,
            phase: selectedPhase
          };
        } else {
          this.activeEvent = null;
        }
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
    const requestedWarehouseIds = this.toSortedWarehouseIds(warehouseIds);
    const requestedEventId = this.activeEvent.event_id;
    const requestedPhase = this.activeEvent.phase as EventPhase;
    const requestToken = ++this.multiWarehouseRequestToken;

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
      requestedEventId,
      requestedWarehouseIds,
      requestedPhase,
      this.buildFilterOptions()
    ).subscribe({
      next: (data) => {
        if (!this.shouldApplyMultiWarehouseResult(requestToken, requestedEventId, requestedPhase, requestedWarehouseIds)) {
          return;
        }

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
        if (!this.shouldApplyMultiWarehouseResult(requestToken, requestedEventId, requestedPhase, requestedWarehouseIds)) {
          return;
        }

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
    this.updateCategorySelection(category, !this.selectedCategories.includes(category));
    this.onFiltersChanged();
  }

  toggleSeverity(severity: SeverityLevel): void {
    this.updateSeveritySelection(severity, !this.selectedSeverities.includes(severity));
    this.onFiltersChanged();
  }

  onCategorySelectionChange(category: string, change: MatChipSelectionChange): void {
    if (!change.isUserInput) {
      return;
    }
    this.updateCategorySelection(category, change.selected);
    this.onFiltersChanged();
  }

  onSeveritySelectionChange(severity: SeverityLevel, change: MatChipSelectionChange): void {
    if (!change.isUserInput) {
      return;
    }
    this.updateSeveritySelection(severity, change.selected);
    this.onFiltersChanged();
  }

  private updateCategorySelection(category: string, selected: boolean): void {
    const index = this.selectedCategories.indexOf(category);
    if (selected && index < 0) {
      this.selectedCategories.push(category);
      return;
    }
    if (!selected && index >= 0) {
      this.selectedCategories.splice(index, 1);
    }
  }

  private updateSeveritySelection(severity: SeverityLevel, selected: boolean): void {
    const index = this.selectedSeverities.indexOf(severity);
    if (selected && index < 0) {
      this.selectedSeverities.push(severity);
      return;
    }
    if (!selected && index >= 0) {
      this.selectedSeverities.splice(index, 1);
    }
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

  openReviewQueue(): void {
    this.router.navigate(['/replenishment/needs-list-review']);
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

  private loadReviewQueueAccess(): void {
    this.http.get<{ user_id?: string; username?: string; roles?: string[]; permissions?: string[] }>('/api/v1/auth/whoami/').subscribe({
      next: (data) => {
        const roles = new Set((data.roles ?? []).map((role) => role.toUpperCase()));
        const permissions = new Set((data.permissions ?? []).map((perm) => perm.toLowerCase()));
        const userRef = String(data.username ?? data.user_id ?? '').trim();
        this.currentUserRef = userRef || null;
        const hasPreviewPermission = permissions.has('replenishment.needs_list.preview');
        const reviewPermissions = [
          'replenishment.needs_list.approve',
          'replenishment.needs_list.reject',
          'replenishment.needs_list.return',
          'replenishment.needs_list.escalate'
        ];
        this.canAccessReviewQueue =
          hasPreviewPermission && (
            roles.has('EXECUTIVE') ||
            reviewPermissions.some((perm) => permissions.has(perm))
          );
        this.loadMySubmissionUpdates();
      },
      error: () => {
        this.canAccessReviewQueue = false;
        this.currentUserRef = null;
        this.mySubmissionUpdates = [];
      }
    });
  }

  private shouldApplyMultiWarehouseResult(
    requestToken: number,
    requestedEventId: number,
    requestedPhase: EventPhase,
    requestedWarehouseIds: number[]
  ): boolean {
    return this.viewMode === 'multi' &&
      this.multiWarehouseRequestToken === requestToken &&
      this.activeEvent?.event_id === requestedEventId &&
      (this.activeEvent?.phase as EventPhase | undefined) === requestedPhase &&
      this.areWarehouseSelectionsEqual(this.currentMultiWarehouseIds(), requestedWarehouseIds);
  }

  private currentMultiWarehouseIds(): number[] {
    const sourceIds = this.selectedWarehouseIds.length > 0
      ? this.selectedWarehouseIds
      : this.allWarehouses.map((w) => w.warehouse_id);
    return this.toSortedWarehouseIds(sourceIds);
  }

  private toSortedWarehouseIds(warehouseIds: number[]): number[] {
    return [...warehouseIds].sort((a, b) => a - b);
  }

  private areWarehouseSelectionsEqual(first: number[], second: number[]): boolean {
    if (first.length !== second.length) {
      return false;
    }
    return first.every((warehouseId, index) => warehouseId === second[index]);
  }

  openNeedsListUpdate(row: NeedsListResponse): void {
    if (!row.needs_list_id) {
      return;
    }
    this.router.navigate(['/replenishment/needs-list-review', row.needs_list_id]);
  }

  private loadMySubmissionUpdates(): void {
    if (!this.currentUserRef) {
      this.mySubmissionUpdates = [];
      return;
    }

    this.replenishmentService
      .listNeedsLists(['APPROVED', 'RETURNED', 'REJECTED'])
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          const currentUser = String(this.currentUserRef ?? '').trim().toLowerCase();
          const updates = (data.needs_lists ?? [])
            .filter((row) => String(row.submitted_by ?? '').trim().toLowerCase() === currentUser)
            .sort((a, b) => this.updateTimestamp(b) - this.updateTimestamp(a))
            .slice(0, 5);

          this.mySubmissionUpdates = updates;
          this.notifySubmitterStatusUpdates(updates);
        },
        error: () => {
          // Keep dashboard functional when this optional feed is unavailable.
          this.mySubmissionUpdates = [];
        }
      });
  }

  private updateTimestamp(row: NeedsListResponse): number {
    const candidates = [
      row.approved_at,
      row.reviewed_at,
      row.updated_at,
      row.submitted_at
    ];
    for (const value of candidates) {
      if (!value) {
        continue;
      }
      const ts = Date.parse(value);
      if (Number.isFinite(ts)) {
        return ts;
      }
    }
    return 0;
  }

  private updateNotificationKey(row: NeedsListResponse): string {
    return [
      row.needs_list_id ?? '',
      row.status ?? '',
      row.approved_at ?? row.reviewed_at ?? row.updated_at ?? row.submitted_at ?? ''
    ].join('|');
  }

  private notifySubmitterStatusUpdates(rows: NeedsListResponse[]): void {
    for (const row of rows) {
      const key = this.updateNotificationKey(row);
      if (!key || this.seenSubmitterUpdateKeys.has(key)) {
        continue;
      }

      const listRef = row.needs_list_no ?? row.needs_list_id ?? 'Needs list';
      if (row.status === 'APPROVED') {
        const approver = row.approved_by ? ` by ${row.approved_by}` : '';
        this.notificationService.showSuccess(`${listRef} was approved${approver}.`);
      } else if (row.status === 'RETURNED') {
        this.notificationService.showWarning(`${listRef} was returned and needs updates.`);
      } else if (row.status === 'REJECTED') {
        this.notificationService.showWarning(`${listRef} was rejected.`);
      } else {
        continue;
      }

      this.seenSubmitterUpdateKeys.add(key);
    }

    this.persistSeenSubmitterUpdateKeys();
  }

  private loadSeenSubmitterUpdateKeys(): void {
    try {
      const raw = localStorage.getItem(this.seenSubmitterUpdateStorageKey);
      if (!raw) {
        return;
      }
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        this.seenSubmitterUpdateKeys = new Set(
          parsed
            .map((entry) => String(entry).trim())
            .filter((entry) => entry.length > 0)
        );
      }
    } catch {
      this.seenSubmitterUpdateKeys = new Set();
    }
  }

  private clearWizardReturnContext(): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        context: null,
        event_id: null,
        phase: null
      },
      queryParamsHandling: 'merge',
      replaceUrl: true
    });
  }

  private persistSeenSubmitterUpdateKeys(): void {
    const entries = Array.from(this.seenSubmitterUpdateKeys).slice(-100);
    localStorage.setItem(this.seenSubmitterUpdateStorageKey, JSON.stringify(entries));
  }
}
