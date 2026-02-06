import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
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
import { Router } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ReplenishmentService, ActiveEvent, Warehouse } from '../services/replenishment.service';
import { StockStatusItem, formatTimeToStockout, EventPhase, SeverityLevel, FreshnessLevel, WarehouseStockGroup, calculateSeverity } from '../models/stock-status.model';
import { NeedsListItem } from '../models/needs-list.model';
import { TimeToStockoutComponent, TimeToStockoutData } from '../time-to-stockout/time-to-stockout.component';
import { PhaseSelectDialogComponent } from '../phase-select-dialog/phase-select-dialog.component';

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
    TimeToStockoutComponent
  ],
  templateUrl: './stock-status-dashboard.component.html',
  styleUrl: './stock-status-dashboard.component.scss'
})
export class StockStatusDashboardComponent implements OnInit {
  readonly phaseOptions: EventPhase[] = ['SURGE', 'STABILIZED', 'BASELINE'];
  readonly severityOptions: SeverityLevel[] = ['CRITICAL', 'WARNING', 'WATCH', 'OK'];

  // Current context
  activeEvent: ActiveEvent | null = null;
  allWarehouses: Warehouse[] = [];
  selectedWarehouseIds: number[] = []; // Empty = all warehouses

  // View mode
  viewMode: 'multi' | 'single' = 'multi';

