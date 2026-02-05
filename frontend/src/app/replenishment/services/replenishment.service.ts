import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { StockStatusResponse, StockStatusItem, calculateSeverity } from '../models/stock-status.model';
import { NeedsListResponse } from '../models/needs-list.model';

export interface ActiveEvent {
  event_id: number;
  event_name: string;
  status: string;
  phase: string;
  declaration_date: string;
}

export interface Warehouse {
  warehouse_id: number;
  warehouse_name: string;
}

export interface WarehousesResponse {
  warehouses: Warehouse[];
  count: number;
}

@Injectable({
  providedIn: 'root'
})
export class ReplenishmentService {
  private readonly apiUrl = '/api/v1/replenishment';

  constructor(private http: HttpClient) {}

  /**
   * Get the currently active event
   * Returns null if no active event exists
   */
  getActiveEvent(): Observable<ActiveEvent | null> {
    return this.http.get<ActiveEvent | null>(`${this.apiUrl}/active-event`);
  }

  /**
   * Get all active warehouses
   */
  getAllWarehouses(): Observable<Warehouse[]> {
    return this.http.get<WarehousesResponse>(`${this.apiUrl}/warehouses`).pipe(
      map(response => response.warehouses)
    );
  }

  getStockStatus(eventId: number, warehouseId: number, phase: string): Observable<StockStatusResponse> {
    return this.http.post<StockStatusResponse>(`${this.apiUrl}/needs-list/preview`, {
      event_id: eventId,
      warehouse_id: warehouseId,
      phase: phase
    }).pipe(
      map(response => this.enrichStockStatusResponse(response))
    );
  }

  /**
   * Get stock status for multiple warehouses (for wizard)
   */
  getStockStatusMulti(
    eventId: number,
    warehouseIds: number[],
    phase: string,
    asOfDatetime?: string
  ): Observable<NeedsListResponse> {
    const payload: any = {
      event_id: eventId,
      warehouse_ids: warehouseIds,
      phase: phase
    };

    if (asOfDatetime) {
      payload.as_of_datetime = asOfDatetime;
    }

    return this.http.post<NeedsListResponse>(
      `${this.apiUrl}/needs-list/preview-multi`,
      payload
    ).pipe(
      map(response => ({
        ...response,
        items: response.items.map(item => ({
          ...item,
          time_to_stockout_hours: this.parseTimeToStockout(item.time_to_stockout) ?? undefined,
          severity: calculateSeverity(this.parseTimeToStockout(item.time_to_stockout))
        }))
      }))
    );
  }

  private enrichStockStatusResponse(response: StockStatusResponse): StockStatusResponse {
    const enrichedItems = response.items.map(item => this.enrichStockItem(item));
    return {
      ...response,
      items: enrichedItems
    };
  }

  private enrichStockItem(item: StockStatusItem): StockStatusItem {
    const timeToStockoutHours = this.parseTimeToStockout(item.time_to_stockout);
    const severity = calculateSeverity(timeToStockoutHours);
    const isEstimated = (item.warnings ?? []).includes('burn_rate_estimated');

    return {
      ...item,
      time_to_stockout_hours: timeToStockoutHours ?? undefined,
      severity,
      is_estimated: isEstimated
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
    return isNaN(parsed) ? null : parsed;
  }
}
