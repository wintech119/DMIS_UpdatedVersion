import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  inject, signal, computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatCardModule } from '@angular/material/card';

import {
  MasterColumnConfig,
  MasterRecord,
  MasterTableConfig,
  MasterTone,
  MasterToneRule,
} from '../../models/master-data.models';
import {
  IfrcFamilyLookup,
  IfrcReferenceLookup,
  ItemCategoryLookup,
} from '../../models/item-taxonomy.models';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import { MasterDataService } from '../../services/master-data.service';
import { MasterFormDialogComponent } from '../master-form-dialog/master-form-dialog.component';
import { DmisSkeletonLoaderComponent } from '../../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisEmptyStateComponent } from '../../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisConfirmDialogComponent, ConfirmDialogData } from '../../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { MasterDataAccessService } from '../../services/master-data-access.service';

import { Subject, combineLatest, debounceTime, distinctUntilChanged, tap } from 'rxjs';

interface ResolvedColumnPill {
  label: string;
  icon: string | null;
  tone: MasterTone | null;
  legacyStatus: string | null;
}

@Component({
  selector: 'dmis-master-list',
  standalone: true,
  imports: [
    CommonModule, FormsModule, RouterModule,
    MatTableModule, MatButtonModule, MatIconModule, MatFormFieldModule,
    MatInputModule, MatSelectModule, MatMenuModule, MatTooltipModule,
    MatDialogModule, MatPaginatorModule, MatCardModule,
    DmisSkeletonLoaderComponent, DmisEmptyStateComponent,
  ],
  templateUrl: './master-list.component.html',
  styleUrl: './master-list.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterListComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(MasterDataService);
  private dialog = inject(MatDialog);
  private notify = inject(DmisNotificationService);
  private access = inject(MasterDataAccessService);
  private destroyRef = inject(DestroyRef);
  private breakpointObserver = inject(BreakpointObserver);
  private latestLoadRequestId = 0;
  private itemIfrcFamilyRequestId = 0;
  private itemIfrcReferenceRequestId = 0;
  private pendingDialogQueryAction: 'new' | null = null;

  config = signal<MasterTableConfig | null>(null);
  rows = signal<MasterRecord[]>([]);
  totalCount = signal(0);
  isLoading = signal(true);
  isMobile = signal(false);

  // Filters
  filtersExpanded = signal(false);
  statusFilter = signal<string>('');
  searchText = signal('');
  sortField = signal('');
  sortDirection = signal<'asc' | 'desc'>('asc');
  pageSize = signal(25);
  pageIndex = signal(0);
  itemCategoryFilter = signal<string>('');
  itemIfrcFamilyFilter = signal<string>('');
  itemIfrcReferenceFilter = signal<string>('');
  itemCategoryOptions = signal<ItemCategoryLookup[]>([]);
  itemIfrcFamilyOptions = signal<IfrcFamilyLookup[]>([]);
  itemIfrcReferenceOptions = signal<IfrcReferenceLookup[]>([]);
  itemLookupLoading = signal({
    categories: false,
    families: false,
    references: false,
  });

  private searchSubject = new Subject<string>();
  readonly isItemList = computed(() => this.config()?.tableKey === 'items');
  readonly canCreate = computed(() => {
    const cfg = this.config();
    if (!cfg) {
      return false;
    }
    return this.access.canCreateRoutePath(cfg.routePath, Boolean(cfg.readOnly));
  });
  readonly canEdit = computed(() => {
    const cfg = this.config();
    if (!cfg) {
      return false;
    }
    return this.access.canEditRoutePath(cfg.routePath, Boolean(cfg.readOnly));
  });
  readonly hasRowActions = computed(() => {
    const cfg = this.config();
    if (!cfg || cfg.readOnly) {
      return false;
    }
    return this.canEdit()
      || this.access.canToggleStatusRoutePath(cfg.routePath, true)
      || this.access.canToggleStatusRoutePath(cfg.routePath, false);
  });

  displayedColumns = computed(() => {
    const cfg = this.config();
    if (!cfg) return [];
    const cols = cfg.columns;
    const colNames = cols.map(c => c.field);
    if (this.hasRowActions()) colNames.push('_actions');
    return colNames;
  });

  activeFilterCount = computed(() => {
    let count = 0;
    if (this.statusFilter()) count++;
    if (this.searchText()) count++;
    if (this.sortField()) count++;
    if (this.itemCategoryFilter()) count++;
    if (this.itemIfrcFamilyFilter()) count++;
    if (this.itemIfrcReferenceFilter()) count++;
    return count;
  });

  hasActiveFilters = computed(() => this.activeFilterCount() > 0);
  sortableColumns = computed<MasterColumnConfig[]>(() => {
    const cfg = this.config();
    if (!cfg) return [];
    return cfg.columns.filter((column) => column.sortable);
  });

  ngOnInit(): void {
    this.breakpointObserver.observe([Breakpoints.Handset]).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(result => this.isMobile.set(result.matches));

    combineLatest([this.route.data, this.route.queryParamMap]).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(([data, queryParams]) => {
      const routePath = data['routePath'] as string;
      const cfg = ALL_TABLE_CONFIGS[routePath];
      this.pendingDialogQueryAction = queryParams.get('open') === 'new' ? 'new' : null;
      if (cfg) {
        this.config.set(cfg);
        this.resetItemFiltersForConfig(cfg);
        this.loadData();
        this.handleDialogQueryAction();
      }
    });

    this.searchSubject.pipe(
      tap(search => {
        this.searchText.set(search);
        this.pageIndex.set(0);
      }),
      debounceTime(300),
      distinctUntilChanged(),
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(() => {
      this.loadData();
    });
  }

  private resetItemFiltersForConfig(cfg: MasterTableConfig): void {
    this.itemCategoryFilter.set('');
    this.itemIfrcFamilyFilter.set('');
    this.itemIfrcReferenceFilter.set('');
    this.itemCategoryOptions.set([]);
    this.itemIfrcFamilyOptions.set([]);
    this.itemIfrcReferenceOptions.set([]);

    if (cfg.tableKey !== 'items') {
      return;
    }

    this.loadItemCategoryOptions();
  }

  private loadItemCategoryOptions(): void {
    this.itemLookupLoading.update((state) => ({ ...state, categories: true }));
    this.service.lookupItemCategories().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (items) => {
        this.itemCategoryOptions.set(items);
        this.itemLookupLoading.update((state) => ({ ...state, categories: false }));
      },
      error: () => {
        this.itemCategoryOptions.set([]);
        this.itemLookupLoading.update((state) => ({ ...state, categories: false }));
        this.notify.showError('Failed to load item category filters.');
      },
    });
  }

  private loadItemFamilyOptions(categoryId: string): void {
    const requestId = ++this.itemIfrcFamilyRequestId;
    if (!categoryId) {
      this.itemIfrcFamilyOptions.set([]);
      this.itemLookupLoading.update((state) => ({ ...state, families: false }));
      return;
    }

    this.itemLookupLoading.update((state) => ({ ...state, families: true }));
    this.service.lookupIfrcFamilies({ categoryId }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (items) => {
        if (requestId !== this.itemIfrcFamilyRequestId) return;
        this.itemIfrcFamilyOptions.set(items);
        this.itemLookupLoading.update((state) => ({ ...state, families: false }));
      },
      error: () => {
        if (requestId !== this.itemIfrcFamilyRequestId) return;
        this.itemIfrcFamilyOptions.set([]);
        this.itemLookupLoading.update((state) => ({ ...state, families: false }));
        this.notify.showError('Failed to load IFRC family filters.');
      },
    });
  }

  private loadItemReferenceOptions(familyId: string): void {
    const requestId = ++this.itemIfrcReferenceRequestId;
    if (!familyId) {
      this.itemIfrcReferenceOptions.set([]);
      this.itemLookupLoading.update((state) => ({ ...state, references: false }));
      return;
    }

    this.itemLookupLoading.update((state) => ({ ...state, references: true }));
    this.service.lookupIfrcReferences({
      ifrcFamilyId: familyId,
      limit: 100,
    }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (items) => {
        if (requestId !== this.itemIfrcReferenceRequestId) return;
        this.itemIfrcReferenceOptions.set(items);
        this.itemLookupLoading.update((state) => ({ ...state, references: false }));
      },
      error: () => {
        if (requestId !== this.itemIfrcReferenceRequestId) return;
        this.itemIfrcReferenceOptions.set([]);
        this.itemLookupLoading.update((state) => ({ ...state, references: false }));
        this.notify.showError('Failed to load IFRC reference filters.');
      },
    });
  }

  toggleFilters(): void {
    this.filtersExpanded.update(v => !v);
  }

  clearFilters(): void {
    const hadSearch = !!this.searchText();
    this.statusFilter.set('');
    this.sortField.set('');
    this.sortDirection.set('asc');
    this.itemCategoryFilter.set('');
    this.itemIfrcFamilyFilter.set('');
    this.itemIfrcReferenceFilter.set('');
    this.itemIfrcFamilyOptions.set([]);
    this.itemIfrcReferenceOptions.set([]);
    this.searchSubject.next('');
    if (this.isItemList()) {
      this.loadItemCategoryOptions();
    }
    if (!hadSearch) {
      this.pageIndex.set(0);
      this.loadData();
    }
  }

  onSearchInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.searchSubject.next(value);
  }

  onStatusFilterChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.statusFilter.set(value === 'ALL' ? '' : value);
    this.pageIndex.set(0);
    this.loadData();
  }

  onItemCategoryFilterChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.itemCategoryFilter.set(value);
    this.itemIfrcFamilyFilter.set('');
    this.itemIfrcReferenceFilter.set('');
    this.itemIfrcReferenceOptions.set([]);
    this.pageIndex.set(0);
    this.loadItemFamilyOptions(value);
    this.loadData();
  }

  onItemIfrcFamilyFilterChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.itemIfrcFamilyFilter.set(value);
    this.itemIfrcReferenceFilter.set('');
    this.pageIndex.set(0);
    this.loadItemReferenceOptions(value);
    this.loadData();
  }

  onItemIfrcReferenceFilterChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.itemIfrcReferenceFilter.set(value);
    this.pageIndex.set(0);
    this.loadData();
  }

  onSortFieldChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.sortField.set(value);
    this.pageIndex.set(0);
    if (!value) {
      this.sortDirection.set('asc');
    }
    this.loadData();
  }

  onSortDirectionChange(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.sortDirection.set(value === 'desc' ? 'desc' : 'asc');
    this.pageIndex.set(0);
    this.loadData();
  }

  onPageChange(event: PageEvent): void {
    this.pageSize.set(event.pageSize);
    this.pageIndex.set(event.pageIndex);
    this.loadData();
  }

  loadData(): void {
    const cfg = this.config();
    if (!cfg) return;

    const requestId = ++this.latestLoadRequestId;
    this.isLoading.set(true);
    this.service.list(cfg.tableKey, {
      status: this.statusFilter() || undefined,
      search: this.searchText() || undefined,
      orderBy: this.getOrderByParam(cfg),
      limit: this.pageSize(),
      offset: this.pageIndex() * this.pageSize(),
      categoryId: cfg.tableKey === 'items' ? this.itemCategoryFilter() || undefined : undefined,
      ifrcFamilyId: cfg.tableKey === 'items' ? this.itemIfrcFamilyFilter() || undefined : undefined,
      ifrcItemRefId: cfg.tableKey === 'items' ? this.itemIfrcReferenceFilter() || undefined : undefined,
    }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: res => {
        if (requestId !== this.latestLoadRequestId) return;
        this.rows.set(this.applyClientSort(cfg, res.results));
        this.totalCount.set(res.count);
        this.isLoading.set(false);
      },
      error: () => {
        if (requestId !== this.latestLoadRequestId) return;
        this.notify.showError('Failed to load records.');
        this.isLoading.set(false);
      },
    });
  }

  onAdd(): void {
    const cfg = this.config();
    if (!cfg || !this.canCreate()) return;

    if (cfg.formMode === 'dialog') {
      this.openFormDialog(null);
    } else {
      this.router.navigate(['/master-data', cfg.routePath, 'new']);
    }
  }

  onView(row: MasterRecord): void {
    const cfg = this.config();
    if (!cfg) return;
    const pk = this.coercePrimaryKey(row[cfg.pkField]);
    if (pk == null) {
      this.notify.showError('Cannot open record: invalid primary key.');
      return;
    }

    if (cfg.formMode === 'page') {
      this.router.navigate(['/master-data', cfg.routePath, pk]);
    }
  }

  onEdit(row: MasterRecord): void {
    const cfg = this.config();
    if (!cfg || !this.canEdit()) return;
    const pk = this.coercePrimaryKey(row[cfg.pkField]);
    if (pk == null) {
      this.notify.showError('Cannot edit record: invalid primary key.');
      return;
    }

    if (cfg.formMode === 'dialog') {
      this.openFormDialog(pk);
    } else {
      this.router.navigate(['/master-data', cfg.routePath, pk, 'edit']);
    }
  }

  onToggleStatus(row: MasterRecord): void {
    const cfg = this.config();
    if (!cfg) return;
    const pk = this.coercePrimaryKey(row[cfg.pkField]);
    if (pk == null) {
      this.notify.showError('Cannot change status: invalid primary key.');
      return;
    }
    const versionNbr = this.coerceVersionNumber(row['version_nbr']);
    const isActive = row[cfg.statusField || 'status_code'] === 'A';
    if (!this.canToggleStatus(row)) {
      return;
    }

    if (isActive) {
      const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
        data: {
          title: 'Confirm Inactivation',
          message: `Are you sure you want to inactivate this record?`,
          confirmLabel: 'Inactivate',
          cancelLabel: 'Cancel',
          icon: 'block',
          iconColor: '#f44336',
          confirmColor: 'warn',
        } as ConfirmDialogData,
        width: '400px',
      });
      dialogRef.afterClosed().pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe(confirmed => {
        if (confirmed) {
          this.service.inactivate(cfg.tableKey, pk, versionNbr).pipe(
            takeUntilDestroyed(this.destroyRef),
          ).subscribe({
            next: () => {
              this.notify.showSuccess('Record inactivated.');
              this.loadData();
            },
            error: (err) => {
              const detail = err.error?.detail || 'Inactivation failed.';
              const blocking = err.error?.blocking;
              if (blocking?.length) {
                this.notify.showError(`Cannot inactivate: referenced by ${blocking.join(', ')}`);
              } else {
                this.notify.showError(detail);
              }
            },
          });
        }
      });
    } else {
      this.service.activate(cfg.tableKey, pk, versionNbr).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: () => {
          this.notify.showSuccess('Record activated.');
          this.loadData();
        },
        error: () => this.notify.showError('Activation failed.'),
      });
    }
  }

  getStatusLabel(value: unknown): string {
    if (typeof value !== 'string') {
      return 'Unknown';
    }
    const cfg = this.config();
    if (value === 'A') return cfg?.activeLabel || 'Active';
    if (value === 'I' || value === 'C') return cfg?.inactiveLabel || 'Inactive';
    return value;
  }

  getStatusClass(value: string): string {
    if (value === 'A') return 'status-active';
    return 'status-inactive';
  }

  getColumnPill(column: MasterColumnConfig, value: unknown): ResolvedColumnPill | null {
    const normalized = this.normalizePillValue(value);
    if (column.toneMap?.length) {
      const rule = this.findToneRule(column.toneMap, normalized);
      const fallbackTone: MasterTone = column.type === 'pill' || column.type === 'status' ? 'neutral' : 'neutral';
      return {
        label: rule?.label ?? this.getPillLabel(column, normalized),
        icon: rule?.icon ?? null,
        tone: rule?.tone ?? fallbackTone,
        legacyStatus: null,
      };
    }

    if (column.type === 'status') {
      return {
        label: this.getStatusLabel(value),
        icon: normalized === 'A' ? 'check_circle' : 'cancel',
        tone: null,
        legacyStatus: normalized,
      };
    }

    if (column.type === 'pill') {
      return {
        label: this.getPillLabel(column, normalized),
        icon: null,
        tone: 'neutral',
        legacyStatus: null,
      };
    }

    return null;
  }

  getPillClasses(pill: ResolvedColumnPill): string[] {
    return pill.tone ? ['ops-chip', `ops-chip--${pill.tone}`] : [];
  }

  getDisplayValue(column: MasterColumnConfig, value: unknown): string {
    if (value === null || value === undefined || value === '') {
      return '';
    }

    const raw = String(value);
    if (!column.truncate || raw.length <= column.truncate) {
      return raw;
    }

    return `${raw.slice(0, Math.max(0, column.truncate - 1))}\u2026`;
  }

  getCellTitle(_column: MasterColumnConfig, value: unknown): string | null {
    if (value === null || value === undefined || value === '') {
      return null;
    }
    return String(value);
  }

  getMobileTitle(cfg: MasterTableConfig, row: MasterRecord): string {
    const firstColumn = cfg.columns[0];
    const value = row[firstColumn.field] ?? row[cfg.pkField];
    return this.getCellTitle(firstColumn, value) ?? '';
  }

  isIdentifierColumn(column: MasterColumnConfig): boolean {
    return Boolean(
      column.monospace
      || column.semibold
      || column.field === 'username'
      || column.field === 'code'
      || column.field.endsWith('_code'),
    );
  }

  getColumnPrefixIcon(column: MasterColumnConfig, value: unknown): string | null {
    if (!column.prefixIcon || value === null || value === undefined || value === '') {
      return null;
    }
    return column.prefixIcon;
  }

  getStatusColumn(cfg: MasterTableConfig): MasterColumnConfig | null {
    const statusField = cfg.statusField || 'status_code';
    return cfg.columns.find((column) => column.field === statusField) ?? null;
  }

  getColumnFontFamily(column: MasterColumnConfig): string | null {
    return column.monospace ? 'var(--dmis-font-mono)' : null;
  }

  getColumnFontWeight(column: MasterColumnConfig): string | null {
    return column.semibold ? '600' : null;
  }

  getItemCategoryFilterLabel(item: ItemCategoryLookup): string {
    const code = String(item.category_code ?? '').trim();
    return code ? `${item.label} (${code})` : item.label;
  }

  getItemFamilyFilterLabel(item: IfrcFamilyLookup): string {
    const familyCode = String(item.family_code ?? '').trim();
    const groupCode = String(item.group_code ?? '').trim();
    const suffix = [groupCode, familyCode].filter(Boolean).join('-');
    return suffix ? `${item.label} (${suffix})` : item.label;
  }

  getItemReferenceFilterLabel(item: IfrcReferenceLookup): string {
    const ifrcCode = String(item.ifrc_code ?? '').trim();
    return ifrcCode ? `${item.label} (${ifrcCode})` : item.label;
  }

  private handleDialogQueryAction(): void {
    const cfg = this.config();
    if (this.pendingDialogQueryAction !== 'new' || cfg?.formMode !== 'dialog') {
      return;
    }

    this.pendingDialogQueryAction = null;
    if (this.canCreate()) {
      this.openFormDialog(null);
    }
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { open: null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  private openFormDialog(pk: string | number | null): void {
    const cfg = this.config();
    if (!cfg) return;
    if (pk == null && !this.canCreate()) return;
    if (pk != null && !this.canEdit()) return;

    const dialogRef = this.dialog.open(MasterFormDialogComponent, {
      data: { config: cfg, pk },
      width: '500px',
      maxHeight: '90vh',
    });

    dialogRef.afterClosed().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(saved => {
      if (saved) {
        this.loadData();
        this.service.clearLookupCache(cfg.tableKey);
      }
    });
  }

  private coercePrimaryKey(value: unknown): string | number | null {
    if (typeof value === 'string' || typeof value === 'number') {
      return value;
    }
    return null;
  }

  private coerceVersionNumber(value: unknown): number | undefined {
    return typeof value === 'number' ? value : undefined;
  }

  private getOrderByParam(cfg: MasterTableConfig): string | undefined {
    const field = this.sortField();
    if (!field) return undefined;

    // For item criticality, enforce domain ordering client-side.
    if (cfg.tableKey === 'items' && field === 'criticality_level') {
      return undefined;
    }

    return this.sortDirection() === 'desc' ? `-${field}` : field;
  }

  private normalizePillValue(value: unknown): string {
    return String(value ?? '').trim().toUpperCase();
  }

  private findToneRule(rules: readonly MasterToneRule[], normalizedValue: string): MasterToneRule | null {
    const defaultRule = rules.find((rule) => !rule.value && !rule.values?.length && !rule.startsWith);
    const matched = rules.find((rule) => {
      if (rule.value && normalizedValue === rule.value.trim().toUpperCase()) {
        return true;
      }
      if (rule.values?.some((value) => normalizedValue === value.trim().toUpperCase())) {
        return true;
      }
      if (rule.startsWith && normalizedValue.startsWith(rule.startsWith.trim().toUpperCase())) {
        return true;
      }
      return false;
    });
    return matched ?? defaultRule ?? null;
  }

  private getPillLabel(column: MasterColumnConfig, normalizedValue: string): string {
    if (column.type === 'status') {
      return this.getStatusLabel(normalizedValue);
    }
    return normalizedValue || 'Unknown';
  }

  private applyClientSort(cfg: MasterTableConfig, rows: MasterRecord[]): MasterRecord[] {
    if (cfg.tableKey !== 'items' || this.sortField() !== 'criticality_level') {
      return rows;
    }

    const direction = this.sortDirection();
    return [...rows].sort((a, b) => {
      const rankA = this.getCriticalityRank(a['criticality_level']);
      const rankB = this.getCriticalityRank(b['criticality_level']);

      if (rankA == null && rankB == null) return 0;
      if (rankA == null) return 1;
      if (rankB == null) return -1;

      const rankDiff = rankA - rankB;
      if (rankDiff !== 0) {
        return direction === 'desc' ? -rankDiff : rankDiff;
      }

      const nameA = String(a['item_name'] ?? '');
      const nameB = String(b['item_name'] ?? '');
      const nameDiff = nameA.localeCompare(nameB, undefined, { sensitivity: 'base' });
      return direction === 'desc' ? -nameDiff : nameDiff;
    });
  }

  canToggleStatus(row: MasterRecord): boolean {
    const cfg = this.config();
    if (!cfg) {
      return false;
    }
    const isActive = row[cfg.statusField || 'status_code'] === 'A';
    return this.access.canToggleStatusRoutePath(cfg.routePath, isActive, Boolean(cfg.readOnly));
  }

  private getCriticalityRank(value: unknown): number | null {
    const normalized = typeof value === 'string' ? value.trim().toUpperCase() : '';
    if (normalized === 'LOW') return 0;
    if (normalized === 'NORMAL') return 1;
    if (normalized === 'HIGH') return 2;
    if (normalized === 'CRITICAL') return 3;
    return null;
  }
}
