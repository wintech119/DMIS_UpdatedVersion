export interface NavItem {
  label: string;
  icon: string;
  route?: string;
  disabled?: boolean;
}

export interface NavGroup {
  label: string;
  icon: string;
  route?: string;
  disabled?: boolean;
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
          { label: 'Procurement Orders', icon: 'shopping_cart', route: '/replenishment/procurement/new' },
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
      { label: 'Relief Requests', icon: 'request_page', disabled: true },
      { label: 'Eligibility Review', icon: 'verified_user', disabled: true },
      { label: 'Package Fulfillment', icon: 'package_2', disabled: true },
      { label: 'Dispatch', icon: 'local_shipping', disabled: true },
    ],
  },
  {
    sectionLabel: 'MANAGEMENT',
    groups: [
      {
        label: 'Master Data',
        icon: 'settings',
        disabled: true,
        children: [
          { label: 'Warehouses', icon: 'warehouse', disabled: true },
          { label: 'Items', icon: 'category', disabled: true },
          { label: 'Events', icon: 'event', disabled: true },
          { label: 'Agencies', icon: 'corporate_fare', disabled: true },
          { label: 'Donors', icon: 'handshake', disabled: true },
          { label: 'Custodians', icon: 'badge', disabled: true },
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
