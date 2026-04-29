import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormControl, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatAutocompleteModule, MatAutocompleteSelectedEvent } from '@angular/material/autocomplete';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectChange, MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { MasterRecord } from '../../models/master-data.models';
import { MasterDataService } from '../../services/master-data.service';
import { IamAssignmentService, TenantAccessLevel, TenantUser } from '../../services/iam-assignment.service';
import { TenantUserRolesAssignmentComponent } from '../tenant-user-roles-assignment/tenant-user-roles-assignment.component';
import {
  ConfirmDialogData,
  DmisConfirmDialogComponent,
} from '../../../replenishment/shared/dmis-confirm-dialog/dmis-confirm-dialog.component';

interface UserOption {
  user_id: number;
  username: string;
  email: string;
}

type TenantUserSort = 'username' | 'access_level' | 'last_login';

const ACCESS_LEVELS: TenantAccessLevel[] = ['ADMIN', 'FULL', 'STANDARD', 'LIMITED', 'READ_ONLY'];

@Component({
  selector: 'dmis-tenant-users-assignment',
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
    MatSelectModule,
    MatSlideToggleModule,
    MatSnackBarModule,
    MatTooltipModule,
    TenantUserRolesAssignmentComponent,
  ],
  templateUrl: './tenant-users-assignment.component.html',
  styleUrl: './tenant-users-assignment.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TenantUsersAssignmentComponent implements OnInit {
  readonly tenantId = input.required<number>();
  readonly tenantCode = input('');
  readonly deepLinkUserId = input<number | null>(null);
  readonly changed = output<void>();

  private readonly assignmentService = inject(IamAssignmentService);
  private readonly masterData = inject(MasterDataService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly dialog = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  readonly userControl = new FormControl<UserOption | string>('', {
    nonNullable: true,
    validators: [Validators.maxLength(120)],
  });

  readonly accessControl = new FormControl<TenantAccessLevel>('STANDARD', {
    nonNullable: true,
    validators: [Validators.required],
  });

  readonly users = signal<TenantUser[]>([]);
  readonly userOptions = signal<UserOption[]>([]);
  readonly isLoading = signal(true);
  readonly errorMessage = signal('');
  readonly isSaving = signal(false);
  readonly savingUserIds = signal<ReadonlySet<number>>(new Set<number>());
  readonly userQuery = signal('');
  readonly selectedUserId = signal<number | null>(null);
  readonly sortBy = signal<TenantUserSort>('username');
  readonly expandedUserId = signal<number | null>(null);

  readonly accessLevels = ACCESS_LEVELS;

  readonly sortedUsers = computed(() => {
    const sortBy = this.sortBy();
    return [...this.users()].sort((a, b) => this.compareTenantUsers(a, b, sortBy));
  });

  readonly availableUsers = computed(() => {
    const assigned = new Set(this.users().map((user) => user.user_id));
    const query = this.userQuery().trim().toLowerCase();
    return this.userOptions()
      .filter((user) => !assigned.has(user.user_id))
      .filter((user) => this.matchesUser(user, query))
      .slice(0, 25);
  });

  readonly selectedUser = computed(() => {
    const userId = this.selectedUserId();
    if (userId == null) {
      return null;
    }
    return this.userOptions().find((user) => user.user_id === userId) ?? null;
  });

  readonly displayUser = (value: UserOption | string | null): string => {
    if (!value) {
      return '';
    }
    if (typeof value === 'string') {
      return value;
    }
    return `${value.username} - ${value.email}`;
  };

  constructor() {
    this.userControl.valueChanges.pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((value) => {
      if (typeof value === 'string') {
        this.userQuery.set(value);
        this.selectedUserId.set(null);
      }
    });

    effect(() => {
      const deepLinkUserId = this.deepLinkUserId();
      if (deepLinkUserId != null && Number.isInteger(deepLinkUserId) && deepLinkUserId > 0) {
        this.expandedUserId.set(deepLinkUserId);
      } else if (deepLinkUserId == null) {
        this.expandedUserId.set(null);
      }
    });
  }

  ngOnInit(): void {
    this.loadAssignments();
    this.loadUserOptions();
  }

  loadAssignments(): void {
    this.isLoading.set(true);
    this.errorMessage.set('');
    this.assignmentService.listTenantUsers(this.tenantId()).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (users) => {
        this.users.set(users);
        this.isLoading.set(false);
      },
      error: (error: unknown) => {
        this.isLoading.set(false);
        this.errorMessage.set(this.getErrorMessage(error, 'Unable to load tenant users.'));
      },
    });
  }

  loadUserOptions(): void {
    this.masterData.list('user', { limit: 1000, orderBy: 'username' }).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response) => {
        this.userOptions.set(response.results.map((record) => this.toUserOption(record)).filter(this.isUserOption));
      },
      error: (error: unknown) => {
        this.showToastIfClientError(error, 'Unable to load available users.');
      },
    });
  }

  onUserSelected(event: MatAutocompleteSelectedEvent): void {
    const user = event.option.value as UserOption;
    this.selectedUserId.set(user.user_id);
    this.userQuery.set(user.username);
  }

  onSortChange(event: MatSelectChange): void {
    this.sortBy.set(event.value as TenantUserSort);
  }

  addSelectedUser(): void {
    const user = this.selectedUser();
    if (!user || this.isSaving()) {
      return;
    }

    this.isSaving.set(true);
    this.assignmentService.assignTenantUser(this.tenantId(), user.user_id, this.accessControl.value).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.isSaving.set(false);
        this.userControl.setValue('');
        this.userQuery.set('');
        this.selectedUserId.set(null);
        this.accessControl.setValue('STANDARD');
        this.changed.emit();
        this.loadAssignments();
      },
      error: (error: unknown) => {
        this.isSaving.set(false);
        this.showToastIfClientError(error, 'Unable to add user to tenant.');
      },
    });
  }

  onAccessLevelChange(user: TenantUser, nextLevel: TenantAccessLevel): void {
    if (user.access_level === nextLevel || this.isUserSaving(user.user_id)) {
      return;
    }
    if (user.access_level === 'ADMIN' && nextLevel !== 'ADMIN') {
      const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
        data: {
          title: 'Confirm access downgrade',
          message: `Downgrade ${user.username} from ADMIN in this tenant? Administrative access will be removed for this tenant context.`,
          confirmLabel: 'Downgrade',
          cancelLabel: 'Keep ADMIN',
          icon: 'admin_panel_settings',
        } as ConfirmDialogData,
        width: '440px',
      });
      dialogRef.afterClosed().pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe((confirmed) => {
        if (confirmed) {
          this.applyAccessLevelChange(user, nextLevel);
        }
      });
      return;
    }

    this.applyAccessLevelChange(user, nextLevel);
  }

  confirmRevoke(user: TenantUser): void {
    if (this.isSaving()) {
      return;
    }
    const dialogRef = this.dialog.open(DmisConfirmDialogComponent, {
      data: {
        title: 'Remove tenant user',
        message: `Remove ${user.username} from ${this.tenantContextLabel()}? Their tenant-scoped roles for this tenant will no longer apply.`,
        confirmLabel: 'Remove user',
        cancelLabel: 'Keep user',
        icon: 'person_remove',
      } as ConfirmDialogData,
      width: '440px',
    });

    dialogRef.afterClosed().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe((confirmed) => {
      if (confirmed) {
        this.revokeUser(user.user_id);
      }
    });
  }

  toggleRoles(user: TenantUser): void {
    const isExpanded = this.expandedUserId() === user.user_id;
    const nextUserId = isExpanded ? null : user.user_id;
    this.expandedUserId.set(nextUserId);
    if (nextUserId == null) {
      this.router.navigate(['/master-data', 'tenants', this.tenantId()]);
      return;
    }
    this.router.navigate(['/master-data', 'tenants', this.tenantId(), 'users', nextUserId, 'roles']);
  }

  handleRowKeydown(event: KeyboardEvent, user: TenantUser): void {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }
    event.preventDefault();
    this.toggleRoles(user);
  }

  accessTone(level: TenantAccessLevel): 'critical' | 'warning' | 'info' | 'neutral' {
    if (level === 'ADMIN') {
      return 'critical';
    }
    if (level === 'FULL') {
      return 'warning';
    }
    if (level === 'LIMITED' || level === 'READ_ONLY') {
      return 'info';
    }
    return 'neutral';
  }

  accessIcon(level: TenantAccessLevel): string {
    switch (level) {
      case 'ADMIN':
        return 'admin_panel_settings';
      case 'FULL':
        return 'verified';
      case 'LIMITED':
        return 'tune';
      case 'READ_ONLY':
        return 'visibility';
      default:
        return 'badge';
    }
  }

  avatarInitial(user: TenantUser): string {
    const source = user.username || user.email || '?';
    return source.trim().charAt(0).toUpperCase() || '?';
  }

  tenantContextLabel(): string {
    return this.tenantCode().trim() || `tenant ${this.tenantId()}`;
  }

  isExpanded(userId: number): boolean {
    return this.expandedUserId() === userId;
  }

  isUserSaving(userId: number): boolean {
    return this.savingUserIds().has(userId);
  }

  formatRelative(value: string | null | undefined): string {
    if (!value) {
      return 'No login yet';
    }
    const parsed = Date.parse(value);
    if (Number.isNaN(parsed)) {
      return 'No login yet';
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

  private applyAccessLevelChange(user: TenantUser, nextLevel: TenantAccessLevel): void {
    const previous = this.users();
    this.users.update((users) => users.map((item) => (
      item.user_id === user.user_id ? { ...item, access_level: nextLevel } : item
    )));
    this.setUserSaving(user.user_id, true);

    this.assignmentService.assignTenantUser(this.tenantId(), user.user_id, nextLevel).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.setUserSaving(user.user_id, false);
        this.changed.emit();
      },
      error: (error: unknown) => {
        this.users.set(previous);
        this.setUserSaving(user.user_id, false);
        this.showToastIfClientError(error, 'Unable to update access level.');
      },
    });
  }

  private revokeUser(userId: number): void {
    this.isSaving.set(true);
    this.assignmentService.revokeTenantUser(this.tenantId(), userId).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => {
        this.isSaving.set(false);
        if (this.expandedUserId() === userId) {
          this.expandedUserId.set(null);
        }
        this.changed.emit();
        this.loadAssignments();
      },
      error: (error: unknown) => {
        this.isSaving.set(false);
        this.showToastIfClientError(error, 'Unable to remove user from tenant.');
      },
    });
  }

  private setUserSaving(userId: number, isSaving: boolean): void {
    const next = new Set(this.savingUserIds());
    if (isSaving) {
      next.add(userId);
    } else {
      next.delete(userId);
    }
    this.savingUserIds.set(next);
  }

  private compareTenantUsers(a: TenantUser, b: TenantUser, sortBy: TenantUserSort): number {
    if (sortBy === 'access_level') {
      const accessRank = this.accessRank(a.access_level) - this.accessRank(b.access_level);
      return accessRank || a.username.localeCompare(b.username);
    }
    if (sortBy === 'last_login') {
      const left = a.last_login_at ? Date.parse(a.last_login_at) : 0;
      const right = b.last_login_at ? Date.parse(b.last_login_at) : 0;
      return right - left || a.username.localeCompare(b.username);
    }
    return a.username.localeCompare(b.username);
  }

  private accessRank(level: TenantAccessLevel): number {
    return ACCESS_LEVELS.indexOf(level);
  }

  private toUserOption(record: MasterRecord): UserOption | null {
    const userId = Number(record['user_id']);
    if (!Number.isInteger(userId) || userId <= 0) {
      return null;
    }
    return {
      user_id: userId,
      username: String(record['username'] ?? '').trim(),
      email: String(record['email'] ?? '').trim(),
    };
  }

  private isUserOption(value: UserOption | null): value is UserOption {
    return value != null;
  }

  private matchesUser(user: UserOption, query: string): boolean {
    if (!query) {
      return true;
    }
    return `${user.username} ${user.email}`.toLowerCase().includes(query);
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
