import { Injectable, inject } from '@angular/core';
import { Observable, of } from 'rxjs';
import { map } from 'rxjs/operators';

import { ReplenishmentService } from './replenishment.service';
import {
  StockStatusItem,
  EventPhase,
  SeverityLevel,
  FreshnessLevel,
  WarehouseStockGroup,
  ActionUrgency,
  calculateSeverity,
  getRecommendedAction
} from '../models/stock-status.model';
import { NeedsListItem } from '../models/needs-list.model';

// ── Public types ──────────────────────────────────────────────

export interface DashboardStockItem extends StockStatusItem {
  recommended_action: string;
  action_urgency: ActionUrgency;
}

export interface DashboardTotals {
  items: number;
  critical: number;
  warning: number;
  watch: number;
  ok: number;
}

export interface DashboardData {
  groups: WarehouseStockGroup[];
  as_of_datetime: string;
  warnings: string[];
  totals: DashboardTotals;
  availableCategories: string[];
}

export type SortField = 'time_to_stockout' | 'item_name' | 'severity';
export type SortDirection = 'asc' | 'desc';

export interface DashboardDataOptions {
  categories?: string[];
  severities?: SeverityLevel[];
  sortBy?: SortField;
  sortDirection?: SortDirection;
}

// ── Cache internals ───────────────────────────────────────────

/** Cached enriched items (pre-filter). Filters are applied on read. */
interface CacheEntry {
  items: DashboardStockItem[];
  asOfDatetime: string;
  warnings: string[];
  timestamp: number;
  freshnessLevel: FreshnessLevel;
}

/** TTL per freshness level (milliseconds) */
const CACHE_TTL: Record<FreshnessLevel, number> = {
  HIGH:   5 * 60_000,   // 5 min — data is < 2 h old
  MEDIUM: 2 * 60_000,   // 2 min — data aging
  LOW:    0              // never cache stale data
};

