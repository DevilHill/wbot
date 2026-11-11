import { PermissionButton } from './permissions';
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Download, RefreshCw, Upload } from 'lucide-react';
import { errorMessage, request } from './api';
import { Dialog, EmptyState, FormFooter, PageHeading } from './components';
import { dateTime, fileSize } from './format';
import { snapshotUploadFile } from './upload';
import type { PageProps } from './pages';
import type { Device } from './types';
import './assistant-releases.css';

type Release = {
  id: string; version: string; notes: string; size: number; sha256: string;
  published: boolean; device_ids: string[]; created_at: number;
};

export function AssistantReleases({ snapshot }: PageProps) {
  const [releases, setReleases] = useState<Release[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [uploading, setUploading] = useState(false);
  const [editing, setEditing] = useState<Release | null>(null);
  const [withdrawing, setWithdrawing] = useState('');
  const refresh = useCallback(async () => {
    setLoading(true);
    try { setReleases((await request<{ items: Release[] }>('/assistant-releases')).items); setError(''); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  async function withdraw(release: Release) {
    setWithdrawing(release.id);
    try {
      await request(`/assistant-releases/${release.id}`, { method: 'PATCH', body: { published: false, device_ids: release.device_ids } });
      await refresh();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setWithdrawing(''); }
  }

  return <>
    <PageHeading eyebrow="ASSISTANT UPDATES" title="客户端更新" description="集中发布 Assistant 版本，让设备在任务结束后由用户确认升级。"
      action={<PermissionButton permission="releases.manage" className="button primary" onClick={() => setUploading(true)}><Upload size={16} />上传新版本</PermissionButton>} />
    <div className="inset-note">上传后先保存为草稿。发布时可选择全部已批准设备或指定设备；撤回后停止提供该版本的下载和安装授权。</div>
    {error && <p className="form-error" role="alert">{error}</p>}
    <section className="panel release-panel"><div className="release-toolbar"><strong>版本目录 · {releases.length}</strong><button className="button secondary" disabled={loading} onClick={() => void refresh()}><RefreshCw size={15} />刷新</button></div>
      {!releases.length ? <EmptyState icon={Download} title={loading ? '正在读取版本…' : '还没有客户端版本'}>上传构建生成的 WBotAssistant-windows-x64.zip，版本号与更新说明会自动读取。</EmptyState> :
        <div className="table-scroll"><table><thead><tr><th>版本 / 更新说明</th><th>状态</th><th>发布范围</th><th>大小 / 上传时间</th><th>操作</th></tr></thead><tbody>{releases.map(release => <tr key={release.id}>
          <td><strong>Assistant {release.version}</strong><p className="release-notes">{release.notes}</p></td>
          <td><span className={`status status-${release.published ? 'succeeded' : 'stopped'}`}><i />{release.published ? '已发布' : '草稿 / 已撤回'}</span></td>
          <td>{release.device_ids.length ? `${release.device_ids.length} 台指定设备` : '全部已批准设备'}</td>
          <td>{fileSize(release.size)}<span className="cell-subtitle">{dateTime(release.created_at)}</span></td>
          <td><div className="release-actions"><PermissionButton permission="releases.manage" className="button secondary" disabled={!!withdrawing} onClick={() => setEditing(release)}>{release.published ? '发布设置' : '发布版本'}</PermissionButton>{release.published && <PermissionButton permission="releases.manage" className="quiet-button" disabled={!!withdrawing} onClick={() => void withdraw(release)}>撤回</PermissionButton>}</div></td>
        </tr>)}</tbody></table></div>}
    </section>
    {uploading && <ReleaseUpload onClose={() => setUploading(false)} onSaved={() => { setUploading(false); void refresh(); }} />}
    {editing && <ReleasePublication release={editing} devices={snapshot.devices} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void refresh(); }} />}
  </>;
}

function ReleaseUpload({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function select(selected?: File) {
    if (!selected || busy) return;
    setBusy(true); setFile(null); setError('');
    try { setFile(await snapshotUploadFile(selected, 128 * 1024 * 1024)); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true); setError('');
    try { await request('/assistant-releases', { file }); onSaved(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  return <Dialog title="上传 Assistant 新版本" description="上传后先保存草稿，再设置发布范围。相同版本号不可覆盖。" busy={busy} onClose={onClose}>
    <form onSubmit={submit}><div className="dialog-body"><label className="upload-zone"><Upload size={28} /><strong>{file?.name ?? '选择客户端 ZIP 包'}</strong><span>Windows x64 · 最大 128 MiB</span><input type="file" accept=".zip" disabled={busy} aria-label="选择客户端更新包" onChange={event => void select(event.target.files?.[0])} /></label>{error && <p className="form-error" role="alert">{error}</p>}</div><FormFooter busy={busy} disabled={!file} label="上传为草稿" onClose={onClose} /></form>
  </Dialog>;
}

function ReleasePublication({ release, devices, onClose, onSaved }: { release: Release; devices: Device[]; onClose: () => void; onSaved: () => void }) {
  const [scope, setScope] = useState(release.device_ids.length ? 'selected' : 'all');
  const [selected, setSelected] = useState(() => release.device_ids.filter(id => devices.some(device => device.id === id && device.transport === 'agent' && device.binding_state === 'approved')));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const eligible = devices.filter(device => device.transport === 'agent' && device.binding_state === 'approved');
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || (scope === 'selected' && !selected.length)) return;
    setBusy(true); setError('');
    try {
      await request(`/assistant-releases/${release.id}`, { method: 'PATCH', body: { published: true, device_ids: scope === 'all' ? [] : selected } });
      onSaved();
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  return <Dialog title={`发布 Assistant ${release.version}`} description="发布后，范围内的设备可以检查并下载更新；由用户在设备空闲时确认安装。" busy={busy} onClose={onClose}>
    <form onSubmit={submit}><div className="dialog-body"><label className="field"><span>发布范围</span><select value={scope} disabled={busy} onChange={event => setScope(event.target.value)}><option value="all">全部已批准设备（含后续批准的设备）</option><option value="selected">指定设备</option></select></label>
      {scope === 'selected' && <fieldset className="release-device-list"><legend>选择设备</legend>{eligible.map(device => <label key={device.id}><input type="checkbox" disabled={busy} checked={selected.includes(device.id)} onChange={event => setSelected(current => event.target.checked ? [...current, device.id] : current.filter(id => id !== device.id))} /><span>{device.name}</span></label>)}{!eligible.length && <p className="muted">暂无已批准的远程设备。</p>}</fieldset>}
      <p className="release-notes">{release.notes}</p>{error && <p className="form-error" role="alert">{error}</p>}
    </div><FormFooter busy={busy} disabled={scope === 'selected' && !selected.length} label="确认发布" onClose={onClose} /></form>
  </Dialog>;
}
