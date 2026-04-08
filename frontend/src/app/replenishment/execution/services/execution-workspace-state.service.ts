import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import {
  AllocationCandidate,
  AllocationCommitPayload,
  AllocationItemGroup,
  AllocationOptionsResponse,
  AllocationOverrideApprovalPayload,
  AllocationSelectionPayload,
  EXECUTION_OVERRIDE_REASON_OPTIONS,
  ExecutionSelectedMethod,
  ExecutionUrgencyCode,
  WaybillResponse,
} from '../../models/allocation-dispatch.model';
import { NeedsListResponse } from '../../models/needs-list.model';
import { ReplenishmentService } from '../../services/replenishment.service';

interface ExecutionCommitDraft {
  agency_id: string;
  urgency_ind: ExecutionUrgencyCode | '';
  transport_mode: string;
  request_notes: string;
  package_comments: string;
  override_reason_code: string;
  override_note: string;
}

interface LoadResult {
  current: NeedsListResponse | null;
  options: AllocationOptionsResponse | null;
}

const DEFAULT_DRAFT: ExecutionCommitDraft = {
  agency_id: '',
  urgency_ind: '',
  transport_mode: '',
  request_notes: '',
  package_comments: '',
  override_reason_code: '',
  override_note: '',
};

@Injectable()
export class ExecutionWorkspaceStateService {
  private readonly replenishmentService = inject(ReplenishmentService);

  readonly needsListId = signal('');
  readonly current = signal<NeedsListResponse | null>(null);
  readonly options = signal<AllocationOptionsResponse | null>(null);
  readonly waybill = signal<WaybillResponse | null>(null);

  readonly loading = signal(false);
  readonly waybillLoading = signal(false);
  readonly submitting = signal(false);
  readonly startPreparationLoading = signal(false);

  readonly loadError = signal<string | null>(null);
  readonly optionsError = signal<string | null>(null);
  readonly waybillError = signal<string | null>(null);

  readonly draft = signal<ExecutionCommitDraft>({ ...DEFAULT_DRAFT });
  readonly selectedRowsByItem = signal<Record<number, AllocationSelectionPayload[]>>({});

  readonly selectedLineCount = computed(() =>
    Object.values(this.selectedRowsByItem()).reduce((sum, rows) => sum + rows.length, 0)
  );

  readonly requiresFirstCommitDetails = computed(() =>
    !this.current()?.reliefrqst_id && !this.current()?.reliefpkg_id
  );

  readonly hasCommittedAllocation = computed(() => {
    if ((this.current()?.allocation_lines ?? []).length > 0) {
      return true;
    }
    const executionStatus = String(this.current()?.execution_status ?? '').trim().toUpperCase();
    return executionStatus === 'COMMITTED' || executionStatus === 'DISPATCHED' || executionStatus === 'RECEIVED';
  });

  readonly hasPendingOverride = computed(() =>
    String(this.current()?.execution_status ?? '').trim().toUpperCase() === 'PENDING_OVERRIDE_APPROVAL'
  );

  readonly hasWaybill = computed(() => !!(this.waybill()?.waybill_no || this.current()?.waybill_no));

  readonly selectedMethod = computed<ExecutionSelectedMethod | undefined>(() => {
    const currentMethod = this.normalizeSelectedMethod(this.current()?.selected_method);
    const itemGroups = this.options()?.items ?? [];
    if (!itemGroups.length) {
      return currentMethod ?? undefined;
    }

    const hasBypass = itemGroups.some((group) => this.isRuleBypassedForItem(group.item_id));
    if (hasBypass) {
      return 'MANUAL';
    }

    const selectedGroups = itemGroups.filter((group) => this.getSelectedTotalForItem(group.item_id) > 0);
    if (!selectedGroups.length) {
      return currentMethod ?? undefined;
    }

    const issuanceOrders = new Set(
      selectedGroups
        .map((group) => this.normalizeSelectedMethod(group.issuance_order))
        .filter((value): value is ExecutionSelectedMethod => value === 'FEFO' || value === 'FIFO')
    );
    if (issuanceOrders.size === 1) {
      return [...issuanceOrders][0];
    }
    return 'MIXED';
  });

