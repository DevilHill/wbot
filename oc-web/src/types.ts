export type ParameterValue = string | number | boolean;
export type Parameters = Record<string, ParameterValue>;
export type ParameterDefinition = {
  type: 'string' | 'number' | 'integer' | 'boolean';
  required?: boolean;
  default?: ParameterValue;
  description?: string;
};
export type Manifest = {
  name: string;
  version: string;
  entry: string;
  parameters: Record<string, ParameterDefinition>;
  files: string[];
  requirements: Record<string, string>;
};
export type Package = { id: string; manifest: Manifest; created_at: number; size_bytes: number };
export type Device = {
  id: string; name: string; state_dir: string; status: 'online' | 'offline' | 'busy';
  maintenance: boolean; active_jobs: number; last_seen: number | null; error: string;
  transport?: 'local' | 'agent';
  binding_state?: 'pending' | 'approved' | 'rejected' | 'revoked';
  verification_code?: string; created_at?: number;
};
export type DeviceBindingAction = 'approve' | 'reject' | 'revoke';
export type AgentGateway = { host: string; port: number; scheme: string; url: string; public_host_required: boolean };
export type Process = {
  id: string; name: string; description: string; package_id: string; device_id: string;
  defaults: Parameters; enabled: boolean; created_at: number; updated_at: number;
};
export type Job = {
  id: string; process_id: string; process_name: string; package_id: string;
  device_id: string; device_name: string; parameters: Parameters; state: string;
  created_at: number; started_at: number | null; finished_at: number | null;
  assistant_job_id: string | null; result: unknown; error: string;
  sync_error: string; last_synced_at: number | null;
};
export type Snapshot = {
  packages: Package[]; devices: Device[]; processes: Process[]; jobs: Job[];
  meta?: { mode: string; organization: string };
};
export type Session = { token: string; mode: string; organization: string; default_assistant_dir: string; agent_gateway?: AgentGateway | null };
export type JobLog = { log: string; cached: boolean; sync_error: string };
export type Section = 'overview' | 'processes' | 'packages' | 'devices' | 'jobs';
