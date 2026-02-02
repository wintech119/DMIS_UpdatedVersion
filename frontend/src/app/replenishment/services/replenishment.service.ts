import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { StockStatusResponse, StockStatusItem, calculateSeverity } from '../models/stock-status.model';

@Injectable({
  providedIn: 'root'
})
export class ReplenishmentService {
  private readonly apiUrl = '/api/v1/replenishment';

  constructor(private http: HttpClient) {}

  getStockStatus(eventId: number, warehouseId: number, phase: string): Observable<StockStatusResponse> {
    return this.http.post<StockStatusResponse>(`${this.apiUrl}/needs-list/preview`, {
      event_id: eventId,
      warehouse_id: warehouseId,
      phase: phase
    }).pipe(
      map(response => this.enrichStockStatusResponse(response))
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
