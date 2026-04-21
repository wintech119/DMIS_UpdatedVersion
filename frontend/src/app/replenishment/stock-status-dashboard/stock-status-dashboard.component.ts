import { CommonModule } from '@angular/common';
import { Component, OnInit, OnDestroy, DestroyRef, inject, signal, computed } from '@angular/core';
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
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin, Subject, Subscription } from 'rxjs';
import { debounceTime } from 'rxjs/operators';
import { HttpErrorResponse } from '@angular/common/http';
import { AppAccessService } from '../../core/app-access.service';
import { AuthRbacService } from '../services/auth-rbac.service';
import { ReplenishmentService, ActiveEvent, Warehouse, NeedsListDuplicateSummary } from '../services/replenishment.service';
import { DataFreshnessService } from '../services/data-freshness.service';
import { DashboardDataService, DashboardDataOptions } from '../services/dashboard-data.service';
import { DmisNotificationService } from '../services/notification.service';
import {
  StockStatusItem,
  formatTimeToStockout,
  EventPhase,
  SeverityLevel,
  FreshnessLevel,
  WarehouseStockGroup,
  DisplaySeverity,
  DisplayStatus,
  PhaseWindowsResponse
} from '../models/stock-status.model';
import {
  ExternalUpdateSummary,
  NeedsListItem,
  NeedsListResponse,
  NeedsListSummary,
  NeedsListSummaryStatus
} from '../models/needs-list.model';
import { formatStatusLabel } from '../needs-list-review/status-label.util';
import { TimeToStockoutComponent, TimeToStockoutData } from '../time-to-stockout/time-to-stockout.component';
import { PhaseSelectDialogComponent } from '../phase-select-dialog/phase-select-dialog.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { toDisplaySeverity, toDisplayStatus, phaseToIntervalMs } from './utils/display-mappers';
import { ScopePickerDialogComponent, ScopePickerDialogResult } from './dialogs/scope-picker-dialog.component';
import { DuplicateGuardDialogComponent, DuplicateGuardDialogResult } from './dialogs/duplicate-guard-dialog.component';
import { LowConfidenceAckDialogComponent } from './dialogs/low-confidence-ack-dialog.component';
import { PhaseWindowsDialogComponent } from './dialogs/phase-windows-dialog.component';


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
    DmisEmptyStateComponent,
  ],
  templateUrl: './stock-status-dashboard.component.html',
  styleUrl: './stock-status-dashboard.component.scss'
})
export class StockStatusDashboardComponent implements OnInit, OnDestroy {
  private replenishmentService = inject(ReplenishmentService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private dialog = inject(MatDialog);
  private readonly appAccess = inject(AppAccessService);
  private readonly auth = inject(AuthRbacService);
  private destroyRef = inject(DestroyRef);
  private dataFreshnessService = inject(DataFreshnessService);
  private dashboardDataService = inject(DashboardDataService);
  private notificationService = inject(DmisNotificationService);

  readonly phaseOptions: EventPhase[] = ['SURGE', 'STABILIZED', 'BASELINE'];
  // Internal severity filter domain (4 buckets). Kept for the
  // DashboardDataOptions/selector contract so business logic is unchanged.
  readonly severityOptions: SeverityLevel[] = ['CRITICAL', 'WARNING', 'WATCH', 'OK'];
  // Display-boundary severity chip list (3 buckets). WATCH folds into WARNING,
  // OK folds into GOOD. This is what renders in the UI filter row.
  readonly displaySeverityOptions: DisplaySeverity[] = ['CRITICAL', 'WARNING', 'GOOD'];

  // Phase-aware refresh + CTA gate signals (new UI slices only).
  readonly phaseSignal = signal<EventPhase>('BASELINE');
  readonly refreshIntervalMs = computed(() => phaseToIntervalMs(this.phaseSignal()));
  readonly phaseWindows = signal<PhaseWindowsResponse | null>(null);
  readonly canManagePhaseWindows = computed(() => !!this.phaseWindows()?.manageable_by_active_tenant);
  readonly ctaInFlight = signal(false);

  // Safe poll loop state.
  private pollInFlight = false;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private visibilityListener: (() => void) | null = null;
  private readonly manualRefresh$ = new Subject<void>();
  private manualRefreshSub: Subscription | null = null;
  private retryAfterMs: number | null = null;

  // Current context
  activeEvent: ActiveEvent | null = null;
  allWarehouses: Warehouse[] = [];
  selectedWarehouseIds: number[] = []; // Empty = all warehouses

  // View mode
  viewMode: 'multi' | 'single' = 'multi';
  canAccessReviewQueue = false;
  mySubmissionUpdates: NeedsListResponse[] = [];
  myNeedsLists: NeedsListResponse[] = [];
  private myNeedsListSummariesCache: NeedsListSummary[] = [];
  myNeedsListsCollapsed = false;
  private readonly myNeedsListOpenStatuses: string[] = [
    'DRAFT',
    'MODIFIED',
    'RETURNED',
    'SUBMITTED',
    'PENDING_APPROVAL',
    'PENDING',
    'UNDER_REVIEW',
    'APPROVED',
    'IN_PROGRESS',
    'IN_PREPARATION',
    'DISPATCHED',
    'RECEIVED',
    'FULFILLED',
    'COMPLETED',
    'REJECTED',
    'SUPERSEDED',
    'CANCELLED'
  ];
  private readonly myNeedsListRevisionStatuses = new Set(['DRAFT', 'MODIFIED', 'RETURNED']);
  private readonly expandedMyNeedsListKeys = new Set<string>();

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
  private readonly myNeedsListsCollapsedStorageKey = 'dmis_stock_dashboard_my_needs_lists_collapsed';
  private readonly seenSubmitterUpdateStorageKeyPrefix = 'dmis_needs_list_submitter_updates_seen';
  private loadedSeenSubmitterUpdateStorageKey: string | null = null;
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
    this.loadMyNeedsListsCollapsedState();
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

    this.syncAuthContext();
    this.loadFilterState();
    this.autoLoadDashboard();

    // Listen for refresh requests from the freshness banner
    this.dataFreshnessService.onRefreshRequested$().pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(() => {
      this.triggerManualRefresh();
    });

    // Debounced manual refresh (300ms) to avoid thundering-herd when users
    // click refresh repeatedly.
    this.manualRefreshSub = this.manualRefresh$
      .pipe(debounceTime(300), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => {
        this.dashboardDataService.invalidateCache();
        this.loadMultiWarehouseStatus();
      });

    // Pause polling when the tab is hidden, resume when visible.
    if (typeof document !== 'undefined') {
      this.visibilityListener = () => {
        if (document.hidden) {
          this.stopPollTimer();
        } else {
          this.schedulePoll();
        }
      };
      document.addEventListener('visibilitychange', this.visibilityListener);
    }
  }

