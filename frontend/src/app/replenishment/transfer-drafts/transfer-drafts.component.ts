import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { TransferDraft, TransferDraftItem } from '../models/needs-list.model';
import { ReplenishmentService } from '../services/replenishment.service';
import { DmisNotificationService } from '../services/notification.service';
import { DmisEmptyStateComponent } from '../shared/dmis-empty-state/dmis-empty-state.component';
import { DmisSkeletonLoaderComponent } from '../shared/dmis-skeleton-loader/dmis-skeleton-loader.component';

interface EditableItem extends TransferDraftItem {
  adjusted_qty: number;
  reason: string;
}

@Component({
  selector: 'app-transfer-drafts',
  standalone: true,
  imports: [
    DecimalPipe,
    FormsModule,
    MatButtonModule,
    MatCardModule,
    MatDialogModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    DmisEmptyStateComponent,
    DmisSkeletonLoaderComponent
  ],
  templateUrl: './transfer-drafts.component.html',
  styleUrl: './transfer-drafts.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class TransferDraftsComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly replenishmentService = inject(ReplenishmentService);
  private readonly notifications = inject(DmisNotificationService);
  private readonly destroyRef = inject(DestroyRef);

  readonly loading = signal(true);
  readonly generating = signal(false);
  readonly error = signal(false);
  readonly transfers = signal<TransferDraft[]>([]);
  readonly editableItems = signal<Map<number, EditableItem[]>>(new Map());
  readonly confirmingId = signal<number | null>(null);

  private needsListId = '';

  readonly hasDrafts = computed(() => this.transfers().length > 0);
  readonly hasPendingDrafts = computed(() =>
    this.transfers().some(t => t.status === 'P')
  );

  constructor() {
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.needsListId = String(params.get('id') || '').trim();
      if (!this.needsListId) {
        this.error.set(true);
        this.loading.set(false);
        return;
      }
      this.loadTransfers();
    });
  }

  backToTracker(): void {
    this.router.navigate(['/replenishment/needs-list', this.needsListId, 'track']);
  }

  generateDrafts(): void {
    this.generating.set(true);
    this.replenishmentService.generateTransfers(this.needsListId).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (response) => {
        const transfers = response.transfers || [];
        const count = (response.transfers ?? []).length;
        this.transfers.set(transfers);
        this.buildEditableItems(transfers);
        this.generating.set(false);
        this.notifications.showSuccess(`Generated ${count} draft transfer(s).`);
      },
      error: () => {
        this.generating.set(false);
        this.notifications.showError('Failed to generate draft transfers.');
      }
    });
  }

  saveChanges(transferId: number): void {
    const items = this.editableItems().get(transferId) || [];
    const changed = items.filter(i => i.adjusted_qty !== i.item_qty);

    if (!changed.length) {
      this.notifications.showWarning('No changes to save.');
      return;
    }

    const reason = changed[0]?.reason || '';
    if (!reason.trim()) {
      this.notifications.showError('Reason is required when modifying quantities.');
      return;
    }

    this.replenishmentService.updateTransferDraft(this.needsListId, transferId, {
      reason,
      items: changed.map(i => ({ item_id: i.item_id, item_qty: i.adjusted_qty }))
    }).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: () => {
        this.notifications.showSuccess('Transfer draft updated.');
        this.loadTransfers();
      },
      error: () => {
        this.notifications.showError('Failed to update transfer draft.');
      }
    });
  }

  confirmTransfer(transferId: number): void {
    this.confirmingId.set(transferId);
    this.replenishmentService.confirmTransfer(this.needsListId, transferId).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: () => {
        this.confirmingId.set(null);
        this.notifications.showSuccess('Transfer confirmed and dispatched.');
        this.loadTransfers();
      },
      error: () => {
        this.confirmingId.set(null);
        this.notifications.showError('Failed to confirm transfer.');
      }
    });
  }

  isConfirming(transferId: number): boolean {
    return this.confirmingId() === transferId;
  }

  isDraft(transfer: TransferDraft): boolean {
    return transfer.status === 'P';
  }

  getStatusLabel(status: string): string {
    switch (status) {
      case 'P': return 'Draft';
      case 'D': return 'Dispatched';
      case 'C': return 'Completed';
      case 'V': return 'Verified';
      default: return status;
    }
  }

  private loadTransfers(): void {
    this.loading.set(true);
    this.error.set(false);

    this.replenishmentService.getTransfers(this.needsListId).pipe(
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: (response) => {
        this.transfers.set(response.transfers || []);
        this.buildEditableItems(response.transfers || []);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
        this.notifications.showError('Failed to load transfers.');
      }
    });
  }

  private buildEditableItems(transfers: TransferDraft[]): void {
    const map = new Map<number, EditableItem[]>();
    for (const t of transfers) {
      map.set(t.transfer_id, t.items.map(item => ({
        ...item,
        adjusted_qty: item.item_qty,
        reason: ''
      })));
    }
    this.editableItems.set(map);
  }
}
