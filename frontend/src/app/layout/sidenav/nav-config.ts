export interface NavItem {
  label: string;
  icon: string;
  route?: string;
  href?: string;
  queryParams?: Record<string, string | number | boolean>;
  disabled?: boolean;
  sysadminOnly?: boolean;
}

export interface NavGroup {
  label: string;
  icon: string;
  route?: string;
  href?: string;
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

export const NAV_SECTIONS: NavSection[] = [
  {
    sectionLabel: 'MAIN',
    groups: [
      {
        label: 'Dashboard',
        icon: 'dashboard',
        route: '/replenishment/dashboard',
      },
    ],
  },
  {
    sectionLabel: 'REPLENISHMENT',
    groups: [
      {
        label: 'Supply Replenishment',
        icon: 'local_shipping',
        expanded: true,
        children: [
          { label: 'Stock Status Dashboard', icon: 'monitoring', route: '/replenishment/dashboard' },
          { label: 'My Drafts & Submissions', icon: 'assignment', route: '/replenishment/my-submissions' },
          { label: 'Needs List Wizard', icon: 'playlist_add', route: '/replenishment/needs-list-wizard' },
          { label: 'Review Queue', icon: 'fact_check', route: '/replenishment/needs-list-review' },
        ],
      },
    ],
  },
  {
    sectionLabel: 'INVENTORY',
    groups: [
      { label: 'View Inventory', icon: 'inventory_2', disabled: true },
      { label: 'Donations', icon: 'volunteer_activism', disabled: true },
      { label: 'Donation Intake', icon: 'move_to_inbox', disabled: true },
    ],
  },
  {
    sectionLabel: 'OPERATIONS',
    groups: [
      {
        label: 'Operations',
        icon: 'assignment',
        expanded: true,
        children: [
          { label: 'Dashboard', icon: 'dashboard', route: '/operations/dashboard' },
          { label: 'Relief Requests', icon: 'request_page', route: '/operations/relief-requests' },
          { label: 'Eligibility Review', icon: 'verified_user', route: '/operations/eligibility-review' },
          { label: 'Package Fulfillment', icon: 'package_2', route: '/operations/package-fulfillment' },
          { label: 'Dispatch', icon: 'local_shipping', route: '/operations/dispatch' },
          { label: 'Task Center', icon: 'task_alt', route: '/operations/tasks' },
        ],
      },
    ],
  },
  {
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
          },
          {
            label: 'Operational Masters',
            icon: 'domain',
            route: '/master-data',
            queryParams: { domain: 'operational' },
          },
          {
            label: 'Policies',
            icon: 'policy',
            route: '/master-data',
            queryParams: { domain: 'policies' },
          },
          {
            label: 'Tenant & Access',
            icon: 'admin_panel_settings',
            route: '/master-data',
            queryParams: { domain: 'tenant-access' },
          },
          {
            label: 'Advanced/System',
            icon: 'security',
            route: '/master-data',
            queryParams: { domain: 'advanced' },
            sysadminOnly: true,
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
      { label: 'User Management', icon: 'manage_accounts', disabled: true },
      { label: 'Notifications', icon: 'notifications', disabled: true },
    ],
  },
];
