/**
 * Horizon-based approval workflow definitions for DMIS needs list
 * Based on ODPEM organizational structure and Public Procurement Act 2015
 */

export type HorizonType = 'A' | 'B' | 'C';
export type ApprovalStepType = 'primary' | 'escalation' | 'conditional' | 'final';

export interface ApprovalStep {
  step: number;
  role: string;
  alternateRole: string | null;
  description: string;
  type: ApprovalStepType;
  external?: boolean;
}

export interface ApprovalWorkflowConfig {
  name: string;
  icon: string;
  inDmis: boolean;
  description: string;
  steps: ApprovalStep[];
  externalNote?: string;
}

export interface ApprovalWorkflowData {
  horizon: HorizonType;
  config: ApprovalWorkflowConfig;
  itemCount: number;
  totalUnits: number;
}

export const APPROVAL_WORKFLOWS: Record<HorizonType, ApprovalWorkflowConfig> = {
  A: {
    name: 'Transfer',
    icon: 'swap_horiz',
    inDmis: true,
    description: 'Inter-warehouse stock movements',
    steps: [
      {
        step: 1,
        role: 'Logistics Manager',
        alternateRole: null,
        description: 'Primary approver for inter-warehouse transfers',
        type: 'primary'
      },
      {
        step: 2,
        role: 'Senior Director PEOD',
        alternateRole: 'delegate',
        description: 'If Logistics Manager is unavailable',
        type: 'escalation'
      }
    ]
  },

  B: {
    name: 'Donation',
    icon: 'card_giftcard',
    inDmis: true,
    description: 'Allocation of donated goods',
    steps: [
      {
        step: 1,
        role: 'Senior Personnel (Donations)',
        alternateRole: 'delegate',
        description: 'Primary approver for donation allocations',
        type: 'primary'
      },
      {
        step: 2,
        role: 'Senior Director PEOD',
        alternateRole: null,
        description: 'If additional authorization required',
        type: 'conditional'
      }
    ]
  },

  C: {
    name: 'Procurement',
    icon: 'shopping_cart',
    inDmis: false,
    description: 'Purchase of new stock',
    steps: [
      {
        step: 1,
        role: 'Senior Director PEOD',
        alternateRole: 'delegate',
        description: 'Initial ODPEM approval',
        type: 'primary'
      },
      {
        step: 2,
        role: 'Director General',
        alternateRole: 'Deputy Director General',
        description: 'Final approval - External to DMIS',
        type: 'final',
        external: true
      }
    ],
    externalNote: 'Final procurement approval occurs outside DMIS through government procurement processes (Public Procurement Act 2015).'
  }
};