  loading = false;
  warehouseGroups: WarehouseStockGroup[] = [];
  private warehouseItemsById: Map<number, StockStatusItem[]> = new Map();
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
        this.errors = [error.error?.errors?.event || error.message || 'Failed to load dashboard data.'];
      }
    });
  }

  /**
   * Load stock status for all warehouses (or filtered warehouses)
   */
  loadMultiWarehouseStatus(): void {
    if (!this.activeEvent) return;

    const warehouseIds = this.selectedWarehouseIds.length > 0
      ? this.selectedWarehouseIds
      : this.allWarehouses.map(w => w.warehouse_id);

    if (warehouseIds.length === 0) {
      this.loading = false;
      this.errors = ['No warehouses available.'];
      return;
    }

    this.loading = true;
    this.replenishmentService.getStockStatusMulti(
      this.activeEvent.event_id,
      warehouseIds,
      this.activeEvent.phase
    ).subscribe({
      next: (data) => {
        const items = this.normalizePreviewItems(data.items);
        this.groupItemsByWarehouse(items, data.warnings ?? []);
        this.loading = false;
      },
      error: (error) => {
        this.loading = false;
        this.errors = [error.message || 'Failed to load stock status.'];
      }
    });
  }

  /**
   * Group items by warehouse and calculate statistics
   */
  private groupItemsByWarehouse(items: StockStatusItem[], warnings: string[]): void {
    // Group items by warehouse_id
    const warehouseMap = new Map<number, StockStatusItem[]>();

    items.forEach(item => {
      const warehouseId = item.warehouse_id;
      if (!warehouseId) return;

      if (!warehouseMap.has(warehouseId)) {
        warehouseMap.set(warehouseId, []);
      }
      warehouseMap.get(warehouseId)!.push(item);
    });

    this.warehouseItemsById = new Map(warehouseMap);

    // Create warehouse groups
    this.warehouseGroups = Array.from(warehouseMap.entries()).map(([warehouseId, warehouseItems]) =>
      this.buildWarehouseGroup(warehouseId, warehouseItems)
    );

    // Sort warehouses by critical count (most critical first)
    this.warehouseGroups.sort((a, b) => b.critical_count - a.critical_count);

    this.warnings = warnings;

    // Extract available categories from all items
    this.availableCategories = [...new Set(
      items
        .map(item => item.category)
        .filter((cat): cat is string => !!cat)
    )].sort();
  }

  private buildWarehouseGroup(warehouseId: number, warehouseItems: StockStatusItem[]): WarehouseStockGroup {
    const warehouseName = warehouseItems[0]?.warehouse_name || `Warehouse ${warehouseId}`;

    // Apply filters and sort to each warehouse's items
    let filteredItems = this.applyFiltersToItems(warehouseItems);
    filteredItems = this.sortItems(filteredItems);

    // Calculate severity counts
    const severityCounts = {
      critical: filteredItems.filter(i => i.severity === 'CRITICAL').length,
      warning: filteredItems.filter(i => i.severity === 'WARNING').length,
      watch: filteredItems.filter(i => i.severity === 'WATCH').length,
      ok: filteredItems.filter(i => i.severity === 'OK').length
    };

    // Overall freshness (worst of all items, regardless of filters)
    const freshnessLevels: FreshnessLevel[] = ['LOW', 'MEDIUM', 'HIGH'];
    const worstFreshness = warehouseItems
      .map(i => i.freshness?.state)
      .filter((f): f is FreshnessLevel => !!f)
      .reduce((worst, current) => {
        const worstIndex = freshnessLevels.indexOf(worst);
        const currentIndex = freshnessLevels.indexOf(current);
        return currentIndex < worstIndex ? current : worst;
      }, 'HIGH' as FreshnessLevel);

    return {
      warehouse_id: warehouseId,
      warehouse_name: warehouseName,
      items: filteredItems,
      critical_count: severityCounts.critical,
      warning_count: severityCounts.warning,
      watch_count: severityCounts.watch,
      ok_count: severityCounts.ok,
      overall_freshness: worstFreshness
    };
  }

  private refreshSingleWarehouseView(): void {
    if (!this.selectedWarehouseId) return;
    const items = this.warehouseItemsById.get(this.selectedWarehouseId);
    if (!items) return;
    this.warehouseGroups = [this.buildWarehouseGroup(this.selectedWarehouseId, items)];
  }

  private normalizePreviewItems(items: NeedsListItem[]): StockStatusItem[] {
    return items.map(item => {
      const parsedStockout = this.parseTimeToStockout(item.time_to_stockout);
      const normalizedFreshness = this.normalizeFreshness(item.freshness);
      const severity = item.severity ?? calculateSeverity(parsedStockout);

      return {
        ...item,
        time_to_stockout_hours: item.time_to_stockout_hours ?? (parsedStockout ?? undefined),
        severity,
        freshness: normalizedFreshness ?? undefined
      } as StockStatusItem;
    });
  }

  private normalizeFreshness(
    freshness: NeedsListItem['freshness']
  ): StockStatusItem['freshness'] | null {
    if (!freshness) return null;
    const state = String(freshness.state).toUpperCase();
    if (state !== 'HIGH' && state !== 'MEDIUM' && state !== 'LOW') {
      return null;
    }
    return {
      ...freshness,
      state: state as FreshnessLevel
    };
  }

  private parseTimeToStockout(value: number | string | undefined): number | null {
    if (value === undefined || value === null || value === 'N/A') {
      return null;
    }
    if (typeof value === 'number') {
      return value;
    }
    const parsed = parseFloat(value);
    return Number.isNaN(parsed) ? null : parsed;
  }

  /**
   * Apply category and severity filters to items
   */
  private applyFiltersToItems(items: StockStatusItem[]): StockStatusItem[] {
    let filtered = [...items];

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

    return filtered;
  }

  /**
   * Reload data when filters change
   */
  onFiltersChanged(): void {
    this.saveFilterState();
    if (this.viewMode === 'multi') {
      this.loadMultiWarehouseStatus();
    } else {
      this.refreshSingleWarehouseView();
    }
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
    // Navigate to single warehouse view (could also be done with routing)
    this.viewMode = 'single';
    this.selectedWarehouseId = warehouseId;

    this.refreshSingleWarehouseView();
  }

  /**
   * Return to multi-warehouse view
   */
  returnToMultiView(): void {
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
}
