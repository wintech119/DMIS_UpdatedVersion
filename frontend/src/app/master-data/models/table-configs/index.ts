import { MasterTableConfig } from '../master-data.models';

import { ITEM_CATEGORY_CONFIG } from './item-category.config';
import { IFRC_FAMILY_CONFIG } from './ifrc-family.config';
import { IFRC_ITEM_REFERENCE_CONFIG } from './ifrc-item-reference.config';
import { UOM_CONFIG } from './uom.config';
import { ITEM_CONFIG } from './item.config';
import { INVENTORY_CONFIG } from './inventory.config';
import { LOCATION_CONFIG } from './location.config';
import { WAREHOUSE_CONFIG } from './warehouse.config';
import { AGENCY_CONFIG } from './agency.config';
import { CUSTODIAN_CONFIG } from './custodian.config';
import { DONOR_CONFIG } from './donor.config';
import { EVENT_CONFIG } from './event.config';
import { SUPPLIER_CONFIG } from './supplier.config';
import { COUNTRY_CONFIG } from './country.config';
import { CURRENCY_CONFIG } from './currency.config';
import { PARISH_CONFIG } from './parish.config';
import { USERS_CONFIG } from './users.config';
import { ROLES_CONFIG } from './roles.config';
import { PERMISSIONS_CONFIG } from './permissions.config';
import { TENANT_TYPES_CONFIG } from './tenant-types.config';
import { TENANTS_CONFIG } from './tenants.config';

export {
  ITEM_CATEGORY_CONFIG,
  IFRC_FAMILY_CONFIG,
  IFRC_ITEM_REFERENCE_CONFIG,
  UOM_CONFIG,
  ITEM_CONFIG,
  INVENTORY_CONFIG,
  LOCATION_CONFIG,
  WAREHOUSE_CONFIG,
  AGENCY_CONFIG,
  CUSTODIAN_CONFIG,
  DONOR_CONFIG,
  EVENT_CONFIG,
  SUPPLIER_CONFIG,
  COUNTRY_CONFIG,
  CURRENCY_CONFIG,
  PARISH_CONFIG,
  USERS_CONFIG,
  ROLES_CONFIG,
  PERMISSIONS_CONFIG,
  TENANT_TYPES_CONFIG,
  TENANTS_CONFIG,
};

/** All table configs indexed by routePath for route resolution */
export const ALL_TABLE_CONFIGS: Record<string, MasterTableConfig> = {
  'item-categories': ITEM_CATEGORY_CONFIG,
  'ifrc-families': IFRC_FAMILY_CONFIG,
  'ifrc-item-references': IFRC_ITEM_REFERENCE_CONFIG,
  'uom': UOM_CONFIG,
  'items': ITEM_CONFIG,
  'inventory': INVENTORY_CONFIG,
  'locations': LOCATION_CONFIG,
  'warehouses': WAREHOUSE_CONFIG,
  'agencies': AGENCY_CONFIG,
  'custodians': CUSTODIAN_CONFIG,
  'donors': DONOR_CONFIG,
  'events': EVENT_CONFIG,
  'suppliers': SUPPLIER_CONFIG,
  'countries': COUNTRY_CONFIG,
  'currencies': CURRENCY_CONFIG,
  'parishes': PARISH_CONFIG,
  'users': USERS_CONFIG,
  'roles': ROLES_CONFIG,
  'permissions': PERMISSIONS_CONFIG,
  'tenant-types': TENANT_TYPES_CONFIG,
  'tenants': TENANTS_CONFIG,
};
