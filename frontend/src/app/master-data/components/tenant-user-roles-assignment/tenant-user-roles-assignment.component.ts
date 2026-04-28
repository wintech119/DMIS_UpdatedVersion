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
import { MatAutocompleteModule, MatAutocompleteSelectedEvent } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { MasterRecord } from '../../models/master-data.models';
import { MasterDataService } from '../../services/master-data.service';
import { IamAssignmentService, UserRoleAssignment } from '../../services/iam-assignment.service';
import {
  ConfirmDialogData,
  DmisConfirmDialogComponent,
} from '../../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';

interface RoleOption {
  role_id: number;
  code: string;
  name: string;
}

@Component({
  selector: 'dmis-tenant-user-roles-assignment',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatAutocompleteModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatSnackBarModule,
    MatTooltipModule,
  ],
  templateUrl: './tenant-user-roles-assignment.component.html',
  styleUrl: './tenant-user-roles-assignment.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TenantUserRolesAssignmentComponent implements OnInit {
  readonly tenantId = input.required<number>();
  readonly userId = input.required<number>();
  readonly tenantCode = input('');
  readonly username = input('');
  readonly changed = output<void>();

  private readonly assignmentService = inject(IamAssignmentService);
  private readonly masterData = inject(MasterDataService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);

  readonly roleControl = new FormControl<RoleOption | string>('', {
    nonNullable: true,
    validators: [Validators.maxLength(80)],
  });

  readonly roles = signal<UserRoleAssignment[]>([]);
  readonly roleOptions = signal<RoleOption[]>([]);
  readonly isLoading = signal(true);
  readonly isSaving = signal(false);
  readonly errorMessage = signal('');
  readonly roleQuery = signal('');
  readonly selectedRoleId = signal<number | null>(null);
  readonly highlightedRoleIds = signal<ReadonlySet<number>>(new Set<number>());

  readonly availableRoles = computed(() => {
    const assigned = new Set(this.roles().map((role) => role.role_id));
    const query = this.roleQuery().trim().toLowerCase();
    return this.roleOptions()
      .filter((role) => !assigned.has(role.role_id))
      .filter((role) => this.matchesRole(role, query))
      .slice(0, 25);
  });

  readonly selectedRole = computed(() => {
    const roleId = this.selectedRoleId();
    if (roleId == null) {
      return null;
    }
    return this.roleOptions().find((role) => role.role_id === roleId) ?? null;
  });

  readonly displayRole = (value: RoleOption | string | null): string => {
    if (!value) {
      return '';
    }
    if (typeof value === 'string') {
      return value;
    }
    return `${value.code} - ${value.name}`;
  };

  constructor() {
    this.roleControl.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((value) => {
      if (typeof value === 'string') {
        this.roleQuery.set(value);
        this.selectedRoleId.set(null);
      }
    });
  }

  ngOnInit(): void {
    this.loadAssignments();
    this.loadRoleOptions();
  }

  loadAssignments(): void {
    this.isLoading.set(true);
    this.errorMessage.set('');
    this.assignmentService.listTenantUserRoles(this.tenantId(), this.userId()).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (roles) => {
        this.roles.set(roles);
        this.isLoading.set(false);
      },
      error: (error: unknown) => {
        this.isLoading.set(false);
        this.errorMessage.set(this.getErrorMessage(error, 'Unable to load tenant-scoped roles.'));
      },
    });
  }

  loadRoleOptions(): void {
    this.masterData.list('role', { limit: 500, orderBy: 'code' }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.roleOptions.set(response.results.map((record) => this.toRoleOption(record)).filter(this.isRoleOption));
      },
      error: (error: unknown) => {
        this.showToastIfClientError(error, 'Unable to load available roles.');
      },
    });
  }

  onRoleSelected(event: MatAutocompleteSelectedEvent): void {
    const role = event.option.value as RoleOption;
    this.selectedRoleId.set(role.role_id);
    this.roleQuery.set(role.code);
  }

  assignSelectedRole(): void {
    const role = this.selectedRole();
    if (!role || this.isSaving()) {
      return;
    }
    this.isSaving.set(true);
    this.assignmentService.assignTenantUserRole(this.tenantId(), this.userId(), role.role_id).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.isSaving.set(false);
        this.roleControl.setValue('');
        this.roleQuery.set('');
        this.selectedRoleId.set(null);
        this.markHighlighted(role.role_id);
        this.changed.emit();
        this.loadAssignments();
      },
      error: (error: unknown) => {
        this.isSaving.set(false);
        this.showToastIfClientError(error, 'Unable to assign tenant-scoped role.');
      },
    });
  }

  confirmRevoke(role: UserRoleAssignment): void {
    if (this.isSaving()) {
      return;
    }
    const tenantLabel = this.tenantCode().trim() || `tenant ${this.tenantId()}`;
    const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
      data: {
        title: 'Remove tenant role',
        message: `Remove role ${role.code} from this user in ${tenantLabel}? Their global user roles remain separate.`,
        confirmLabel: 'Remove role',
        cancelLabel: 'Keep role',
        icon: 'delete_outline',
      } as ConfirmDialogData,
      width: '440px',
    });

    dialogRef.afterClosed().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((confirmed) => {
      if (confirmed) {
        this.revokeRole(role.role_id);
      }
    });
  }

  roleTone(role: Pick<UserRoleAssignment, 'code'>): 'warning' | 'neutral' {
    return role.code === 'SYSTEM_ADMINISTRATOR' ? 'warning' : 'neutral';
  }

  roleIcon(role: Pick<UserRoleAssignment, 'code'>): string {
    return role.code === 'SYSTEM_ADMINISTRATOR' ? 'shield' : 'badge';
  }

  isHighlighted(roleId: number): boolean {
    return this.highlightedRoleIds().has(roleId);
  }

  tenantContextLabel(): string {
    return this.tenantCode().trim() || `tenant ${this.tenantId()}`;
  }

  roleMeta(role: UserRoleAssignment): string {
    if (!role.assigned_at) {
      return 'Tenant scoped';
    }
    return this.formatRelative(role.assigned_at);
  }

  private revokeRole(roleId: number): void {
    this.isSaving.set(true);
    this.assignmentService.revokeTenantUserRole(this.tenantId(), this.userId(), roleId).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.isSaving.set(false);
        this.changed.emit();
        this.loadAssignments();
      },
      error: (error: unknown) => {
        this.isSaving.set(false);
        this.showToastIfClientError(error, 'Unable to remove tenant-scoped role.');
      },
    });
  }

  private markHighlighted(roleId: number): void {
    this.highlightedRoleIds.set(new Set([roleId]));
    window.setTimeout(() => this.highlightedRoleIds.set(new Set<number>()), 650);
  }

  private formatRelative(value: string): string {
    const parsed = Date.parse(value);
    if (Number.isNaN(parsed)) {
      return 'Tenant scoped';
    }
    const minutes = Math.max(0, Math.round((Date.now() - parsed) / 60000));
    if (minutes < 1) {
      return 'Just now';
    }
    if (minutes < 60) {
      return `${minutes}m ago`;
    }
    if (minutes < 1440) {
      return `${Math.floor(minutes / 60)}h ago`;
    }
    return `${Math.floor(minutes / 1440)}d ago`;
  }

  private toRoleOption(record: MasterRecord): RoleOption | null {
    const roleId = Number(record['id'] ?? record['role_id']);
    if (!Number.isInteger(roleId) || roleId <= 0) {
      return null;
    }
    return {
      role_id: roleId,
      code: String(record['code'] ?? '').trim(),
      name: String(record['name'] ?? '').trim(),
    };
  }

  private isRoleOption(value: RoleOption | null): value is RoleOption {
    return value != null;
  }

  private matchesRole(role: RoleOption, query: string): boolean {
    if (!query) {
      return true;
    }
    return `${role.code} ${role.name}`.toLowerCase().includes(query);
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
