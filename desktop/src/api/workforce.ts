import api from './client';

export interface WorkforceMember {
  user_id: number;
  team_id: number;
  display_name: string;
  avatar_url: string;
  role: 'owner' | 'admin' | 'sales' | string;
  online: boolean;
  reported_state: 'online' | 'busy' | 'away' | 'offline' | string;
  availability: 'idle' | 'busy' | 'away' | 'offline' | string;
  active_count: number;
  last_heartbeat_at: string;
  last_assigned_at: string;
}

export interface CustomerAssignment {
  customer_id: number;
  team_id: number;
  assignee_user_id: number;
  assignee_name: string;
  assignee_role: string;
  status: 'assigned' | 'released' | string;
  source: string;
  assigned_by_user_id: number;
  version: number;
  assigned_at: string;
  last_activity_at: string;
  updated_at: string;
}

export interface WorkforceOverview {
  presence: WorkforceMember[];
  assignments: CustomerAssignment[];
  online_count: number;
  idle_count: number;
  assigned_count: number;
}

export const sendWorkforceHeartbeat = (state: 'online' | 'busy' | 'away' = 'online') =>
  api.post('/api/kellai/workforce/presence/heartbeat', { state }, {
    skipErrorToast: true,
    skipLoading: true,
  });

export const getWorkforceOverview = () =>
  api.get('/api/kellai/workforce/overview', {
    skipErrorToast: true,
    skipLoading: true,
  });

export const claimCustomer = (customerId: number) =>
  api.post(`/api/kellai/workforce/customers/${customerId}/claim`);

export const assignCustomer = (customerId: number, assigneeUserId: number) =>
  api.post(`/api/kellai/workforce/customers/${customerId}/assign`, {
    assignee_user_id: assigneeUserId,
  });

export const autoAssignCustomer = (customerId: number) =>
  api.post(`/api/kellai/workforce/customers/${customerId}/auto-assign`);

export const releaseCustomer = (customerId: number) =>
  api.post(`/api/kellai/workforce/customers/${customerId}/release`);
