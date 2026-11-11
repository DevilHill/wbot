export const stateLabels: Record<string, string> = {
  queued: '等待调度',
  preparing: '准备中', running: '运行中', stopping: '停止中', succeeded: '已完成', failed: '失败',
  stopped: '已停止', interrupted: '中断待核实', dispatching: '派发中', unknown: '待核实',
  online: '在线', offline: '离线', busy: '忙碌', maintenance: '维护中', enabled: '已启用', disabled: '已停用',
};
export const activeStates = new Set(['queued', 'preparing', 'running', 'stopping', 'dispatching']);
export function dateTime(timestamp: number | null | undefined) {
  return timestamp ? new Date(timestamp * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—';
}
export function duration(start: number | null, finish: number | null) {
  if (!start) return '—';
  const seconds = Math.max(0, Math.round((finish ?? Date.now() / 1000) - start));
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}
export function fileSize(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
