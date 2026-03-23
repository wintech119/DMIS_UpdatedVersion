import {
  Component, OnInit, DestroyRef, ChangeDetectionStrategy,
  inject, signal, computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Clipboard } from '@angular/cdk/clipboard';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatCardModule } from '@angular/material/card';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { CatalogEditGuidance, MasterFieldConfig, MasterRecord, MasterTableConfig } from '../../models/master-data.models';
import { ALL_TABLE_CONFIGS } from '../../models/table-configs';
import { MasterDataService } from '../../services/master-data.service';
import { MasterEditGateService } from '../../services/master-edit-gate.service';
import { DmisNotificationService } from '../../../replenishment/services/notification.service';
import { DmisConfirmDialogComponent, ConfirmDialogData } from '../../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';
import { MasterEditGateDialogComponent } from '../master-edit-gate-dialog/master-edit-gate-dialog.component';

@Component({
  selector: 'dmis-master-detail-page',
  standalone: true,
  imports: [
    CommonModule, RouterModule,
    MatButtonModule, MatIconModule, MatCardModule, MatTooltipModule,
    MatDialogModule, MatProgressBarModule,
  ],
  templateUrl: './master-detail-page.component.html',
  styleUrl: './master-detail-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MasterDetailPageComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(MasterDataService);
  private editGate = inject(MasterEditGateService);
  private notify = inject(DmisNotificationService);
  private dialog = inject(MatDialog);
  private clipboard = inject(Clipboard);
  private destroyRef = inject(DestroyRef);
  private latestRecordRequestId = 0;

  config = signal<MasterTableConfig | null>(null);
  record = signal<MasterRecord | null>(null);
  editGuidance = signal<CatalogEditGuidance | null>(null);
  isLoading = signal(true);
  pk = signal<string | number | null>(null);
  itemUomConversions = signal<{uom_code: string; conversion_factor: number; is_default?: boolean}[]>([]);

  isItemRecord = computed(() => this.config()?.tableKey === 'items');

  auditExpanded = signal(false);

  isActive = computed(() => {
    const r = this.record();
    const cfg = this.config();
    if (!r || !cfg) return false;
    return r[cfg.statusField || 'status_code'] === 'A';
  });

  readonly recordTitle = computed(() => {
    return this.editGate.getRecordTitle(this.record(), this.config(), this.pk());
  });

  readonly statusGroup = computed(() => {
    const cfg = this.config();
    if (!cfg || cfg.hasStatus === false) return null;
    const includedFields = new Set<string>();
    const statusFieldName = cfg.statusField || 'status_code';
    const statusFields = cfg.formFields.filter((field) => {
      const shouldInclude = field.group === 'Status' || field.field === statusFieldName;
      if (!shouldInclude || includedFields.has(field.field)) {
        return false;
      }
      includedFields.add(field.field);
      return true;
    });
    if (statusFields.length === 0) return null;
    return statusFields;
  });

  /** Group form fields for display sections */
  fieldGroups = computed(() => {
    const cfg = this.config();
    if (!cfg) return [];
    const groups: { label: string; fields: MasterFieldConfig[] }[] = [];
    const seen = new Map<string, MasterFieldConfig[]>();

    for (const f of cfg.formFields) {
      if (f.group === 'Status') continue;
      const groupLabel = f.group || 'General';
      if (!seen.has(groupLabel)) {
        seen.set(groupLabel, []);
        groups.push({ label: groupLabel, fields: seen.get(groupLabel)! });
      }
      seen.get(groupLabel)!.push(f);
    }
    return groups;
  });

  ngOnInit(): void {
    this.route.data.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(data => {
      const routePath = data['routePath'] as string;
      const cfg = ALL_TABLE_CONFIGS[routePath];
      if (cfg) {
        this.config.set(cfg);
      }
    });

    this.route.params.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(params => {
      const pkParam = params['pk'];
      if (pkParam) {
        this.pk.set(pkParam);
        this.loadRecord();
      }
    });
  }

  private loadRecord(): void {
    const cfg = this.config();
    if (!cfg || !this.pk()) return;

    const requestId = ++this.latestRecordRequestId;
    this.isLoading.set(true);
    this.service.get(cfg.tableKey, this.pk()!).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: res => {
        if (requestId !== this.latestRecordRequestId) return;
        this.record.set(res.record);
        this.editGuidance.set(this.editGate.getEffectiveCatalogEditGuidance(cfg, res.edit_guidance));

        // Extract UOM conversions for item records
        const uomOptions = res.record['uom_options'] as
          Array<{ uom_code: string; conversion_factor: number; is_default?: boolean }> | undefined;
        if (Array.isArray(uomOptions)) {
          this.itemUomConversions.set(
            uomOptions.map(o => ({
              uom_code: o.uom_code,
              conversion_factor: o.conversion_factor,
              is_default: o.is_default,
            })),
          );
        } else {
          this.itemUomConversions.set([]);
        }

        this.isLoading.set(false);
      },
      error: () => {
        if (requestId !== this.latestRecordRequestId) return;
        this.isLoading.set(false);
        this.notify.showError('Record not found.');
        this.navigateBack();
      },
    });
  }

  onEdit(): void {
    const cfg = this.config();
    if (!cfg || !this.pk()) return;

    const dialogRef = this.dialog.open(MasterEditGateDialogComponent, {
      data: this.editGate.buildDialogData({
        config: cfg,
        recordName: this.recordTitle(),
        editGuidance: this.editGuidance(),
        isEdit: true,
      }),
      width: '460px',
      panelClass: 'dmis-edit-gate-panel',
      autoFocus: 'first-tabbable',
      ariaLabelledBy: 'gate-dialog-title',
    });

    dialogRef.afterClosed().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe(confirmed => {
      if (confirmed) {
        if (this.editGate.isGovernedCatalogTable(cfg.tableKey)) {
          this.editGate.markDetailEditGatePassed();
        }
        this.router.navigate(['/master-data', cfg.routePath, this.pk(), 'edit']);
      }
    });
  }

  onToggleStatus(): void {
    const cfg = this.config();
    const r = this.record();
    if (!cfg || !r) return;
    const versionNbr = this.coerceVersionNumber(r['version_nbr']);

    if (this.isActive()) {
      const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
        data: {
          title: 'Confirm Inactivation',
          message: 'Are you sure you want to inactivate this record?',
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
          this.service.inactivate(cfg.tableKey, this.pk()!, versionNbr).pipe(
            takeUntilDestroyed(this.destroyRef),
          ).subscribe({
            next: () => {
              this.notify.showSuccess('Record inactivated.');
              this.loadRecord();
            },
            error: (err) => {
              const blocking = err.error?.blocking;
              if (blocking?.length) {
                this.notify.showError(`Cannot inactivate: referenced by ${blocking.join(', ')}`);
              } else {
                this.notify.showError(err.error?.detail || 'Inactivation failed.');
              }
            },
          });
        }
      });
    } else {
      this.service.activate(cfg.tableKey, this.pk()!, versionNbr).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: () => {
          this.notify.showSuccess('Record activated.');
          this.loadRecord();
        },
        error: () => this.notify.showError('Activation failed.'),
      });
    }
  }

  /** Map section group labels to Material icons */
  private readonly sectionIconMap: Record<string, string> = {
    'Basic Information': 'info',
    'General': 'info',
    'Details': 'description',
    'Contact': 'contact_phone',
    'Contact Information': 'contact_phone',
    'Address': 'location_on',
    'Location': 'location_on',
    'Status': 'toggle_on',
    'Inventory Settings': 'inventory_2',
    'Procurement': 'shopping_cart',
    'Financial': 'payments',
    'Item Identity': 'label',
    'Classification': 'category',
    'Inventory Rules': 'inventory_2',
    'Tracking & Behaviour': 'track_changes',
    'UOM & Conversions': 'swap_horiz',
    'Notes & Storage': 'notes',
  };

  getSectionIcon(groupLabel: string): string {
    return this.sectionIconMap[groupLabel] || 'folder';
  }

  getDisplayValue(field: MasterFieldConfig, value: unknown): string {
    const record = this.record();
    const companionDisplayValue = field.displayField && record
      ? record[field.displayField]
      : undefined;
    const displayValue = companionDisplayValue != null && companionDisplayValue !== ''
      ? companionDisplayValue
      : value;

    if (displayValue == null || displayValue === '') return '-';
    if (field.type === 'boolean') return displayValue ? 'Yes' : 'No';
    if (field.type === 'select' && field.options) {
      const opt = field.options.find((option) => option.value === displayValue);
      return opt?.label || String(displayValue);
    }
    return String(displayValue);
  }

  getStatusLabel(): string {
    const r = this.record();
    const cfg = this.config();
    if (!r || !cfg) return '';
    const val = r[cfg.statusField || 'status_code'];
    if (val === 'A') return cfg.activeLabel || 'Active';
    return cfg.inactiveLabel || 'Inactive';
  }

  getAuditCreatedAt(record: MasterRecord): string | number | Date | null {
    return this.toDateInput(record['create_dtime'] ?? record['created_at']);
  }

  getAuditUpdatedAt(record: MasterRecord): string | number | Date | null {
    return this.toDateInput(record['update_dtime'] ?? record['updated_at']);
  }

  getDefaultUomLabel(): string {
    const record = this.record();
    const desc = record?.['default_uom_desc'];
    if (desc) return String(desc);
    const code = record?.['default_uom_code'];
    return code ? String(code) : 'units';
  }

  getUomLabel(uomCode: string): string {
    if (!uomCode) return '';
    // Check if it's the default UOM
    const record = this.record();
    if (record && String(record['default_uom_code']).toUpperCase() === uomCode.toUpperCase()) {
      return this.getDefaultUomLabel();
    }
    return uomCode;
  }

  private toPositiveInt(value: unknown): number | null {
    if (value == null || value === '') return null;
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed <= 0) return null;
    return parsed;
  }

  private toDateInput(value: unknown): string | number | Date | null {
    if (value == null) return null;
    if (value instanceof Date) return value;
    if (typeof value === 'string' || typeof value === 'number') return value;
    return null;
  }

  private coerceVersionNumber(value: unknown): number | undefined {
    return typeof value === 'number' ? value : undefined;
  }

  isEmptyValue(value: unknown): boolean {
    return value == null || value === '';
  }

  isCopyableField(fieldName: string): boolean {
    return fieldName.endsWith('_code') || fieldName.endsWith('_id');
  }

  copyValue(value: unknown): void {
    if (value == null || value === '') return;
    const copied = this.clipboard.copy(String(value));
    if (copied) {
      this.notify.showSuccess('Copied to clipboard');
    }
  }

  navigateBack(): void {
    const cfg = this.config();
    if (cfg) {
      this.router.navigate(['/master-data', cfg.routePath]);
    }
  }
}

