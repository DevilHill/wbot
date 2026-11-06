import type { Device, DeviceBindingAction, Session, Snapshot } from './types';

let session: Session | null = null;
let sessionRequest: Promise<Session> | null = null;

export function getSession(): Promise<Session> {
  if (session) return Promise.resolve(session);
  if (!sessionRequest) {
    sessionRequest = fetch('/api/oc/session', { cache: 'no-store', signal: AbortSignal.timeout(12000) })
      .then(async response => {
        if (!response.ok) throw new Error('无法连接 OC 服务');
        session = await response.json() as Session;
        return session;
      }).finally(() => { sessionRequest = null; });
  }
  return sessionRequest;
}

export async function request<T>(path: string, options: { method?: string; body?: unknown; file?: File } = {}): Promise<T> {
  const credentials = await getSession();
  const headers: Record<string, string> = { 'X-WBot-Token': credentials.token };
  let body: BodyInit | undefined;
  if (options.file) {
    headers['Content-Type'] = 'application/octet-stream';
    body = options.file;
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }
  const response = await fetch('/api/oc' + path, {
    method: options.method ?? (body === undefined ? 'GET' : 'POST'), headers, body,
    cache: 'no-store', signal: AbortSignal.timeout(options.file ? 90000 : 30000),
  });
  const content = await response.json();
  if (!response.ok) {
    if (response.status === 403) session = null;
    throw new Error(content.error || `请求失败（${response.status}）`);
  }
  return content as T;
}

export const readSnapshot = () => request<Snapshot>('/state');

export function changeDeviceBinding(id: string, action: DeviceBindingAction) {
  return request<{ device: Device }>(`/devices/${encodeURIComponent(id)}/${action}`, { method: 'POST', body: {} });
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    if (error.name === 'TimeoutError') return '服务响应超时。运行请求可能已被接受，请查看作业记录，或保持当前参数重试核对。';
    if (error.message === 'Failed to fetch') return '无法连接管理服务，请检查服务是否正在运行。';
    return error.message;
  }
  return '操作未完成，请重试。';
}
