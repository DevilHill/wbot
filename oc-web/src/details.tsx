import { useEffect, useState } from 'react';
import { AlertCircle, Check, Copy, FileJson, Square } from 'lucide-react';
import { Dialog, StatusBadge } from './components';
import { activeStates, dateTime, duration, fileSize } from './format';
import { errorMessage, request } from './api';
import type { Job, JobLog, Package } from './types';

export function PackageDetails({ item, onClose }: { item: Package; onClose: () => void }) {
  return <Dialog title={item.manifest.name} description={`发布版本 ${item.manifest.version}`} onClose={onClose} wide><div className="dialog-body">
    <dl className="detail-grid"><div><dt>入口文件</dt><dd>{item.manifest.entry}</dd></div><div><dt>包大小</dt><dd>{fileSize(item.size_bytes)}</dd></div><div><dt>导入时间</dt><dd>{dateTime(item.created_at)}</dd></div><div><dt>文件数量</dt><dd>{item.manifest.files.length}</dd></div></dl>
    <h3 className="detail-section-title"><FileJson size={16} />项目清单</h3><pre className="json-view">{JSON.stringify(item.manifest, null, 2)}</pre>
  </div></Dialog>;
}

export function JobDetails({ job, onClose, onChanged }: { job: Job; onClose: () => void; onChanged: () => void }) {
  const [tab, setTab] = useState<'log' | 'result' | 'parameters'>('log');
  const [log, setLog] = useState<JobLog | null>(null);
  const [logError, setLogError] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await request<JobLog>(`/jobs/${encodeURIComponent(job.id)}/log`);
        if (!cancelled) { setLog(response); setLogError(''); }
      } catch (cause) { if (!cancelled) setLogError(errorMessage(cause)); }
      finally { if (!cancelled) timer = setTimeout(poll, 3000); }
    }
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [job.id]);
  async function stop() {
    if (busy) return;
    setBusy(true); setActionError('');
    try { await request(`/jobs/${encodeURIComponent(job.id)}/stop`, { body: {} }); onChanged(); }
    catch (cause) { setActionError(errorMessage(cause)); } finally { setBusy(false); }
  }
  async function copyId() {
    try { await navigator.clipboard.writeText(job.id); setCopied(true); }
    catch { setActionError('无法复制到剪贴板，可以选择下方作业 ID 手动复制。'); }
  }
  return <Dialog title={job.process_name} description="作业详情" onClose={onClose} wide>
    <div className="dialog-body"><div className="job-detail-state"><StatusBadge state={job.state} />{activeStates.has(job.state) && job.state !== 'stopping' && <button className="button danger" disabled={busy} onClick={stop}><Square size={13} />{busy ? '正在停止…' : '停止任务'}</button>}</div>
      <div className="job-identity"><code>{job.id}</code><button className="icon-button" onClick={copyId} aria-label="复制作业 ID">{copied ? <Check size={15} /> : <Copy size={15} />}</button></div>
      <dl className="detail-grid"><div><dt>执行设备</dt><dd>{job.device_name}</dd></div><div><dt>固定版本</dt><dd>{job.package_id}</dd></div><div><dt>创建时间</dt><dd>{dateTime(job.created_at)}</dd></div><div><dt>运行耗时</dt><dd>{duration(job.started_at, job.finished_at)}</dd></div><div><dt>完成时间</dt><dd>{dateTime(job.finished_at)}</dd></div><div><dt>最近同步</dt><dd>{dateTime(job.last_synced_at)}</dd></div><div><dt>执行端作业 ID</dt><dd className="mono">{job.assistant_job_id ?? '尚未确认'}</dd></div></dl>
      {(job.error || actionError) && <p className="form-error" role="alert">{actionError || job.error}</p>}
      {(job.sync_error || log?.sync_error || logError) && <div className="information-box warning"><AlertCircle size={17} /><p>{logError || job.sync_error || log?.sync_error} {log?.cached && '当前展示已保存的日志。'}</p></div>}
      <div className="detail-tabs" role="tablist" aria-label="作业内容">{(['log', 'result', 'parameters'] as const).map(value => <button role="tab" aria-selected={tab === value} key={value} className={tab === value ? 'selected' : ''} onClick={() => setTab(value)}>{value === 'log' ? '执行日志' : value === 'result' ? '运行结果' : '输入参数'}</button>)}</div>
      {tab === 'log' && <div role="tabpanel"><div className="console-heading"><span><i />OUTPUT</span><small>{log?.cached ? '已保存日志' : 'Assistant 日志'}</small></div><pre className="log-view" tabIndex={0}>{log?.log || (log ? '暂无日志输出。' : '正在读取日志…')}</pre></div>}
      {tab === 'result' && <pre className="json-view" role="tabpanel">{job.result === null ? '这个作业尚无返回结果。' : JSON.stringify(job.result, null, 2)}</pre>}
      {tab === 'parameters' && <pre className="json-view" role="tabpanel">{JSON.stringify(job.parameters, null, 2)}</pre>}
    </div>
  </Dialog>;
}
