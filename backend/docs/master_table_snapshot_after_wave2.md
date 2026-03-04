# DMIS Master Table Audit Snapshot

- Generated at (UTC): `2026-03-03T22:21:02.971453+00:00`

## Table Status

| Table | Exists | Row Count |
|---|---:|---:|
| `agency` | `True` | `1` |
| `allocation_limit` | `True` | `0` |
| `allocation_priority_rule` | `False` | `None` |
| `allocation_rule` | `True` | `0` |
| `approval_authority_matrix` | `True` | `0` |
| `approval_reason_code` | `False` | `None` |
| `approval_threshold_policy` | `True` | `0` |
| `auth_group` | `True` | `0` |
| `auth_group_permissions` | `True` | `0` |
| `auth_permission` | `True` | `64` |
| `auth_user` | `True` | `0` |
| `auth_user_groups` | `True` | `0` |
| `auth_user_user_permissions` | `True` | `0` |
| `batchlocation` | `True` | `0` |
| `country` | `True` | `66` |
| `currency` | `True` | `37` |
| `custodian` | `True` | `3` |
| `distribution_package` | `True` | `0` |
| `event` | `True` | `3` |
| `event_phase` | `True` | `2` |
| `event_phase_config` | `True` | `5` |
| `event_severity_profile` | `False` | `None` |
| `hadr_aid_movement_staging` | `True` | `1562` |
| `item` | `True` | `457` |
| `item_location` | `True` | `0` |
| `itemcatg` | `True` | `5` |
| `itemcostdef` | `False` | `None` |
| `lead_time_config` | `True` | `6` |
| `location` | `True` | `0` |
| `parish` | `True` | `14` |
| `permission` | `True` | `11` |
| `ref_approval_tier` | `True` | `4` |
| `ref_event_phase` | `True` | `4` |
| `ref_procurement_method` | `True` | `4` |
| `ref_tenant_type` | `True` | `9` |
| `resource_capability_ref` | `False` | `None` |
| `role` | `True` | `15` |
| `role_scope_policy` | `False` | `None` |
| `supplier` | `True` | `4` |
| `tenant` | `True` | `28` |
| `tenant_access_policy` | `False` | `None` |
| `warehouse_sync_status` | `True` | `11` |

## Contradictions

- auth_permission contains 64 rows (framework metadata is populated).
- warehouse_sync_status contains 11 rows (drop must be staged).

## FK References To Flagged Tables

- `auth_group_permissions.group_id` -> `auth_group.id` (`auth_group_permissions_group_id_b120cbf9_fk_auth_group_id`)
- `auth_user_groups.group_id` -> `auth_group.id` (`auth_user_groups_group_id_97559544_fk_auth_group_id`)
- `auth_group_permissions.permission_id` -> `auth_permission.id` (`auth_group_permissio_permission_id_84c5c92e_fk_auth_perm`)
- `auth_user_user_permissions.permission_id` -> `auth_permission.id` (`auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm`)
- `auth_user_groups.user_id` -> `auth_user.id` (`auth_user_groups_user_id_6a12ed8b_fk_auth_user_id`)
- `auth_user_user_permissions.user_id` -> `auth_user.id` (`auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id`)
- `donation.origin_country_id` -> `country.country_id` (`fk_donation_country`)
- `donor.country_id` -> `country.country_id` (`donor_country_id_fkey`)
- `supplier.country_id` -> `country.country_id` (`supplier_country_id_fkey`)
- `donation.custodian_id` -> `custodian.custodian_id` (`fk_donation_custodian`)
- `warehouse.custodian_id` -> `custodian.custodian_id` (`warehouse_custodian_id_fkey`)
- `distribution_package_item.package_id` -> `distribution_package.id` (`distribution_package_item_package_id_fkey`)

## FK References From Flagged Tables

- `auth_group_permissions.group_id` -> `auth_group.id` (`auth_group_permissions_group_id_b120cbf9_fk_auth_group_id`)
- `auth_group_permissions.permission_id` -> `auth_permission.id` (`auth_group_permissio_permission_id_84c5c92e_fk_auth_perm`)
- `auth_permission.content_type_id` -> `django_content_type.id` (`auth_permission_content_type_id_2f476e4b_fk_django_co`)
- `auth_user_groups.group_id` -> `auth_group.id` (`auth_user_groups_group_id_97559544_fk_auth_group_id`)
- `auth_user_groups.user_id` -> `auth_user.id` (`auth_user_groups_user_id_6a12ed8b_fk_auth_user_id`)
- `auth_user_user_permissions.permission_id` -> `auth_permission.id` (`auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm`)
- `auth_user_user_permissions.user_id` -> `auth_user.id` (`auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id`)
- `batchlocation.batch_id` -> `itembatch.batch_id` (`fk_batchlocation_inventory`)
- `batchlocation.batch_id` -> `itembatch.batch_id` (`fk_batchlocation_itembatch`)
- `batchlocation.batch_id` -> `itembatch.inventory_id` (`fk_batchlocation_inventory`)
- `batchlocation.inventory_id` -> `itembatch.inventory_id` (`fk_batchlocation_inventory`)
- `batchlocation.inventory_id` -> `itembatch.batch_id` (`fk_batchlocation_inventory`)
- `batchlocation.inventory_id` -> `warehouse.warehouse_id` (`fk_batchlocation_warehouse`)
- `batchlocation.location_id` -> `location.location_id` (`fk_batchlocation_location`)
- `country.currency_code` -> `currency.currency_code` (`fk_country_currency`)
- `custodian.parish_code` -> `parish.parish_code` (`fk_custodian_parish`)
- `custodian.tenant_id` -> `tenant.tenant_id` (`custodian_tenant_id_fkey`)
- `distribution_package.assigned_warehouse_id` -> `warehouse.warehouse_id` (`distribution_package_assigned_warehouse_id_fkey`)
- `distribution_package.event_id` -> `event.event_id` (`distribution_package_event_id_fkey`)
- `distribution_package.recipient_agency_id` -> `agency.agency_id` (`distribution_package_recipient_agency_id_fkey`)
- `event_phase.ended_by` -> `user.user_id` (`event_phase_ended_by_fkey`)
- `event_phase.event_id` -> `event.event_id` (`event_phase_event_id_fkey`)
- `event_phase.phase_code` -> `ref_event_phase.phase_code` (`event_phase_phase_code_fkey`)
- `event_phase.started_by` -> `user.user_id` (`event_phase_started_by_fkey`)
- `event_phase_config.event_id` -> `event.event_id` (`event_phase_config_event_id_fkey`)
- `event_phase_config.phase` -> `ref_event_phase.phase_code` (`event_phase_config_phase_fkey`)
- `item_location.inventory_id` -> `inventory.inventory_id` (`fk_item_location_inventory`)
- `item_location.inventory_id` -> `inventory.item_id` (`fk_item_location_inventory`)
- `item_location.item_id` -> `inventory.item_id` (`fk_item_location_inventory`)
- `item_location.item_id` -> `inventory.inventory_id` (`fk_item_location_inventory`)
- `item_location.location_id` -> `location.location_id` (`item_location_location_id_fkey`)
- `warehouse_sync_status.warehouse_id` -> `warehouse.warehouse_id` (`warehouse_sync_status_warehouse_id_fkey`)