// ── Service ───────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class DashboardDataService {
  private replenishmentService = inject(ReplenishmentService);

  /** Cache keyed by eventId|warehouseIds|phase (filters NOT included). */
  private cache = new Map<string, CacheEntry>();

  // ── Public API ────────────────────────────────────────────

  /**
   * Fetch, transform, and cache dashboard stock data.
   *
   * The cache stores *enriched items* (pre-filter).  Filters, grouping, and
   * sorting are applied locally on every call — so filter changes never
   * trigger a network request.
   *
   * Pipeline:
   *  1. Cache check  (enriched items by eventId + warehouseIds + phase)
   *  2. If miss → API call → enrich → store in cache
   *  3. Apply filters + group by warehouse + sort by urgency + compute totals
   */
  getDashboardData(
    eventId: number,
    warehouseIds: number[],
    phase: EventPhase,
    options: DashboardDataOptions = {}
  ): Observable<DashboardData> {
    const cacheKey = this.buildCacheKey(eventId, warehouseIds, phase);
    const cached = this.getFromCache(cacheKey);

    if (cached) {
      return of(this.transformForDisplay(cached, options));
    }

    return this.replenishmentService.getStockStatusMulti(eventId, warehouseIds, phase).pipe(
      map(response => {
        const enriched = this.enrichItems(response.items);
        const freshness = this.worstFreshnessFromItems(enriched);

        const entry: CacheEntry = {
          items: enriched,
          asOfDatetime: response.as_of_datetime,
          warnings: response.warnings ?? [],
          timestamp: Date.now(),
          freshnessLevel: freshness
        };

        this.storeInCache(cacheKey, entry);
        return this.transformForDisplay(entry, options);
      })
    );
  }

  /** Clear all cached entries. Call before a manual refresh. */
  invalidateCache(): void {
    this.cache.clear();
  }

  // ── Transform (runs on every call, cached or not) ─────────

  /**
   * Apply filters, group, sort, and compute totals from cached enriched items.
   */
  private transformForDisplay(entry: CacheEntry, options: DashboardDataOptions): DashboardData {
    const filtered = this.applyFilters(entry.items, options);
    const groups = this.groupByWarehouse(filtered, entry.items, options);
    const totals = this.computeTotals(groups);

    // Available categories from ALL items (not just filtered)
    const availableCategories = [...new Set(
      entry.items.map(i => i.category).filter((c): c is string => !!c)
    )].sort();

    return {
      groups,
      as_of_datetime: entry.asOfDatetime,
      warnings: entry.warnings,
      totals,
      availableCategories
    };
  }

  // ── Enrichment ────────────────────────────────────────────

  /**
   * Enrich raw API items with derived fields:
   * time_to_stockout_hours, severity, recommended_action, action_urgency.
   */
  private enrichItems(items: NeedsListItem[]): DashboardStockItem[] {
    return items.map(item => {
      const parsedStockout = this.parseTimeToStockout(item.time_to_stockout);
      const freshness = this.normalizeFreshness(item.freshness);
      const severity = item.severity ?? calculateSeverity(parsedStockout);
      const { action, urgency } = getRecommendedAction(severity);

      return {
        ...item,
        time_to_stockout_hours: item.time_to_stockout_hours ?? (parsedStockout ?? undefined),
        severity,
        freshness: freshness ?? undefined,
        is_estimated: (item.warnings ?? []).includes('burn_rate_estimated'),
        recommended_action: action,
        action_urgency: urgency
      } as DashboardStockItem;
    });
  }

  // ── Filtering ─────────────────────────────────────────────

  private applyFilters(
    items: DashboardStockItem[],
    options: DashboardDataOptions
  ): DashboardStockItem[] {
    let filtered = items;

    if (options.categories && options.categories.length > 0) {
      const cats = options.categories;
      filtered = filtered.filter(item => item.category != null && cats.includes(item.category));
    }

    if (options.severities && options.severities.length > 0) {
      const sevs = options.severities;
      filtered = filtered.filter(item => sevs.includes(item.severity ?? 'OK'));
    }

    return filtered;
  }

  // ── Grouping ──────────────────────────────────────────────

  /**
   * Group items by warehouse_id.
   *
   * Each group contains filtered + sorted items, severity counts, and
   * overall freshness (computed from *all* items regardless of filters).
   */
  private groupByWarehouse(
    filteredItems: DashboardStockItem[],
    allItems: DashboardStockItem[],
    options: DashboardDataOptions
  ): WarehouseStockGroup[] {
    const allByWarehouse = new Map<number, DashboardStockItem[]>();
    const filteredByWarehouse = new Map<number, DashboardStockItem[]>();

    for (const item of allItems) {
      const wid = item.warehouse_id;
      if (wid == null) continue;
      if (!allByWarehouse.has(wid)) allByWarehouse.set(wid, []);
      allByWarehouse.get(wid)!.push(item);
    }

    for (const item of filteredItems) {
      const wid = item.warehouse_id;
      if (wid == null) continue;
      if (!filteredByWarehouse.has(wid)) filteredByWarehouse.set(wid, []);
      filteredByWarehouse.get(wid)!.push(item);
    }

    const groups: WarehouseStockGroup[] = [];

    for (const [warehouseId, warehouseAllItems] of allByWarehouse) {
      const warehouseFiltered = filteredByWarehouse.get(warehouseId) ?? [];
      const sorted = this.sortByUrgency(warehouseFiltered, options);
      const name = warehouseAllItems[0]?.warehouse_name || `Warehouse ${warehouseId}`;
      const overallFreshness = this.worstFreshness(warehouseAllItems);

      groups.push({
        warehouse_id: warehouseId,
        warehouse_name: name,
        items: sorted,
        all_items: warehouseAllItems,
        critical_count: sorted.filter(i => i.severity === 'CRITICAL').length,
        warning_count: sorted.filter(i => i.severity === 'WARNING').length,
        watch_count: sorted.filter(i => i.severity === 'WATCH').length,
        ok_count: sorted.filter(i => i.severity === 'OK').length,
        overall_freshness: overallFreshness
      });
    }

    // Most critical warehouses first
    groups.sort((a, b) => b.critical_count - a.critical_count);
    return groups;
  }

  // ── Sorting ───────────────────────────────────────────────

  private sortByUrgency(
    items: DashboardStockItem[],
    options: DashboardDataOptions
  ): DashboardStockItem[] {
    const sortBy = options.sortBy ?? 'time_to_stockout';
    const direction = options.sortDirection ?? 'asc';

    const severityOrder: Record<SeverityLevel, number> = {
      CRITICAL: 0, WARNING: 1, WATCH: 2, OK: 3
    };

    return [...items].sort((a, b) => {
      let comparison = 0;

      switch (sortBy) {
        case 'time_to_stockout': {
          comparison = this.normalizeStockoutTime(a) - this.normalizeStockoutTime(b);
          break;
        }
        case 'severity': {
          comparison = severityOrder[a.severity ?? 'OK'] - severityOrder[b.severity ?? 'OK'];
          break;
        }
        case 'item_name': {
          const nameA = (a.item_name || `Item ${a.item_id}`).toLowerCase();
          const nameB = (b.item_name || `Item ${b.item_id}`).toLowerCase();
          comparison = nameA.localeCompare(nameB);
          break;
        }
      }

      return direction === 'asc' ? comparison : -comparison;
    });
  }

  // ── Totals ────────────────────────────────────────────────

  private computeTotals(groups: WarehouseStockGroup[]): DashboardTotals {
    return groups.reduce(
      (acc, g) => ({
        items: acc.items + g.items.length,
        critical: acc.critical + g.critical_count,
        warning: acc.warning + g.warning_count,
        watch: acc.watch + g.watch_count,
        ok: acc.ok + g.ok_count
      }),
      { items: 0, critical: 0, warning: 0, watch: 0, ok: 0 }
    );
  }

  // ── Helpers ───────────────────────────────────────────────

  private parseTimeToStockout(value: number | string | undefined): number | null {
    if (value === undefined || value === null || value === 'N/A') return null;
    if (typeof value === 'number') return value;
    const parsed = parseFloat(value);
    return Number.isNaN(parsed) ? null : parsed;
  }

  private normalizeFreshness(
    freshness: NeedsListItem['freshness']
  ): StockStatusItem['freshness'] | null {
    if (!freshness) return null;
    const state = String(freshness.state).toUpperCase();
    if (state !== 'HIGH' && state !== 'MEDIUM' && state !== 'LOW') return null;
    return { ...freshness, state: state as FreshnessLevel };
  }

  private normalizeStockoutTime(item: StockStatusItem): number {
    const value = item.time_to_stockout_hours ?? item.time_to_stockout;
    const numeric = typeof value === 'number' ? value : Number(value);
    return Number.isFinite(numeric) ? numeric : Infinity;
  }

  private worstFreshness(items: StockStatusItem[]): FreshnessLevel {
    const order: FreshnessLevel[] = ['LOW', 'MEDIUM', 'HIGH'];
    let worst: FreshnessLevel = 'HIGH';

    for (const item of items) {
      const state = item.freshness?.state;
      if (!state) continue;
      if (order.indexOf(state) < order.indexOf(worst)) worst = state;
    }

    return worst;
  }

  private worstFreshnessFromItems(items: DashboardStockItem[]): FreshnessLevel {
    return this.worstFreshness(items);
  }

  // ── Cache ─────────────────────────────────────────────────

  /** Key based on fetch params only — filters are NOT included. */
  private buildCacheKey(eventId: number, warehouseIds: number[], phase: EventPhase): string {
    const wids = [...warehouseIds].sort().join(',');
    return `${eventId}|${wids}|${phase}`;
  }

  private getFromCache(key: string): CacheEntry | null {
    const entry = this.cache.get(key);
    if (!entry) return null;

    const ttl = CACHE_TTL[entry.freshnessLevel];
    const age = Date.now() - entry.timestamp;

    if (age > ttl) {
      this.cache.delete(key);
      return null;
    }

    return entry;
  }

  private storeInCache(key: string, entry: CacheEntry): void {
    if (CACHE_TTL[entry.freshnessLevel] === 0) return;
    this.cache.set(key, entry);
  }
}