  ngOnDestroy(): void {
    this.stopPollTimer();
    if (this.visibilityListener && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.visibilityListener);
    }
    this.manualRefreshSub?.unsubscribe();
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
          this.activeEvent = this.resolveRequestedEventContext(event);
          this.phaseSignal.set((this.activeEvent.phase as EventPhase) || 'BASELINE');
        } else {
          this.activeEvent = null;
        }
        this.allWarehouses = warehouses;

        // If no active event, stop loading and show empty state
        if (!event) {
          this.loading = false;
          this.phaseWindows.set(null);
          return;
        }

        // Phase windows are event-scoped in the backend contract; defer the
        // call until we know the active event_id. Without an event, the
        // endpoint does not exist.
        this.loadPhaseWindows();

        // Load stock status for all warehouses, then kick off the poll loop.
        this.loadMultiWarehouseStatus();
        this.schedulePoll();
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
        this.onRefreshComplete();
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
        this.onRefreshComplete(error instanceof HttpErrorResponse ? error : undefined);
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
      this.phaseSignal.set(newPhase);
      this.dashboardDataService.invalidateCache();
      this.loadMultiWarehouseStatus();
      this.schedulePoll();
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

  /**
   * Legacy entry point. Kept only so existing callers continue to work;
   * all UI bindings should call `generateNeedsListWithGates()` directly.
   */
  generateNeedsList(warehouseId?: number): void {
    this.generateNeedsListWithGates('legacy', warehouseId);
  }

  /**
   * Single CTA path for creating a needs list. Enforces (in order):
   *   1. Scope: event + warehouse must be resolved (opens ScopePickerDialog if missing)
   *   2. Duplicate check: `checkActiveNeedsLists` → DuplicateGuardDialog if any
   *   3. Low-confidence ack: LowConfidenceAckDialog when scope has LOW confidence
   *   4. Navigate to wizard with queryParams
   *
   * All three UI triggers (hero, mobile FAB, warehouse card) route through
   * this method. Backend remains the authoritative enforcement layer; the
   * dialogs on steps 2 and 3 are UX aids only.
   */
  generateNeedsListWithGates(
    source: 'hero' | 'fab' | 'warehouse-card' | 'legacy',
    warehouseId?: number | null
  ): void {
    if (!this.activeEvent) {
      this.notificationService.showWarning('No active event. Cannot create a needs list.');
      return;
    }
    if (this.ctaInFlight()) {
      return;
    }

    const preselected = warehouseId ?? this.selectedWarehouseId ?? (
      this.selectedWarehouseIds.length === 1 ? this.selectedWarehouseIds[0] : null
    );

    if (preselected == null) {
      this.openScopePicker(source);
      return;
    }

    this.runGateChain(preselected);
  }

  private openScopePicker(source: 'hero' | 'fab' | 'warehouse-card' | 'legacy'): void {
    if (!this.allWarehouses.length) {
      this.notificationService.showWarning('No warehouses are available to create a needs list.');
      return;
    }
    const ref = this.dialog.open(ScopePickerDialogComponent, {
      data: {
        availableWarehouses: this.allWarehouses,
        preselectedWarehouseId: this.selectedWarehouseId
      },
      ariaLabel: 'Select warehouse for needs list'
    });
    ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result: ScopePickerDialogResult | undefined) => {
      if (!result) return;
      this.runGateChain(result.warehouseId, source);
    });
  }

  private runGateChain(
    warehouseId: number,
    _source: 'hero' | 'fab' | 'warehouse-card' | 'legacy' = 'legacy'
  ): void {
    if (!this.activeEvent) return;

    this.ctaInFlight.set(true);

    const eventId = this.activeEvent.event_id;
    const phase = String(this.activeEvent.phase);

    this.replenishmentService
      .checkActiveNeedsLists({ eventId, warehouseId, phase })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (duplicates) => {
          if (duplicates && duplicates.length > 0) {
            this.openDuplicateGuard(duplicates, warehouseId);
            return;
          }
          this.runLowConfidenceGate(warehouseId);
        },
        error: () => {
          // Backend still validates at submission — fall through to navigation.
          this.runLowConfidenceGate(warehouseId);
        }
      });
  }

  private openDuplicateGuard(duplicates: NeedsListDuplicateSummary[], warehouseId: number): void {
    const warehouseName = this.warehouseNameFor(warehouseId);
    const ref = this.dialog.open(DuplicateGuardDialogComponent, {
      data: {
        duplicates,
        warehouseName,
        phase: String(this.activeEvent?.phase ?? '')
      },
      ariaLabel: 'Duplicate needs list warning'
    });
    ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result: DuplicateGuardDialogResult) => {
      if (!result) {
        this.ctaInFlight.set(false);
        return;
      }
      if (result.action === 'open') {
        this.ctaInFlight.set(false);
        this.router.navigate(['/replenishment/needs-list', result.needsListId, 'review']);
        return;
      }
      this.runLowConfidenceGate(warehouseId);
    });
  }

  private runLowConfidenceGate(warehouseId: number): void {
    const group = this.warehouseGroups.find((g) => g.warehouse_id === warehouseId);
    const lowConfItem = group?.items?.find((item) => item.confidence?.level === 'LOW');

    if (!lowConfItem) {
      this.navigateToWizard(warehouseId);
      return;
    }

    const reasons = Array.from(
      new Set(
        (group?.items ?? [])
          .filter((it) => it.confidence?.level === 'LOW')
          .flatMap((it) => it.confidence?.reasons ?? [])
      )
    );

    const ref = this.dialog.open(LowConfidenceAckDialogComponent, {
      data: {
        warehouseName: this.warehouseNameFor(warehouseId),
        reasons
      },
      ariaLabel: 'Low-confidence acknowledgement'
    });
    ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef)).subscribe((proceed?: boolean) => {
      if (!proceed) {
        this.ctaInFlight.set(false);
        return;
      }
      this.navigateToWizard(warehouseId);
    });
  }

  private navigateToWizard(warehouseId: number): void {
    this.ctaInFlight.set(false);
    if (!this.activeEvent) return;
    this.router.navigate(['/replenishment/needs-list-wizard'], {
      queryParams: {
        event_id: this.activeEvent.event_id,
        event_name: this.activeEvent.event_name,
        warehouse_id: warehouseId,
        phase: this.activeEvent.phase
      }
    });
  }

  private warehouseNameFor(warehouseId: number): string {
    const warehouse = this.allWarehouses.find((w) => w.warehouse_id === warehouseId);
    if (warehouse?.warehouse_name) {
      return warehouse.warehouse_name;
    }
    const group = this.warehouseGroups.find((g) => g.warehouse_id === warehouseId);
    return group?.warehouse_name ?? `Warehouse ${warehouseId}`;
  }

  // -- Phase windows --------------------------------------------------

  loadPhaseWindows(): void {
    const eventId = this.activeEvent?.event_id;
    if (!eventId) {
      this.phaseWindows.set(null);
      return;
    }
    this.replenishmentService
      .getPhaseWindows(eventId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (response) => this.phaseWindows.set(response),
        error: () => this.phaseWindows.set(null)
      });
  }

  openPhaseWindowsDialog(): void {
    const current = this.phaseWindows();
    const eventId = this.activeEvent?.event_id;
    if (!current || !current.manageable_by_active_tenant || !eventId) {
      return;
    }
    const ref = this.dialog.open(PhaseWindowsDialogComponent, {
      data: { eventId, windows: current.windows },
      ariaLabel: 'Edit phase windows'
    });
    // Always refetch — the dialog may have made partial saves before being
    // closed, and the projected `windows` record must reflect server truth.
    ref
      .afterClosed()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.loadPhaseWindows());
  }

  // -- Safe poll loop --------------------------------------------------

  /**
   * Schedule the next auto-refresh based on the current phase. Honors the
   * in-flight guard (to avoid overlapping calls), pauses when the tab is
   * hidden, and respects `Retry-After` when a prior call returned 429.
   */
  private schedulePoll(): void {
    this.stopPollTimer();
    if (typeof document !== 'undefined' && document.hidden) {
      return;
    }
    const baseInterval = this.refreshIntervalMs();
    const delay = this.retryAfterMs ?? baseInterval;
    this.retryAfterMs = null;
    this.pollTimer = setTimeout(() => this.pollTick(), delay);
  }

  private stopPollTimer(): void {
    if (this.pollTimer != null) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private pollTick(): void {
    if (this.pollInFlight) {
      this.schedulePoll();
      return;
    }
    if (typeof document !== 'undefined' && document.hidden) {
      return;
    }
    if (!this.activeEvent) {
      this.schedulePoll();
      return;
    }
    this.pollInFlight = true;
    this.dashboardDataService.invalidateCache();
    this.loadMultiWarehouseStatus();
    // `loadMultiWarehouseStatus` clears pollInFlight via onRefreshComplete().
  }

  private onRefreshComplete(error?: HttpErrorResponse): void {
    this.pollInFlight = false;
    if (error && error.status === 429) {
      const retryHeader = error.headers?.get?.('Retry-After');
      const seconds = Number(retryHeader);
      if (Number.isFinite(seconds) && seconds > 0) {
        this.retryAfterMs = Math.min(seconds * 1000, 60 * 60 * 1000);
      }
    }
    this.schedulePoll();
  }

  triggerManualRefresh(): void {
    this.manualRefresh$.next();
  }

  // -- Display mappers (exposed to template) ---------------------------

  displaySeverity(severity: SeverityLevel | undefined): DisplaySeverity {
    return toDisplaySeverity(severity ?? 'OK');
  }

  displayStatus(status: string | undefined | null): DisplayStatus {
    return toDisplayStatus(status);
  }

  getDisplaySeverityClass(severity: SeverityLevel | undefined): string {
    return `display-severity-${this.displaySeverity(severity).toLowerCase()}`;
  }

  /**
   * Badge CSS class for stock-status pills at the display boundary.
   * Always returns one of `badge-critical`, `badge-warning`, `badge-good`.
   * Prevents raw WATCH/OK leakage into the rendered DOM.
   */
  getDisplayBadgeClass(severity: SeverityLevel | undefined): string {
    return `badge-${this.displaySeverity(severity).toLowerCase()}`;
  }

  /** Filter chip CSS class at the display boundary (3-bucket). */
  getDisplayChipClass(bucket: DisplaySeverity): string {
    return `chip-${bucket.toLowerCase()}`;
  }

  /**
   * Expand a display-severity bucket into the internal SeverityLevel values
   * that the dashboard selector/filter operates on. WATCH is shown under
   * WARNING in the UI; OK is shown under GOOD.
   */
  private expandDisplaySeverity(bucket: DisplaySeverity): SeverityLevel[] {
    switch (bucket) {
      case 'CRITICAL': return ['CRITICAL'];
      case 'WARNING':  return ['WARNING', 'WATCH'];
      case 'GOOD':     return ['OK'];
    }
  }

  isDisplaySeveritySelected(bucket: DisplaySeverity): boolean {
    // A bucket is "selected" when every internal severity it represents is
    // currently in the filter. Partial membership is treated as unselected
    // so the chip's UI state stays binary.
    const members = this.expandDisplaySeverity(bucket);
    return members.every((s) => this.selectedSeverities.includes(s));
  }

  onDisplaySeveritySelectionChange(bucket: DisplaySeverity, change: MatChipSelectionChange): void {
    if (!change.isUserInput) {
      return;
    }
    this.setDisplaySeveritySelection(bucket, change.selected);
    this.onFiltersChanged();
  }

  private setDisplaySeveritySelection(bucket: DisplaySeverity, selected: boolean): void {
    const members = this.expandDisplaySeverity(bucket);
    for (const severity of members) {
      const idx = this.selectedSeverities.indexOf(severity);
      if (selected && idx < 0) {
        this.selectedSeverities.push(severity);
      } else if (!selected && idx >= 0) {
        this.selectedSeverities.splice(idx, 1);
      }
    }
  }

  getDisplaySeverityTooltip(bucket: DisplaySeverity): string {
    switch (bucket) {
      case 'CRITICAL':
        return 'CRITICAL: Less than 8 hours of stock remaining. Immediate replenishment action required using transfers (Horizon A).';
      case 'WARNING':
        return 'WARNING: Less than 72 hours of stock remaining. Includes items under 24h (act soon) and under 72h (plan ahead).';
      case 'GOOD':
        return 'GOOD: More than 72 hours of stock remaining. Stock levels are healthy.';
    }
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

  getStockItemTooltip(item: StockStatusItem): string {
    return item.item_name?.trim() || `Item ${item.item_id}`;
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

  private saveMyNeedsListsCollapsedState(): void {
    try {
      localStorage.setItem(
        this.myNeedsListsCollapsedStorageKey,
        JSON.stringify(this.myNeedsListsCollapsed)
      );
    } catch {
      // localStorage may be unavailable; keep in-memory state only.
    }
  }

  private loadMyNeedsListsCollapsedState(): void {
    try {
      const saved = localStorage.getItem(this.myNeedsListsCollapsedStorageKey);
      if (!saved) {
        return;
      }
      const parsed = JSON.parse(saved);
      if (typeof parsed === 'boolean') {
        this.myNeedsListsCollapsed = parsed;
      }
    } catch {
      // Ignore malformed localStorage data and keep defaults.
    }
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

  private syncAuthContext(): void {
    // Mirror backend actor ordering (user_id first, then username) so
    // submitter update matching remains stable across mixed identifiers.
    this.setCurrentUserRef(this.auth.actorRef());
    this.canAccessReviewQueue = this.appAccess.canAccessNavKey('replenishment.review');
    this.loadMyNeedsLists();
    this.loadMySubmissionUpdates();
  }

  private setCurrentUserRef(userRef: string | null): void {
    const nextRef = String(userRef ?? '').trim() || null;
    if (this.currentUserRef === nextRef) {
      return;
    }
    this.currentUserRef = nextRef;
    this.loadSeenSubmitterUpdateKeys();
  }

  private getSeenSubmitterUpdateStorageKey(): string | null {
    const userRef = String(this.currentUserRef ?? '').trim().toLowerCase();
    if (!userRef) {
      return null;
    }
    return `${this.seenSubmitterUpdateStorageKeyPrefix}:${userRef}`;
  }

  private resolveRequestedEventContext(event: ActiveEvent): ActiveEvent {
    // Only honor wizard overrides when they match the fetched active event context.
    if (this.requestedEventId != null && this.requestedEventId !== event.event_id) {
      return { ...event };
    }

    const selectedPhase = this.requestedPhase ?? (event.phase as EventPhase);
    return {
      ...event,
      event_id: event.event_id,
      phase: selectedPhase
    };
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

  get myNeedsListSummaries(): NeedsListSummary[] {
    return this.myNeedsListSummariesCache;
  }

  openNeedsListUpdate(row: NeedsListResponse): void {
    if (!row.needs_list_id) {
      return;
    }
    this.router.navigate(['/replenishment/needs-list', row.needs_list_id, 'review']);
  }

  openMyNeedsList(row: NeedsListResponse, event?: Event): void {
    event?.stopPropagation();
    this.openNeedsListUpdate(row);
  }

  canReviseNeedsList(row: NeedsListResponse): boolean {
    return this.myNeedsListRevisionStatuses.has(String(row.status ?? '').toUpperCase());
  }

  reviseMyNeedsList(row: NeedsListResponse, event?: Event): void {
    event?.stopPropagation();
    const warehouseId = row.warehouse_id ?? row.warehouse_ids?.[0];
    this.router.navigate(['/replenishment/needs-list-wizard'], {
      queryParams: {
        needs_list_id: row.needs_list_id,
        event_id: row.event_id,
        event_name: row.event_name,
        warehouse_id: warehouseId,
        phase: row.phase
      }
    });
  }

  /**
   * Cross-page-shared needs-list status label (kept for non-dashboard
   * surfaces that pass status strings through this helper). Dashboard-owned
   * status pills must use `displayStatus()` instead to stay on the FR02.93
   * display vocabulary.
   */
  statusLabel(status: string | undefined): string {
    return formatStatusLabel(status);
  }

  toggleMyNeedsListsCollapsed(event?: Event): void {
    event?.stopPropagation();
    this.myNeedsListsCollapsed = !this.myNeedsListsCollapsed;
    this.saveMyNeedsListsCollapsedState();
  }

  isNeedsListExpanded(row: NeedsListResponse): boolean {
    const key = this.myNeedsListKey(row);
    return key ? this.expandedMyNeedsListKeys.has(key) : false;
  }

  toggleNeedsListExpanded(row: NeedsListResponse, event?: Event): void {
    event?.stopPropagation();
    const key = this.myNeedsListKey(row);
    if (!key) {
      return;
    }
    if (this.expandedMyNeedsListKeys.has(key)) {
      this.expandedMyNeedsListKeys.delete(key);
    } else {
      this.expandedMyNeedsListKeys.add(key);
    }
  }

  remainingNeedsListItems(row: NeedsListResponse): NeedsListItem[] {
    return (row.items ?? []).filter((item) => this.itemRemainingQty(item, row) > 0);
  }

  fulfilledNeedsListItems(row: NeedsListResponse): NeedsListItem[] {
    return (row.items ?? []).filter((item) => this.isItemFulfilled(item, row));
  }

  needsListProgressSummary(row: NeedsListResponse): string {
    const remainingCount = this.remainingNeedsListItems(row).length;
    const resolvedCount = this.fulfilledNeedsListItems(row).length;
    return `Remaining ${remainingCount} • Resolved ${resolvedCount}`;
  }

  needsListItemLabel(item: NeedsListItem): string {
    return String(item.item_name || `Item ${item.item_id}`);
  }

  needsListItemRemainingQty(item: NeedsListItem, row: NeedsListResponse): number {
    return this.itemRemainingQty(item, row);
  }

  private loadMyNeedsLists(): void {
    if (!this.currentUserRef) {
      this.setMyNeedsLists([]);
      this.expandedMyNeedsListKeys.clear();
      return;
    }

    this.replenishmentService
      .listNeedsLists(this.myNeedsListOpenStatuses, { mine: true, includeClosed: true })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (data) => {
          const rows = [...(data.needs_lists ?? [])]
            .sort((a, b) => this.updateTimestamp(b) - this.updateTimestamp(a))
            .slice(0, 8);
          this.setMyNeedsLists(rows);
          this.syncExpandedNeedsListKeys(rows);
        },
        error: () => {
          // Keep dashboard functional when this optional feed is unavailable.
          this.setMyNeedsLists([]);
          this.expandedMyNeedsListKeys.clear();
        }
      });
  }

  private setMyNeedsLists(rows: NeedsListResponse[]): void {
    this.myNeedsLists = [...rows];
    this.myNeedsListSummariesCache = this.myNeedsLists.map((row) => this.toNeedsListSummary(row));
  }

  private loadMySubmissionUpdates(): void {
    if (!this.currentUserRef) {
      this.mySubmissionUpdates = [];
      return;
    }

    this.replenishmentService
      .listNeedsLists(['APPROVED', 'RETURNED', 'REJECTED'], { mine: true })
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
    const status = row.status ?? '';
    const activityAt = row.approved_at ?? row.reviewed_at ?? row.updated_at ?? row.submitted_at ?? '';
    const needsListId = (row.needs_list_id ?? '').trim();

    if (needsListId) {
      return [needsListId, status, activityAt].join('|');
    }

    const rowRecord = row as unknown as Record<string, unknown>;
    const runtimeId = [rowRecord['id'], rowRecord['uuid']]
      .map((value) => (typeof value === 'string' ? value.trim() : ''))
      .find((value) => value.length > 0);

    const fallbackIdentity = runtimeId || row.needs_list_no || this.stableRowFingerprint(row);
    return [needsListId, status, activityAt, fallbackIdentity].join('|');
  }

  private myNeedsListKey(row: NeedsListResponse): string | null {
    const needsListId = String(row.needs_list_id ?? '').trim();
    if (needsListId) {
      return needsListId;
    }
    const needsListNo = String(row.needs_list_no ?? '').trim();
    if (needsListNo) {
      return needsListNo;
    }
    return null;
  }

  private syncExpandedNeedsListKeys(rows: NeedsListResponse[]): void {
    const keys = new Set(
      rows
        .map((row) => this.myNeedsListKey(row))
        .filter((key): key is string => typeof key === 'string' && key.length > 0)
    );
    for (const existingKey of Array.from(this.expandedMyNeedsListKeys)) {
      if (!keys.has(existingKey)) {
        this.expandedMyNeedsListKeys.delete(existingKey);
      }
    }
  }

  private isItemFulfilled(item: NeedsListItem, row: NeedsListResponse): boolean {
    const listStatus = String(row.status ?? '').toUpperCase();
    if (listStatus === 'FULFILLED' || listStatus === 'COMPLETED') {
      return true;
    }

    const fulfillmentStatus = String(item.fulfillment_status ?? '').toUpperCase();
    if (fulfillmentStatus === 'FULFILLED' || fulfillmentStatus === 'RECEIVED') {
      return true;
    }

    const gapQty = Math.max(this.toFiniteNumber(item.gap_qty), 0);
    // Dashboard progress treats items with no remaining gap as fulfilled so
    // needsListProgressSummary/itemRemainingQty both resolve to zero remaining.
    if (gapQty <= 0) {
      return true;
    }

    const fulfilledQty = Math.max(this.toFiniteNumber(item.fulfilled_qty), 0);
    return fulfilledQty >= gapQty;
  }

  private itemRemainingQty(item: NeedsListItem, row: NeedsListResponse): number {
    if (this.isItemFulfilled(item, row)) {
      return 0;
    }
    const gapQty = Math.max(this.toFiniteNumber(item.gap_qty), 0);
    const fulfilledQty = Math.max(this.toFiniteNumber(item.fulfilled_qty), 0);
    return Math.max(gapQty - fulfilledQty, 0);
  }

  private toFiniteNumber(value: unknown): number {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  private stableRowFingerprint(row: NeedsListResponse): string {
    const normalize = (value: unknown): unknown => {
      if (Array.isArray(value)) {
        return value.map((entry) => normalize(entry));
      }
      if (value && typeof value === 'object') {
        const record = value as Record<string, unknown>;
        const normalized: Record<string, unknown> = {};
        for (const key of Object.keys(record).sort()) {
          normalized[key] = normalize(record[key]);
        }
        return normalized;
      }
      return value;
    };

    try {
      return JSON.stringify(normalize(row));
    } catch {
      return String(row.needs_list_no ?? row.status ?? '');
    }
  }

  private toNeedsListSummary(row: NeedsListResponse): NeedsListSummary {
    const status = this.toSummaryStatus(row.status);
    const items = row.items ?? [];
    const fulfilledItems = items.filter((item) => this.isItemFulfilled(item, row)).length;
    const totalItems = items.length;
    const horizonSummary = {
      horizon_a: { count: 0, estimated_value: 0 },
      horizon_b: { count: 0, estimated_value: 0 },
      horizon_c: { count: 0, estimated_value: 0 }
    };

    for (const item of items) {
      const unitCost = Number(item.procurement?.est_unit_cost ?? 0) || 0;
      const cTotal = Number(item.procurement?.est_total_cost ?? 0) || 0;
      const horizonA = Number(item.horizon?.A?.recommended_qty ?? 0) || 0;
      const horizonB = Number(item.horizon?.B?.recommended_qty ?? 0) || 0;
      const horizonC = Number(item.horizon?.C?.recommended_qty ?? 0) || 0;

      if (horizonA > 0) {
        horizonSummary.horizon_a.count += 1;
        horizonSummary.horizon_a.estimated_value += unitCost > 0 ? horizonA * unitCost : 0;
      }
      if (horizonB > 0) {
        horizonSummary.horizon_b.count += 1;
        horizonSummary.horizon_b.estimated_value += unitCost > 0 ? horizonB * unitCost : 0;
      }
      if (horizonC > 0) {
        horizonSummary.horizon_c.count += 1;
        horizonSummary.horizon_c.estimated_value += unitCost > 0 ? horizonC * unitCost : cTotal;
      }
    }

    const externalUpdates: ExternalUpdateSummary[] = items
      .filter((item) => (Number(item.fulfilled_qty ?? 0) || 0) > 0)
      .map((item) => {
        const fulfilledQty = Math.max(Number(item.fulfilled_qty ?? 0) || 0, 0);
        const gapQty = Math.max(Number(item.gap_qty ?? 0) || 0, 0);
        const originalQty = fulfilledQty + gapQty;

        let sourceType: 'DONATION' | 'TRANSFER' | 'PROCUREMENT' = 'TRANSFER';
        let sourceReference = 'External Supply';
        if ((Number(item.inbound_donation_qty ?? 0) || 0) > 0) {
          sourceType = 'DONATION';
          sourceReference = 'Inbound Donation';
        } else if ((Number(item.inbound_procurement_qty ?? 0) || 0) > 0) {
          sourceType = 'PROCUREMENT';
          sourceReference = 'Procurement Pipeline';
        } else if ((Number(item.inbound_transfer_qty ?? 0) || 0) > 0) {
          sourceType = 'TRANSFER';
          sourceReference = 'Inbound Transfer';
        }

        return {
          item_name: this.needsListItemLabel(item),
          original_qty: originalQty,
          covered_qty: fulfilledQty,
          remaining_qty: Math.max(originalQty - fulfilledQty, 0),
          source_type: sourceType,
          source_reference: sourceReference,
          updated_at: row.updated_at ?? null
        };
      });

    const warehouseId = row.warehouse_id ?? row.warehouse_ids?.[0] ?? null;
    return {
      id: String(row.needs_list_id ?? ''),
      reference_number: String(row.needs_list_no ?? 'N/A'),
      warehouse: {
        id: warehouseId,
        name: row.warehouses?.[0]?.warehouse_name || (warehouseId ? `Warehouse ${warehouseId}` : 'Unknown'),
        code: warehouseId ? String(warehouseId) : ''
      },
      event: {
        id: row.event_id ?? null,
        name: row.event_name || (row.event_id ? `Event ${row.event_id}` : 'Unknown'),
        phase: (row.phase || 'BASELINE') as EventPhase
      },
      status,
      total_items: totalItems,
      fulfilled_items: fulfilledItems,
      remaining_items: Math.max(totalItems - fulfilledItems, 0),
      horizon_summary: horizonSummary,
      submitted_at: row.submitted_at ?? null,
      approved_at: row.approved_at ?? null,
      last_updated_at: row.updated_at ?? row.submitted_at ?? row.created_at ?? null,
      superseded_by_id: row.superseded_by_needs_list_id ?? row.superseded_by ?? null,
      supersedes_id: row.supersedes_needs_list_ids?.[0] ?? null,
      has_external_updates: externalUpdates.length > 0,
      external_update_summary: externalUpdates,
      data_version: `${row.needs_list_id}|${row.updated_at || ''}|${status}`,
      created_by: {
        id: null,
        name: row.created_by ?? ''
      }
    };
  }

  private toSummaryStatus(status: string | undefined): NeedsListSummaryStatus {
    const originalStatus = status;
    const normalized = String(status || '').trim().toUpperCase();
    if (normalized === 'SUBMITTED' || normalized === 'PENDING' || normalized === 'UNDER_REVIEW') {
      return 'PENDING_APPROVAL';
    }
    if (normalized === 'IN_PREPARATION' || normalized === 'DISPATCHED' || normalized === 'RECEIVED') {
      return 'IN_PROGRESS';
    }
    if (normalized === 'COMPLETED') {
      return 'FULFILLED';
    }
    if (
      normalized === 'DRAFT' ||
      normalized === 'MODIFIED' ||
      normalized === 'RETURNED' ||
      normalized === 'PENDING_APPROVAL' ||
      normalized === 'APPROVED' ||
      normalized === 'REJECTED' ||
      normalized === 'IN_PROGRESS' ||
      normalized === 'FULFILLED' ||
      normalized === 'SUPERSEDED' ||
      normalized === 'CANCELLED'
    ) {
      return normalized;
    }
    console.warn(
      '[StockStatusDashboard] Unrecognized needs list status in toSummaryStatus:',
      originalStatus
    );
    return 'DRAFT';
  }

  private notifySubmitterStatusUpdates(rows: NeedsListResponse[]): void {
    for (const row of rows) {
      const key = this.updateNotificationKey(row);
      if (!key || this.seenSubmitterUpdateKeys.has(key)) {
        continue;
      }

      const listRef = row.needs_list_no ?? 'Needs list';
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
    const scopedKey = this.getSeenSubmitterUpdateStorageKey();
    if (!scopedKey) {
      this.loadedSeenSubmitterUpdateStorageKey = null;
      this.seenSubmitterUpdateKeys = new Set();
      return;
    }
    if (this.loadedSeenSubmitterUpdateStorageKey === scopedKey) {
      return;
    }
    this.loadedSeenSubmitterUpdateStorageKey = scopedKey;
    this.seenSubmitterUpdateKeys = new Set();

    try {
      let raw = localStorage.getItem(scopedKey);
      if (!raw) {
        // One-time migration from pre-user-scoped storage key.
        const legacyRaw = localStorage.getItem(this.seenSubmitterUpdateStorageKeyPrefix);
        if (legacyRaw) {
          raw = legacyRaw;
          localStorage.setItem(scopedKey, legacyRaw);
          localStorage.removeItem(this.seenSubmitterUpdateStorageKeyPrefix);
        }
      }
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
    const scopedKey = this.getSeenSubmitterUpdateStorageKey();
    if (!scopedKey) {
      return;
    }

    try {
      const entries = Array.from(this.seenSubmitterUpdateKeys).slice(-100);
      localStorage.setItem(scopedKey, JSON.stringify(entries));
    } catch {
      // localStorage may be full or unavailable – notifications still work in-memory.
    }
  }
}
