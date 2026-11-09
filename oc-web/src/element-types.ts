export type ElementRecord = {
  id: string;
  name: string;
  group: string;
  xpath: string;
  description: string;
  url: string;
  frame: Record<string, unknown> | null;
};

export type ElementField = Exclude<keyof ElementRecord, 'id'>;

export type ElementRepository = { id: string; name: string; description: string; head: string; created_at: number };
export type ElementCommit = {
  id: string; repository_id: string; parents: string[]; message: string;
  author: { id: string; name: string; kind: 'admin' | 'device' }; created_at: number; items: ElementRecord[]; restored_from?: string;
};
export type ElementBranch = {
  id: string; name: string; repository_id: string; device_id: string; device_name: string;
  base_commit: string; head: string; status: 'open' | 'merged'; created_at: number; updated_at: number;
};
export type ElementMergeRequest = {
  id: string; repository_id: string; branch_id: string; branch_name: string; device_id: string; device_name: string;
  title: string; description: string; state: 'open' | 'merged' | 'closed'; source_head: string; base_commit: string;
  created_at: number; updated_at: number; merge_commit?: string; close_reason?: string;
};
export type ElementRepositoryDetail = {
  repository: ElementRepository; head: ElementCommit; branches: ElementBranch[];
  requests: ElementMergeRequest[]; commits: Omit<ElementCommit, 'items'>[];
};
export type ElementConflict = { id: string; field: ElementField | '__record__'; base: unknown; main: unknown; source: unknown };
export type ElementReview = {
  request: ElementMergeRequest; main_head: string; source_head: string; base_commit: string;
  changes: { id: string; type: 'added' | 'modified' | 'deleted'; before: ElementRecord | null; after: ElementRecord | null }[];
  merged_items: ElementRecord[]; conflicts: ElementConflict[];
};
export type ElementResolution = { id: string; field: ElementConflict['field']; value: unknown };

export const elementFields: ElementField[] = ['group', 'name', 'xpath', 'url', 'description', 'frame'];
export const elementFieldLabels: Record<ElementField, string> = {
  group: '页面 / 分组', name: '元素名称', xpath: 'XPath', url: '页面 URL', description: '描述', frame: '框架定位',
};

export function elementValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}