  readonly planRequiresOverride = computed(() =>
    (this.options()?.items ?? []).some((group) => {
      const total = this.getSelectedTotalForItem(group.item_id);
      return total > 0 && this.isRuleBypassedForItem(group.item_id);
    })
  );

  readonly totalSelectedQty = computed(() =>
    Object.values(this.selectedRowsByItem())
      .flat()
      .reduce((sum, row) => sum + this.toNumber(row.quantity), 0)
  );

  load(needsListId: string, optionsEnabled = true): void {
    this.needsListId.set(needsListId);
    this.loading.set(true);
    this.loadError.set(null);
    this.optionsError.set(null);
    this.current.set(null);
    this.options.set(null);
    this.waybill.set(null);
    this.waybillError.set(null);
    this.selectedRowsByItem.set({});
    this.draft.set({ ...DEFAULT_DRAFT });

    forkJoin({
      current: this.replenishmentService.getAllocationCurrent(needsListId).pipe(
        catchError((error: HttpErrorResponse) => {
          this.loadError.set(this.extractError(error, 'Failed to load allocation status.'));
          return of(null);
        })
      ),
      options: optionsEnabled
        ? this.replenishmentService.getAllocationOptions(needsListId).pipe(
            catchError((error: HttpErrorResponse) => {
              this.optionsError.set(this.extractError(error, 'Failed to load allocation options.'));
              return of(null);
            })
          )
        : of(null),
    }).subscribe({
      next: ({ current, options }: LoadResult) => {
        this.current.set(current);
        this.options.set(options);
        if (current) {
          this.hydrateDraft(current);
        }
        if (options) {
          this.initializeSelections(current, options);
        }
        if (current?.waybill_no) {
          this.loadWaybill();
        } else {
          this.waybill.set(null);
          this.waybillError.set(null);
        }
        this.loading.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.loadError.set('Failed to load execution workspace.');
      },
    });
  }

  refreshCurrent(): void {
    const needsListId = this.needsListId();
    if (!needsListId) {
      return;
    }
    this.replenishmentService.getAllocationCurrent(needsListId).subscribe({
      next: (current) => {
        this.current.set(current);
        this.hydrateDraft(current);
        if (current.waybill_no) {
          this.loadWaybill();
        } else {
          this.waybill.set(null);
          this.waybillError.set(null);
        }
      },
      error: (error: HttpErrorResponse) => {
        this.loadError.set(this.extractError(error, 'Failed to refresh execution status.'));
      },
    });
  }

  loadWaybill(): void {
    const needsListId = this.needsListId();
    if (!needsListId) {
      return;
    }
    this.waybillLoading.set(true);
    this.waybillError.set(null);
    this.replenishmentService.getWaybill(needsListId).subscribe({
      next: (payload) => {
        this.waybill.set(payload);
        this.waybillLoading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.waybillLoading.set(false);
        this.waybillError.set(this.extractError(error, 'Waybill details are not available yet.'));
      },
    });
  }

  patchDraft(patch: Partial<ExecutionCommitDraft>): void {
    this.draft.update((current) => ({ ...current, ...patch }));
  }

  useSuggestedPlan(itemId: number): void {
    const group = this.getItemGroup(itemId);
    if (!group) {
      return;
    }
    const next = {
      ...this.selectedRowsByItem(),
      [itemId]: group.suggested_allocations.map((row) => ({
        item_id: row.item_id,
        inventory_id: row.inventory_id,
        batch_id: row.batch_id,
        quantity: row.quantity,
        source_type: row.source_type,
        source_record_id: row.source_record_id ?? null,
        uom_code: row.uom_code ?? null,
        needs_list_item_id: group.needs_list_item_id,
      })),
    };
    this.selectedRowsByItem.set(next);
  }

  clearItemSelection(itemId: number): void {
    const next = { ...this.selectedRowsByItem() };
    next[itemId] = [];
    this.selectedRowsByItem.set(next);
  }

