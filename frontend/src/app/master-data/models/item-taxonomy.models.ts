import { LookupItem } from './master-data.models';

export interface ItemCategoryLookup extends LookupItem {
  category_code?: string;
  status_code?: string;
}

export interface IfrcFamilyLookup extends LookupItem {
  family_code?: string;
  group_code?: string;
  group_label?: string;
  category_id?: string | number;
  category_code?: string;
  category_desc?: string;
}

export interface IfrcReferenceLookup extends LookupItem {
  ifrc_code?: string;
  ifrc_family_id?: string | number;
  family_code?: string;
  family_label?: string;
  category_code?: string;
  category_label?: string;
  spec_segment?: string;
  size_weight?: string;
  form?: string;
  material?: string;
}

export interface MasterListOptions {
  status?: string;
  search?: string;
  orderBy?: string;
  limit?: number;
  offset?: number;
  categoryId?: string | number | null;
  ifrcFamilyId?: string | number | null;
  ifrcItemRefId?: string | number | null;
}

export interface ItemCategoryLookupOptions {
  activeOnly?: boolean;
  includeValue?: string | number | null;
}

export interface IfrcFamilyLookupOptions {
  categoryId?: string | number | null;
  search?: string;
  activeOnly?: boolean;
  includeValue?: string | number | null;
}

export interface IfrcReferenceLookupOptions {
  ifrcFamilyId?: string | number | null;
  familyId?: string | number | null;
  search?: string;
  activeOnly?: boolean;
  includeValue?: string | number | null;
  limit?: number;
}
