export type EventPhase = 'SURGE' | 'STABILIZED' | 'BASELINE';
export type SeverityLevel = 'CRITICAL' | 'WARNING' | 'WATCH' | 'OK';
export type FreshnessLevel = 'HIGH' | 'MEDIUM' | 'LOW';

export interface StockStatusItem {
  item_id: number;
  item_name?: string;
  category?: string;
  warehouse_id?: number;
  warehouse_name?: string;
  available_qty: number;
  inbound_strict_qty: number;
  burn_rate_per_hour: number;
  burn_rate_trend?: 'up' | 'down' | 'stable';
  time_to_stockout?: number | string;
  time_to_stockout_hours?: number;
  required_qty?: number;
  gap_qty: number;
  severity?: SeverityLevel;
  confidence?: {
    level: string;
    reasons: string[];
  };
  freshness?: {
    state: FreshnessLevel;
    age_hours: number | null;
    inventory_as_of: string | null;
  };
  warnings?: string[];
  is_estimated?: boolean;
}

export interface StockStatusResponse {
  as_of_datetime: string;
  event_id: number;
  warehouse_id: number;
  phase: EventPhase;
  items: StockStatusItem[];
  warnings: string[];
  data_freshness?: {
    overall: FreshnessLevel;
    last_sync: string;
    warehouses: Record<string, { state: FreshnessLevel; last_sync: string }>;
  };
}

export interface WarehouseStockGroup {
  warehouse_id: number;
  warehouse_name: string;
  items: StockStatusItem[];
  critical_count: number;
  warning_count: number;
  watch_count: number;
  ok_count: number;
  overall_freshness?: FreshnessLevel;
}

export interface MultiWarehouseStockResponse {
  event_id: number;
  event_name: string;
  phase: EventPhase;
  warehouses: WarehouseStockGroup[];
  as_of_datetime: string;
  warnings: string[];
}

export interface PhaseWindows {
  demand_hours: number;
  planning_hours: number;
  safety_factor: number;
}

export const PHASE_WINDOWS: Record<EventPhase, PhaseWindows> = {
  SURGE: { demand_hours: 6, planning_hours: 72, safety_factor: 1.5 },
  STABILIZED: { demand_hours: 72, planning_hours: 168, safety_factor: 1.25 },
  BASELINE: { demand_hours: 720, planning_hours: 720, safety_factor: 1.1 }
};

export function calculateSeverity(timeToStockoutHours: number | null): SeverityLevel {
  if (timeToStockoutHours === null || timeToStockoutHours === undefined) {
    return 'OK';
  }
  if (timeToStockoutHours < 8) return 'CRITICAL';
  if (timeToStockoutHours < 24) return 'WARNING';
  if (timeToStockoutHours < 72) return 'WATCH';
  return 'OK';
}

export function formatTimeToStockout(hours: number | null | string): string {
  if (hours === null || hours === undefined || hours === 'N/A') {
    return 'N/A';
  }
  if (typeof hours === 'string') {
    return hours;
  }

  const h = Math.floor(hours);
  const m = Math.floor((hours - h) * 60);

  if (h === 0 && m === 0) return '< 1m';
  if (h === 0) return `${m}m`;
  if (h < 24) return `${h}h ${m}m`;

  const days = Math.floor(h / 24);
  const remainingHours = h % 24;
  return `${days}d ${remainingHours}h`;
}
