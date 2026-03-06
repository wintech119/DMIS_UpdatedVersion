import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { IFRCSuggestion } from '../models/ifrc-suggest.models';

export interface IFRCSpecHints {
  size_weight: string;
  form: string;
  material: string;
}

@Injectable({ providedIn: 'root' })
export class IfrcSuggestService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = '/api/v1/masterdata/items/ifrc-suggest';

  suggest(itemName: string, specs?: Partial<IFRCSpecHints>): Observable<IFRCSuggestion | null> {
    let params = new HttpParams().set('name', itemName);
    if (specs?.size_weight) params = params.set('size_weight', specs.size_weight);
    if (specs?.form)        params = params.set('form', specs.form);
    if (specs?.material)    params = params.set('material', specs.material);

    return this.http.get<IFRCSuggestion>(this.apiUrl, { params }).pipe(
      catchError((err) => {
        console.warn('[IFRC Suggest] request failed:', err);
        return of(null);
      }),
    );
  }
}
