import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormControl, Validators } from '@angular/forms';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin, of } from 'rxjs';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTooltipModule } from '@angular/material/tooltip';

import { MasterRecord } from '../../models/master-data.models';
import { MasterDataService } from '../../services/master-data.service';
import { IamAssignmentService, RolePermission } from '../../services/iam-assignment.service';
import {
  ConfirmDialogData,
  DmisConfirmDialogComponent,
} from '../../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';

interface PermissionOption {
  perm_id: number;
  resource: string;
  action: string;
}

@Component({
  selector: 'dmis-role-permissions-assignment',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatExpansionModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSnackBarModule,
    MatTabsModule,
    MatTooltipModule,
  ],
  templateUrl: './role-permissions-assignment.component.html',
  styleUrl: './role-permissions-assignment.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RolePermissionsAssignmentComponent implements OnInit {
  readonly roleId = input.required<number>();
  readonly changed = output<void>();

  private readonly assignmentService = inject(IamAssignmentService);
  private readonly masterData = inject(MasterDataService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);

  readonly searchControl = new FormControl('', {
    nonNullable: true,
    validators: [Validators.maxLength(80)],
  });

  readonly assignedPermissions = signal<RolePermission[]>([]);
  readonly permissionOptions = signal<PermissionOption[]>([]);
  readonly isLoading = signal(true);
  readonly isSaving = signal(false);
  readonly errorMessage = signal('');
  readonly searchQuery = signal('');
  readonly selectedAvailableIds = signal<ReadonlySet<number>>(new Set<number>());
  readonly selectedAssignedIds = signal<ReadonlySet<number>>(new Set<number>());

  private readonly lastAvailableIndex = signal<number | null>(null);
  private readonly lastAssignedIndex = signal<number | null>(null);

  readonly assignedIdSet = computed(() => new Set(this.assignedPermissions().map((permission) => permission.perm_id)));

  readonly availablePermissions = computed(() => {
    const assigned = this.assignedIdSet();
    const query = this.searchQuery().trim().toLowerCase();
    return this.permissionOptions()
      .filter((permission) => !assigned.has(permission.perm_id))
      .filter((permission) => this.matchesPermission(permission, query));
  });

  readonly filteredAssignedPermissions = computed(() => {
    const query = this.searchQuery().trim().toLowerCase();
    return this.assignedPermissions().filter((permission) => this.matchesPermission(permission, query));
  });

  constructor() {
    this.searchControl.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((value) => this.searchQuery.set(value));
  }

  ngOnInit(): void {
    this.loadAssignments();
    this.loadPermissionOptions();
  }

  loadAssignments(): void {
    this.isLoading.set(true);
    this.errorMessage.set('');
    this.assignmentService.listRolePermissions(this.roleId()).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (permissions) => {
        this.assignedPermissions.set(permissions);
        this.isLoading.set(false);
      },
      error: (error: unknown) => {
        this.isLoading.set(false);
        this.errorMessage.set(this.getErrorMessage(error, 'Unable to load role permissions.'));
      },
    });
  }

  loadPermissionOptions(): void {
    this.masterData.list('permission', { limit: 1000, orderBy: 'resource' }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.permissionOptions.set(response.results.map((record) => this.toPermissionOption(record)).filter(this.isPermissionOption));
      },
      error: (error: unknown) => {
        this.showToastIfClientError(error, 'Unable to load available permissions.');
      },
    });
  }

  toggleAvailable(permission: PermissionOption, index: number, event: MouseEvent): void {
    this.selectedAvailableIds.set(this.toggleId(
      this.selectedAvailableIds(),
      permission.perm_id,
      event.shiftKey ? this.getRangeIds(this.availablePermissions(), this.lastAvailableIndex() ?? index, index) : [],
    ));
    this.lastAvailableIndex.set(index);
  }

  toggleAssigned(permission: RolePermission, index: number, event: MouseEvent): void {
    this.selectedAssignedIds.set(this.toggleId(
      this.selectedAssignedIds(),
      permission.perm_id,
      event.shiftKey ? this.getRangeIds(this.filteredAssignedPermissions(), this.lastAssignedIndex() ?? index, index) : [],
    ));
    this.lastAssignedIndex.set(index);
  }

  assignSelectedPermissions(): void {
    const ids = [...this.selectedAvailableIds()];
    if (ids.length === 0 || this.isSaving()) {
      return;
    }
    this.assignPermissionIds(ids);
  }

  assignPermission(permission: PermissionOption): void {
    if (this.isSaving()) {
      return;
    }
    this.assignPermissionIds([permission.perm_id]);
  }

  revokeSelectedPermissions(): void {
    const ids = [...this.selectedAssignedIds()];
    if (ids.length === 0 || this.isSaving()) {
      return;
    }
    if (ids.length >= 5) {
      const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
        data: {
          title: 'Remove permissions',
          message: `Remove ${ids.length} permissions from this role? Users with only this role will lose those capabilities.`,
          confirmLabel: 'Remove permissions',
          cancelLabel: 'Keep permissions',
          icon: 'delete_sweep',
        } as ConfirmDialogData,
        width: '440px',
      });
      dialogRef.afterClosed().pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe((confirmed) => {
        if (confirmed) {
          this.revokePermissionIds(ids);
        }
      });
      return;
    }

    this.revokePermissionIds(ids);
  }

  revokePermission(permission: RolePermission): void {
    if (this.isSaving()) {
      return;
    }
    this.revokePermissionIds([permission.perm_id]);
  }

  permissionLabel(permission: Pick<RolePermission, 'resource' | 'action'>): string {
    return `${permission.resource}.${permission.action}`;
  }

  permissionTone(permission: Pick<RolePermission, 'resource' | 'action'>): 'warning' | 'info' | 'neutral' {
    const label = this.permissionLabel(permission).toLowerCase();
    if (label === 'tenant.act_cross_tenant') {
      return 'info';
    }
    if (label.includes('.advanced.') || label.endsWith('.delete') || permission.action.toLowerCase() === 'delete') {
      return 'warning';
    }
    return 'neutral';
  }

  permissionIcon(permission: Pick<RolePermission, 'resource' | 'action'>): string {
    const tone = this.permissionTone(permission);
    if (tone === 'warning') {
      return 'warning_amber';
    }
    if (tone === 'info') {
      return 'tune';
    }
    return 'key';
  }

  isAvailableSelected(permId: number): boolean {
    return this.selectedAvailableIds().has(permId);
  }

  isAssignedSelected(permId: number): boolean {
    return this.selectedAssignedIds().has(permId);
  }

  hasScope(permission: RolePermission): boolean {
    return permission.scope_json != null;
  }

  formatScope(scopeJson: object | null | undefined): string {
    if (scopeJson == null) {
      return '';
    }
    return JSON.stringify(scopeJson, null, 2);
  }

  private assignPermissionIds(permIds: number[]): void {
    this.isSaving.set(true);
    const requests = permIds.map((permId) => this.assignmentService.assignRolePermission(this.roleId(), permId));
    forkJoin(requests.length ? requests : [of(void 0)]).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.isSaving.set(false);
        this.selectedAvailableIds.set(new Set<number>());
        this.changed.emit();
        this.loadAssignments();
      },
      error: (error: unknown) => {
        this.isSaving.set(false);
        this.showToastIfClientError(error, 'Unable to assign permission.');
      },
    });
  }

  private revokePermissionIds(permIds: number[]): void {
    this.isSaving.set(true);
    const requests = permIds.map((permId) => this.assignmentService.revokeRolePermission(this.roleId(), permId));
    forkJoin(requests.length ? requests : [of(void 0)]).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.isSaving.set(false);
        this.selectedAssignedIds.set(new Set<number>());
        this.changed.emit();
        this.loadAssignments();
      },
      error: (error: unknown) => {
        this.isSaving.set(false);
        this.showToastIfClientError(error, 'Unable to remove permission.');
      },
    });
  }

  private toggleId(current: ReadonlySet<number>, id: number, rangeIds: number[]): ReadonlySet<number> {
    const next = new Set(current);
    const ids = rangeIds.length ? rangeIds : [id];
    const shouldAdd = !next.has(id);
    for (const rangeId of ids) {
      if (shouldAdd) {
        next.add(rangeId);
      } else {
        next.delete(rangeId);
      }
    }
    return next;
  }

  private getRangeIds<T extends { perm_id: number }>(items: T[], previousIndex: number, currentIndex: number): number[] {
    const start = Math.min(previousIndex, currentIndex);
    const end = Math.max(previousIndex, currentIndex);
    return items.slice(start, end + 1).map((item) => item.perm_id);
  }

  private toPermissionOption(record: MasterRecord): PermissionOption | null {
    const permId = Number(record['perm_id']);
    if (!Number.isInteger(permId) || permId <= 0) {
      return null;
    }
    return {
      perm_id: permId,
      resource: String(record['resource'] ?? '').trim(),
      action: String(record['action'] ?? '').trim(),
    };
  }

  private isPermissionOption(value: PermissionOption | null): value is PermissionOption {
    return value != null;
  }

  private matchesPermission(permission: Pick<RolePermission, 'resource' | 'action'>, query: string): boolean {
    if (!query) {
      return true;
    }
    return this.permissionLabel(permission).toLowerCase().includes(query);
  }

  private showToastIfClientError(error: unknown, fallback: string): void {
    const message = this.getErrorMessage(error, fallback);
    this.errorMessage.set(message);
    const status = this.getHttpStatus(error);
    if (status >= 400 && status < 500) {
      this.snackBar.open(message, 'Dismiss', { duration: 5000 });
    }
  }

  private getHttpStatus(error: unknown): number {
    return typeof (error as { status?: unknown })?.status === 'number'
      ? (error as { status: number }).status
      : 0;
  }

  private getErrorMessage(error: unknown, fallback: string): string {
    const responseError = error as { error?: { detail?: unknown; errors?: Record<string, unknown> } };
    const detail = responseError.error?.detail;
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
    const fieldErrors = responseError.error?.errors;
    const firstFieldError = fieldErrors ? Object.values(fieldErrors)[0] : null;
    if (typeof firstFieldError === 'string' && firstFieldError.trim()) {
      return firstFieldError;
    }
    return fallback;
  }
}