  setCandidateQuantity(
    itemId: number,
    candidate: AllocationCandidate,
    quantity: number
  ): void {
    const normalizedQty = this.toFixedQuantity(Math.max(0, quantity));
    const rows = [...(this.selectedRowsByItem()[itemId] ?? [])];
    const existingIndex = rows.findIndex((row) =>
      this.selectionKey(row) === this.selectionKey(candidate)
    );
    if (normalizedQty <= 0) {
      if (existingIndex >= 0) {
        rows.splice(existingIndex, 1);
      }
    } else {
      const nextRow: AllocationSelectionPayload = {
        item_id: itemId,
        inventory_id: candidate.inventory_id,
        batch_id: candidate.batch_id,
        quantity: this.formatQuantity(normalizedQty),
        source_type: candidate.source_type,
        source_record_id: candidate.source_record_id ?? null,
        uom_code: candidate.uom_code ?? null,
        needs_list_item_id: this.getItemGroup(itemId)?.needs_list_item_id,
      };
      if (existingIndex >= 0) {
        rows[existingIndex] = nextRow;
      } else {
        rows.push(nextRow);
      }
    }
    this.selectedRowsByItem.set({
      ...this.selectedRowsByItem(),
      [itemId]: this.sortSelections(itemId, rows),
    });
  }

  getSelectedRows(itemId: number): AllocationSelectionPayload[] {
    return this.selectedRowsByItem()[itemId] ?? [];
  }

  getSelectedQtyForCandidate(itemId: number, candidate: AllocationCandidate): number {
    const row = this.getSelectedRows(itemId).find((entry) =>
      this.selectionKey(entry) === this.selectionKey(candidate)
    );
    return this.toNumber(row?.quantity);
  }

  getSelectedTotalForItem(itemId: number): number {
    return this.getSelectedRows(itemId)
      .reduce((sum, row) => sum + this.toNumber(row.quantity), 0);
  }

  getRemainingQtyForItem(itemId: number): number {
    return this.toNumber(this.getItemGroup(itemId)?.remaining_qty);
  }

  getUncoveredQtyForItem(itemId: number): number {
    return Math.max(0, this.getRemainingQtyForItem(itemId) - this.getSelectedTotalForItem(itemId));
  }

  getGreedyRecommendationForSelectedTotal(itemId: number): AllocationSelectionPayload[] {
    const group = this.getItemGroup(itemId);
    if (!group) {
      return [];
    }

    let remaining = this.getSelectedTotalForItem(itemId);
    const rows: AllocationSelectionPayload[] = [];
    for (const candidate of group.candidates) {
      if (remaining <= 0) {
        break;
      }
      const available = this.toNumber(candidate.available_qty);
      if (available <= 0) {
        continue;
      }
      const quantity = Math.min(available, remaining);
      rows.push({
        item_id: itemId,
        inventory_id: candidate.inventory_id,
        batch_id: candidate.batch_id,
        quantity: this.formatQuantity(quantity),
        source_type: candidate.source_type,
        source_record_id: candidate.source_record_id ?? null,
        uom_code: candidate.uom_code ?? null,
        needs_list_item_id: group.needs_list_item_id,
      });
      remaining = this.toFixedQuantity(remaining - quantity);
    }
    return rows;
  }

  isRuleBypassedForItem(itemId: number): boolean {
    const selectedRows = this.getSelectedRows(itemId).filter((row) => this.toNumber(row.quantity) > 0);
    if (!selectedRows.length) {
      return false;
    }
    return this.selectionSignature(selectedRows) !== this.selectionSignature(
      this.getGreedyRecommendationForSelectedTotal(itemId)
    );
  }

  getItemValidationMessage(item: AllocationItemGroup): string | null {
    const selected = this.getSelectedTotalForItem(item.item_id);
    const remaining = this.toNumber(item.remaining_qty);
    if (selected <= 0) {
      return 'Select at least one stock line before continuing.';
    }
    if (selected > remaining + 0.0001) {
      return 'Selected quantity cannot exceed the remaining requested quantity.';
    }
    for (const candidate of item.candidates) {
      const selectedQty = this.getSelectedQtyForCandidate(item.item_id, candidate);
      if (selectedQty > this.toNumber(candidate.available_qty) + 0.0001) {
        return `Selected quantity exceeds available stock for batch ${candidate.batch_no || candidate.batch_id}.`;
      }
    }
    return null;
  }

