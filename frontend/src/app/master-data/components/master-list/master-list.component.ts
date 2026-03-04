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

import { MasterRecord, MasterTableConfig } from '../../models/master-data.models';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import { MasterDataService } from '../../services/master-data.service';
import { MasterFormDialogComponent } from '../master-form-dialog/master-form-dialog.component';
import { DmisSkeletonLoaderComponent } from '../../../replenishment/shared/dmis-skeleton-loader/dmis-skeleton-loader.component';
import { DmisEmptyStateComponent } from '../../../replenishment/shared/dmis-empty-state/dmis-empty-state.component';
import { DmisConfirmDialogComponent, ConfirmDialogData } from '../../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';

import { Subject, debounceTime, distinctUntilChanged, tap } from 'rxjs';

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
  private destroyRef = inject(DestroyRef);
  private breakpointObserver = inject(BreakpointObserver);
  private latestLoadRequestId = 0;

  config = signal<MasterTableConfig | null>(null);
  rows = signal<MasterRecord[]>([]);
  totalCount = signal(0);
  isLoading = signal(true);
  isMobile = signal(false);

  // Filters
  filtersExpanded = signal(false);
  statusFilter = signal<string>('');
  searchText = signal('');
  pageSize = signal(25);
  pageIndex = signal(0);

  private searchSubject = new Subject<string>();

  displayedColumns = computed(() => {
    const cfg = this.config();
    if (!cfg) return [];
    const cols = cfg.columns;
    const colNames = cols.map(c => c.field);
    if (!cfg.readOnly) colNames.push('_actions');
    return colNames;
  });

  activeFilterCount = computed(() => {
    let count = 0;
    if (this.statusFilter()) count++;
    if (this.searchText()) count++;
    return count;
  });

  hasActiveFilters = computed(() => this.activeFilterCount() > 0);

  ngOnInit(): void {
    this.breakpointObserver.observe([Breakpoints.Handset]).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(result => this.isMobile.set(result.matches));

    this.route.data.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(data => {
      const routePath = data['routePath'] as string;
      const cfg = ALL_TABLE_CONFIGS[routePath];
      if (cfg) {
        this.config.set(cfg);
        this.loadData();
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

  toggleFilters(): void {
    this.filtersExpanded.update(v => !v);
  }

  clearFilters(): void {
    const hadSearch = !!this.searchText();
    this.statusFilter.set('');
    this.searchSubject.next('');
    if (!hadSearch) {
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
      limit: this.pageSize(),
      offset: this.pageIndex() * this.pageSize(),
    }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: res => {
        if (requestId !== this.latestLoadRequestId) return;
        this.rows.set(res.results);
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
    if (!cfg) return;

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
    if (!cfg) return;
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

  private openFormDialog(pk: string | number | null): void {
    const cfg = this.config();
    if (!cfg) return;

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
}
