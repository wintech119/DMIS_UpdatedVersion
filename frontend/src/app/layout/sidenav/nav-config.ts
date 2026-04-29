export interface NavItem {
  label: string;
  icon: string;
  route?: string;
  href?: string;
  accessKey?: string;
  queryParams?: Record<string, string | number | boolean>;
  disabled?: boolean;
  sysadminOnly?: boolean;
  masterDomain?: 'catalogs' | 'operational' | 'policies' | 'tenant-access' | 'advanced';
}

export interface NavGroup {
  label: string;
  icon: string;
  route?: string;
  href?: string;
  accessKey?: string;
  queryParams?: Record<string, string | number | boolean>;
  disabled?: boolean;
  sysadminOnly?: boolean;
  children?: NavItem[];
  expanded?: boolean;
}

export interface NavSection {
  sectionLabel: string;
  groups: NavGroup[];
}

const REPLENISHMENT_ENABLED = typeof DMIS_REPLENISHMENT_ENABLED === 'undefined'
  ? true
  : DMIS_REPLENISHMENT_ENABLED;
const OPERATIONS_ENABLED = typeof DMIS_OPERATIONS_ENABLED === 'undefined'
  ? true
  : DMIS_OPERATIONS_ENABLED;

export const MAIN_SECTION: NavSection = {
  sectionLabel: 'MAIN',
  groups: [
    {
      label: 'Dashboard',
      icon: 'dashboard',
      route: '/replenishment/dashboard',
    },
  ],
};

export const REPLENISHMENT_SECTION: NavSection = {
  sectionLabel: 'REPLENISHMENT',
  groups: [
    {
      label: 'Supply Replenishment',
      icon: 'local_shipping',
      expanded: true,
      children: [
        { label: 'Stock Status Dashboard', icon: 'monitoring', route: '/replenishment/dashboard', accessKey: 'replenishment.dashboard' },
        { label: 'My Drafts & Submissions', icon: 'assignment', route: '/replenishment/my-submissions', accessKey: 'replenishment.submissions' },
        { label: 'Needs List Wizard', icon: 'playlist_add', route: '/replenishment/needs-list-wizard', accessKey: 'replenishment.wizard' },
        { label: 'Review Queue', icon: 'fact_check', route: '/replenishment/needs-list-review', accessKey: 'replenishment.review' },
      ],
    },
  ],
};

export const INVENTORY_SECTION: NavSection = {
  sectionLabel: 'INVENTORY',
  groups: [
    { label: 'View Inventory', icon: 'inventory_2', disabled: true },
    { label: 'Donations', icon: 'volunteer_activism', disabled: true },
    { label: 'Donation Intake', icon: 'move_to_inbox', disabled: true },
  ],
};

export const OPERATIONS_SECTION: NavSection = {
  sectionLabel: 'OPERATIONS',
  groups: [
    {
      label: 'Operations',
      icon: 'assignment',
      expanded: true,
      children: [
        { label: 'Dashboard', icon: 'dashboard', route: '/operations/dashboard', accessKey: 'operations.dashboard' },
        { label: 'Relief Requests', icon: 'request_page', route: '/operations/relief-requests', accessKey: 'operations.relief-requests' },
        { label: 'Eligibility Review', icon: 'verified_user', route: '/operations/eligibility-review', accessKey: 'operations.eligibility' },
        { label: 'Package Fulfillment', icon: 'inventory_2', route: '/operations/package-fulfillment', accessKey: 'operations.fulfillment' },
        { label: 'Consolidation', icon: 'warehouse', route: '/operations/consolidation', accessKey: 'operations.fulfillment' },
        { label: 'Dispatch', icon: 'local_shipping', route: '/operations/dispatch', accessKey: 'operations.dispatch' },
        { label: 'Task Center', icon: 'task_alt', route: '/operations/tasks', accessKey: 'operations.tasks' },
      ],
    },
  ],
};

export const MANAGEMENT_SECTION: NavSection = {
  sectionLabel: 'MANAGEMENT',
  groups: [
    {
      label: 'Master Data',
      icon: 'settings',
      expanded: false,
      children: [
        {
          label: 'Catalogs',
          icon: 'menu_book',
          route: '/master-data',
          queryParams: { domain: 'catalogs' },
          masterDomain: 'catalogs',
          accessKey: 'master.catalogs',
        },
        {
          label: 'Operational Masters',
          icon: 'domain',
          route: '/master-data',
          queryParams: { domain: 'operational' },
          masterDomain: 'operational',
          accessKey: 'master.operational',
        },
        {
          label: 'Advanced/System',
          icon: 'security',
          route: '/master-data',
          queryParams: { domain: 'advanced' },
          sysadminOnly: true,
          masterDomain: 'advanced',
          accessKey: 'master.advanced',
        },
      ],
    },
    {
      label: 'Reports',
      icon: 'assessment',
      disabled: true,
      children: [
        { label: 'Inventory Reports', icon: 'summarize', disabled: true },
        { label: 'Donation Reports', icon: 'receipt_long', disabled: true },
      ],
    },
    { label: 'Notifications', icon: 'notifications', disabled: true },
  ],
};

export const NAV_SECTIONS: NavSection[] = [
  ...(REPLENISHMENT_ENABLED ? [MAIN_SECTION, REPLENISHMENT_SECTION, INVENTORY_SECTION] : []),
  ...(OPERATIONS_ENABLED ? [OPERATIONS_SECTION] : []),
  MANAGEMENT_SECTION,
];