  buildCommitPayload(): { payload: AllocationCommitPayload | null; errors: string[] } {
    const errors: string[] = [];
    const allocations = Object.values(this.selectedRowsByItem())
      .flat()
      .filter((row) => this.toNumber(row.quantity) > 0)
      .map((row) => ({
        ...row,
        quantity: this.formatQuantity(this.toNumber(row.quantity)),
      }));

    if (!allocations.length) {
      errors.push('Select at least one stock line to reserve.');
    }

    const itemGroups = this.options()?.items ?? [];
    for (const item of itemGroups) {
      const validation = this.getItemValidationMessage(item);
      if (validation) {
        errors.push(`${item.item_name || `Item ${item.item_id}`}: ${validation}`);
      }
    }

    const draft = this.draft();
    if (this.requiresFirstCommitDetails()) {
      const agencyId = Number(draft.agency_id);
      if (!Number.isInteger(agencyId) || agencyId <= 0) {
        errors.push('Receiving agency ID is required for the first formal allocation.');
      }
      if (!draft.urgency_ind) {
        errors.push('Urgency is required for the first formal allocation.');
      }
    }

    if (this.planRequiresOverride()) {
      if (!draft.override_reason_code.trim()) {
        errors.push('Select an override reason before submitting a bypassed plan.');
      }
    }
    if (this.hasPendingOverride()) {
      if (!draft.override_note.trim()) {
        errors.push('Add an override note before submitting a bypassed plan.');
      }
    }

    if (errors.length) {
      return { payload: null, errors: [...new Set(errors)] };
    }

    const payload: AllocationCommitPayload = {
      allocations,
      selected_method: this.selectedMethod(),
      transport_mode: draft.transport_mode.trim() || undefined,
      request_notes: draft.request_notes.trim() || undefined,
      package_comments: draft.package_comments.trim() || undefined,
      override_reason_code: draft.override_reason_code.trim() || undefined,
      override_note: draft.override_note.trim() || undefined,
    };
    if (this.requiresFirstCommitDetails()) {
      payload.agency_id = Number(draft.agency_id);
      payload.urgency_ind = draft.urgency_ind || undefined;
    }
    return { payload, errors: [] };
  }

  buildOverrideApprovalPayload(): { payload: AllocationOverrideApprovalPayload | null; errors: string[] } {
    const draft = this.draft();
    const errors: string[] = [];
    if (!draft.override_reason_code.trim()) {
      errors.push('Select an override reason before approving.');
    }
    if (!draft.override_note.trim()) {
      errors.push('Add an override note before approving.');
    }
    if (errors.length) {
      return { payload: null, errors };
    }
    return {
      payload: {
        allocations: this.current()?.allocation_lines?.map((line) => ({
          item_id: line.item_id,
          inventory_id: line.inventory_id,
          batch_id: line.batch_id,
          quantity: line.quantity,
          source_type: line.source_type,
          source_record_id: line.source_record_id ?? null,
          uom_code: line.uom_code ?? null,
          needs_list_item_id: line.needs_list_item_id ?? null,
        })),
        selected_method: this.selectedMethod(),
        override_reason_code: draft.override_reason_code.trim(),
        override_note: draft.override_note.trim(),
      },
      errors: [],
    };
  }

  setSubmitting(isSubmitting: boolean): void {
    this.submitting.set(isSubmitting);
  }

  setStartPreparationLoading(isLoading: boolean): void {
    this.startPreparationLoading.set(isLoading);
  }

  private hydrateDraft(current: NeedsListResponse): void {
    this.draft.update((draft) => ({
      ...draft,
      transport_mode: draft.transport_mode || current.waybill_payload?.transport_mode || '',
      override_reason_code: draft.override_reason_code || this.findStoredOverrideReason(current) || '',
      override_note: draft.override_note || this.findStoredOverrideNote(current) || '',
    }));
  }

  private initializeSelections(
    current: NeedsListResponse | null,
    options: AllocationOptionsResponse
  ): void {
    const nextSelections: Record<number, AllocationSelectionPayload[]> = {};
    for (const item of options.items) {
      const committed = (current?.allocation_lines ?? []).filter((line) => line.item_id === item.item_id);
      if (committed.length) {
        nextSelections[item.item_id] = this.sortSelections(
          item.item_id,
          committed.map((line) => ({
            item_id: line.item_id,
            inventory_id: line.inventory_id,
            batch_id: line.batch_id,
            quantity: line.quantity,
            source_type: line.source_type,
            source_record_id: line.source_record_id ?? null,
            uom_code: line.uom_code ?? null,
            needs_list_item_id: line.needs_list_item_id ?? item.needs_list_item_id,
          }))
        );
        continue;
      }
      nextSelections[item.item_id] = item.suggested_allocations.map((line) => ({
        item_id: line.item_id,
        inventory_id: line.inventory_id,
        batch_id: line.batch_id,
        quantity: line.quantity,
        source_type: line.source_type,
        source_record_id: line.source_record_id ?? null,
        uom_code: line.uom_code ?? null,
        needs_list_item_id: item.needs_list_item_id,
      }));
    }
    this.selectedRowsByItem.set(nextSelections);
  }

