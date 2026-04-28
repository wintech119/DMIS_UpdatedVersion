const http = require('http');
const itemRecord = {
  item_id: 101,
  item_code: 'WAT-PUR-TAB-25',
  legacy_item_code: 'LOC-WASH-001',
  item_name: 'WATER PURIFICATION TABLETS',
  sku_code: 'SKU-2401-WAT',
  category_id: 1,
  category_desc: 'Water, Sanitation and Hygiene',
  ifrc_family_id: 1,
  ifrc_family_label: 'Water Purification',
  ifrc_item_ref_id: 1,
  ifrc_reference_desc: 'Water purification tablets',
  item_desc: 'Water purification tablets, 25 pack',
  default_uom_code: 'PACK',
  reorder_qty: 100,
  issuance_order: 'FEFO',
  can_expire_flag: true,
  baseline_burn_rate: 5,
  min_stock_threshold: 50,
  criticality_level: 'CRITICAL',
  is_batched_flag: true,
  units_size_vary_flag: false,
  usage_desc: 'Issued through shelters',
  storage_desc: 'Cool dry storage',
  comments_text: 'Verification fixture',
  status_code: 'A',
  version_nbr: 1,
};
const tenantRecord = {
  tenant_id: 1,
  tenant_code: 'KINGSTON_NEOC',
  tenant_name: 'Kingston NEOC',
  tenant_type: 'NEOC',
  parent_tenant_id: null,
  data_scope: 'NATIONAL_DATA',
  pii_access: 'LIMITED',
  offline_required: true,
  mobile_priority: true,
  address1_text: '12 Camp Road, Kingston',
  parish_code: '01',
  contact_name: 'Kemar Brown',
  phone_no: '+1 876 555 0123',
  email_text: 'kemar.brown@odpem.gov.jm',
  status_code: 'A',
  version_nbr: 1,
};
const userRecord = {
  user_id: 11,
  username: 'kemar.brown',
  email: 'kemar.brown@odpem.gov.jm',
  full_name: 'Kemar Brown',
  access_level: 'ADMIN',
  is_primary_tenant: true,
  last_login_at: '2026-04-28T12:00:00Z',
};
const roleRecord = {
  role_id: 1,
  code: 'SYSTEM_ADMINISTRATOR',
  name: 'System Administrator',
  assigned_at: '2026-04-28T12:00:00Z',
};
function send(res, status, body) {
  const json = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json',
    'content-length': Buffer.byteLength(json),
    'access-control-allow-origin': '*',
    'access-control-allow-headers': '*',
    'access-control-allow-methods': 'GET,POST,PATCH,OPTIONS',
  });
  res.end(json);
}
function lookupItems(path) {
  if (path.includes('/tenant/lookup')) return [{ value: 1, label: 'ODPEM National EOC' }];
  if (path.includes('/parishes/lookup')) return [{ value: '01', label: 'Kingston' }, { value: '02', label: 'St. Andrew' }];
  if (path.includes('/item_categories/lookup') || path.includes('/items/categories/lookup')) return [{ value: 1, label: 'Water, Sanitation and Hygiene' }];
  if (path.includes('/ifrc_families/lookup') || path.includes('/items/ifrc-families/lookup')) return [{ value: 1, label: 'Water Purification', category_id: 1 }];
  if (path.includes('/ifrc_item_references/lookup') || path.includes('/items/ifrc-references/lookup')) return [{ value: 1, label: 'Water purification tablets', ifrc_code: 'WAT-PUR-TAB-25' }];
  if (path.includes('/uom/lookup')) return [{ value: 'PACK', label: 'Pack' }, { value: 'EA', label: 'Each' }];
  return [{ value: 1, label: 'Fixture Option' }];
}
const server = http.createServer((req, res) => {
  if (req.method === 'OPTIONS') return send(res, 200, {});
  const url = new URL(req.url, 'http://127.0.0.1:8001');
  const path = url.pathname;
  if (path === '/api/v1/auth/whoami/') {
    return send(res, 200, {
      user_id: 'brief-c-admin', username: 'brief-c-admin', roles: ['SYSTEM_ADMINISTRATOR'],
      permissions: ['masterdata.view', 'masterdata.create', 'masterdata.edit', 'masterdata.inactivate'],
      tenant_context: { tenant_id: 1, tenant_name: 'ODPEM', tenant_type: 'NEOC' },
      operations_capabilities: {},
    });
  }
  if (path === '/api/v1/auth/local-harness/') return send(res, 200, { enabled: false, users: [] });
  if (!path.startsWith('/api/v1/masterdata/')) return send(res, 404, { detail: 'not found' });
  if (path.endsWith('/summary')) return send(res, 200, { counts: { total: 1, active: 1, inactive: 0 }, warnings: [] });
  if (path.includes('/lookup')) return send(res, 200, { items: lookupItems(path), warnings: [] });
  if (path.includes('/tenant/1/users/11/roles')) return send(res, 200, { results: [roleRecord], warnings: [] });
  if (path.includes('/tenant/1/users')) return send(res, 200, { results: [userRecord], warnings: [] });
  if (/\/user\/?$/.test(path)) return send(res, 200, { results: [userRecord], count: 1, limit: 1000, offset: 0, warnings: [] });
  if (/\/role\/?$/.test(path)) return send(res, 200, { results: [roleRecord], count: 1, limit: 500, offset: 0, warnings: [] });
  if (path.includes('/tenant/1')) return send(res, 200, { record: tenantRecord, warnings: [] });
  if (/\/items\/?$/.test(path)) return send(res, 200, { results: [itemRecord], count: 1, limit: 25, offset: 0, warnings: [] });
  if (path.includes('/items/101')) return send(res, 200, { record: itemRecord, warnings: [] });
  return send(res, 200, { results: [], count: 0, limit: 25, offset: 0, warnings: [] });
});
server.listen(8001, '127.0.0.1', () => console.log('brief-c mock backend listening on 8001'));
process.on('SIGTERM', () => server.close(() => process.exit(0)));
process.on('SIGINT', () => server.close(() => process.exit(0)));
