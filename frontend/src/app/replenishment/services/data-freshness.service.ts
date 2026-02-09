import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable, Subject } from 'rxjs';
import {
  FreshnessLevel,
  BannerFreshnessState,
  WarehouseFreshnessEntry,
  DataFreshnessBannerState,
  WarehouseStockGroup
} from '../models/stock-status.model';

const INITIAL_STATE: DataFreshnessBannerState = {
  overallState: 'ALL_FRESH',
  lastSuccessfulSync: null,
  warehouses: [],
  staleWarehouseNames: [],
  maxAgeHours: null
};

@Injectable({ providedIn: 'root' })
export class DataFreshnessService {
  private bannerState$ = new BehaviorSubject<DataFreshnessBannerState>(INITIAL_STATE);
  private refreshRequested$ = new Subject<void>();
  private refreshing$ = new BehaviorSubject<boolean>(false);

  getBannerState$(): Observable<DataFreshnessBannerState> {
    return this.bannerState$.asObservable();
  }

  onRefreshRequested$(): Observable<void> {
    return this.refreshRequested$.asObservable();
  }

  isRefreshing$(): Observable<boolean> {
    return this.refreshing$.asObservable();
  }

  /**
   * Called by dashboard after loading stock data.
   * Computes banner state from warehouse groups that already have overall_freshness.
   */
  updateFromWarehouseGroups(groups: WarehouseStockGroup[]): void {
    const entries: WarehouseFreshnessEntry[] = groups.map(g => {
      // Find worst age_hours across items in this group
      let worstAge: number | null = null;
      let latestSync: string | null = null;

      g.items.forEach(item => {
        const ageH = item.freshness?.age_hours;
        if (ageH !== null && ageH !== undefined) {
          if (worstAge === null || ageH > worstAge) {
            worstAge = ageH;
          }
        }
        const asOf = item.freshness?.inventory_as_of;
        if (asOf && (!latestSync || asOf > latestSync)) {
          latestSync = asOf;
        }
      });

      return {
        warehouse_id: g.warehouse_id,
        warehouse_name: g.warehouse_name,
        freshness: g.overall_freshness ?? 'HIGH',
        last_sync: latestSync,
        age_hours: worstAge
      };
    });

    this.computeAndEmit(entries);
  }

  triggerRefresh(): void {
    this.refreshing$.next(true);
    this.refreshRequested$.next();
  }

  refreshComplete(): void {
    this.refreshing$.next(false);
  }

  clear(): void {
    this.bannerState$.next(INITIAL_STATE);
  }

  private computeAndEmit(entries: WarehouseFreshnessEntry[]): void {
    const staleWarehouses = entries.filter(e => e.freshness === 'LOW');
    const warningWarehouses = entries.filter(e => e.freshness === 'MEDIUM');

    let overallState: BannerFreshnessState = 'ALL_FRESH';
    if (staleWarehouses.length > 0) {
      overallState = 'CRITICAL_STALE';
    } else if (warningWarehouses.length > 0) {
      overallState = 'SOME_STALE';
    }

    const allAges = entries.map(e => e.age_hours).filter((a): a is number => a !== null);
    const maxAge = allAges.length > 0 ? Math.max(...allAges) : null;

    const allSyncs = entries.map(e => e.last_sync).filter((s): s is string => !!s);
    const latestSync = allSyncs.length > 0 ? allSyncs.sort().reverse()[0] : null;

    this.bannerState$.next({
      overallState,
      lastSuccessfulSync: latestSync,
      warehouses: entries,
      staleWarehouseNames: staleWarehouses.map(w => w.warehouse_name),
      maxAgeHours: maxAge
    });
  }
}