  private getItemGroup(itemId: number): AllocationItemGroup | undefined {
    return this.options()?.items.find((entry) => entry.item_id === itemId);
  }

  private sortSelections(itemId: number, rows: AllocationSelectionPayload[]): AllocationSelectionPayload[] {
    const group = this.getItemGroup(itemId);
    if (!group) {
      return [...rows];
    }
    const candidateOrder = new Map(group.candidates.map((candidate, index) => [this.selectionKey(candidate), index]));
    return [...rows].sort((left, right) =>
      (candidateOrder.get(this.selectionKey(left)) ?? Number.MAX_SAFE_INTEGER)
      - (candidateOrder.get(this.selectionKey(right)) ?? Number.MAX_SAFE_INTEGER)
    );
  }

  private selectionKey(
    value: Pick<AllocationSelectionPayload, 'inventory_id' | 'batch_id' | 'source_type' | 'source_record_id'>
      | Pick<AllocationCandidate, 'inventory_id' | 'batch_id' | 'source_type' | 'source_record_id'>
  ): string {
    return [
      String(value.inventory_id),
      String(value.batch_id),
      String(value.source_type || 'ON_HAND').toUpperCase(),
      String(value.source_record_id ?? ''),
    ].join('|');
  }

  private selectionSignature(rows: AllocationSelectionPayload[]): string {
    return rows
      .filter((row) => this.toNumber(row.quantity) > 0)
      .map((row) => ({
        key: this.selectionKey(row),
        quantity: this.formatQuantity(this.toNumber(row.quantity)),
      }))
      .sort((left, right) => left.key.localeCompare(right.key))
      .map((row) => `${row.key}:${row.quantity}`)
      .join(';');
  }

  private normalizeSelectedMethod(value: unknown): ExecutionSelectedMethod | null {
    const normalized = String(value ?? '').trim().toUpperCase();
    if (normalized === 'FEFO' || normalized === 'FIFO' || normalized === 'MIXED' || normalized === 'MANUAL') {
      return normalized;
    }
    return null;
  }

  private findStoredOverrideReason(current: NeedsListResponse): string | null {
    return current.allocation_lines?.find((line) => !!String(line.override_reason_code ?? '').trim())?.override_reason_code ?? null;
  }

  private findStoredOverrideNote(current: NeedsListResponse): string | null {
    return current.allocation_lines?.find((line) => !!String(line.override_note ?? '').trim())?.override_note ?? null;
  }

  private toNumber(value: string | number | null | undefined): number {
    if (typeof value === 'number') {
      return Number.isFinite(value) ? value : 0;
    }
    const parsed = Number.parseFloat(String(value ?? '0'));
    return Number.isFinite(parsed) ? parsed : 0;
  }

  private toFixedQuantity(value: number): number {
    return Math.round(value * 10_000) / 10_000;
  }

  private formatQuantity(value: number): string {
    return this.toFixedQuantity(value).toFixed(4);
  }

  private extractError(error: HttpErrorResponse, fallback: string): string {
    const errorMap = error.error?.errors;
    if (errorMap && typeof errorMap === 'object') {
      const messages = Object.values(errorMap)
        .flatMap((value) => Array.isArray(value) ? value : [value])
        .map((value) => String(value ?? '').trim())
        .filter(Boolean);
      if (messages.length) {
        return messages[0];
      }
    }
    const directMessage = typeof error.error?.message === 'string' ? error.error.message.trim() : '';
    const fallbackDetail = typeof error.error?.detail === 'string' ? error.error.detail.trim() : '';
    return directMessage || fallbackDetail || fallback;
  }
}

export const EXECUTION_OVERRIDE_OPTIONS = EXECUTION_OVERRIDE_REASON_OPTIONS;
