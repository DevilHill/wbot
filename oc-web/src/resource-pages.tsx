import { PermissionButton } from './permissions';
import { useState, type FormEvent } from 'react';
import { Boxes, Database, Pencil, Plus, Trash2 } from 'lucide-react';
import { Dialog, EmptyState, FormFooter, PageHeading, SearchBox, StatusBadge } from './components';
import { errorMessage, request } from './api';
import { isDeviceAuthorized, isDeviceReady } from './devices';
import { dateTime } from './format';
import type { PageProps } from './pages';
import type { Asset, Environment, Snapshot } from './types';
import './resources.css';

type EditorProps<T> = { item?: T; snapshot: Snapshot; onClose: () => void; onSaved: () => Promise<void> };

function EnvironmentEditor({ item, snapshot, onClose, onSaved }: EditorProps<Environment>) {
  const [name, setName] = useState(item?.name ?? '');
  const [description, setDescription] = useState(item?.description ?? '');
  const [members, setMembers] = useState(item?.robot_ids ?? []);
  const [enabled, setEnabled] = useState(item?.enabled ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const robots = snapshot.devices.filter(robot => isDeviceAuthorized(robot) || members.includes(robot.id));
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError('');
    try {
      await request(item ? `/environments/${item.id}` : '/environments', {
        method: item ? 'PATCH' : 'POST', body: { name, description, robot_ids: members, enabled },
      });
      await onSaved(); onClose();
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title={item ? '编辑 Environment' : '创建 Environment'} description="将可执行相同流程的 Robot 组织到一个环境，空闲成员自动承接队列任务。" onClose={onClose} busy={busy}>
    <form onSubmit={submit}><div className="dialog-body"><fieldset disabled={busy} className="resource-fields">
      <label className="field"><span>环境名称</span><input autoFocus required maxLength={120} value={name} onChange={event => setName(event.target.value)} placeholder="例如：财务生产环境" /></label>
      <label className="field"><span>说明</span><textarea maxLength={2000} value={description} onChange={event => setDescription(event.target.value)} rows={2} /></label>
      <label className="field"><span>调度状态</span><select value={enabled ? 'enabled' : 'paused'} onChange={event => setEnabled(event.target.value === 'enabled')}><option value="enabled">启用调度</option><option value="paused">暂停调度</option></select><small>暂停只影响等待任务；已派发的任务继续执行。</small></label>
      <div className="section-divider"><h3>Robot 成员 · {members.length}</h3><p>一个连接对应一个 Robot。同一个 Robot 可加入多个环境，但同时只承接一个 OC 作业。</p></div>
      <div className="robot-picker">{robots.length ? robots.map(robot => <label className="robot-choice" key={robot.id}><input type="checkbox" checked={members.includes(robot.id)} onChange={event => setMembers(event.target.checked ? [...members, robot.id] : members.filter(id => id !== robot.id))} /><span><strong>{robot.name}</strong><small>{isDeviceAuthorized(robot) ? robot.maintenance ? '维护中' : '已批准连接' : '绑定已失效，请移出环境'}</small></span><StatusBadge state={robot.status} /></label>) : <p className="inset-note">暂无已批准的 Robot；可以先保存空环境，再接入成员。</p>}</div>
    </fieldset>{error && <p role="alert" className="form-error">{error}</p>}</div><FormFooter busy={busy} label="保存环境" onClose={onClose} /></form>
  </Dialog>;
}

const assetTypes = { string: '文本', number: '数字', integer: '整数', boolean: '布尔' };

function AssetEditor({ item, snapshot, onClose, onSaved }: EditorProps<Asset>) {
  const [name, setName] = useState(item?.name ?? '');
  const [description, setDescription] = useState(item?.description ?? '');
  const [type, setType] = useState<Asset['type']>(item?.type ?? 'string');
  const [value, setValue] = useState(String(item?.value ?? ''));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const referenced = snapshot.processes.some(process => Object.values(process.asset_bindings ?? {}).includes(item?.id ?? ''));
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    setError('');
    const parsed = type === 'string' ? value : type === 'boolean' ? value === 'true' : Number(value);
    if (typeof parsed === 'number' && (!value.trim() || !Number.isFinite(parsed))) { setError('请输入有效数字'); return; }
    setBusy(true);
    try {
      await request(item ? `/assets/${item.id}` : '/assets', {
        method: item ? 'PATCH' : 'POST', body: { name, description, type, value: parsed },
      });
      await onSaved(); onClose();
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title={item ? '编辑 Asset' : '创建 Asset'} description="集中管理普通配置，绑定流程参数后自动注入每次运行。" onClose={onClose} busy={busy}>
    <form onSubmit={submit}><div className="dialog-body"><fieldset disabled={busy} className="resource-fields">
      <label className="field"><span>Asset 名称</span><input autoFocus required maxLength={120} value={name} onChange={event => setName(event.target.value)} placeholder="例如：报表保存目录" /></label>
      <label className="field"><span>类型</span><select disabled={referenced} value={type} onChange={event => { setType(event.target.value as Asset['type']); setValue(event.target.value === 'boolean' ? 'false' : ''); }}>{Object.entries(assetTypes).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>{referenced && <small>已被流程引用，解除绑定后可修改类型。</small>}</label>
      <label className="field"><span>配置值</span>{type === 'boolean' ? <select value={value} onChange={event => setValue(event.target.value)}><option value="false">否（false）</option><option value="true">是（true）</option></select> : type === 'string' ? <textarea rows={3} maxLength={16384} value={value} onChange={event => setValue(event.target.value)} /> : <input type="number" required step={type === 'integer' ? 1 : 'any'} value={value} onChange={event => setValue(event.target.value)} />}</label>
      <label className="field"><span>说明</span><textarea rows={2} maxLength={2000} value={description} onChange={event => setDescription(event.target.value)} /></label>
      <p className="information-box">普通配置会以明文保存，并出现在作业参数中。请勿填写密码、令牌等凭据。</p>
    </fieldset>{error && <p role="alert" className="form-error">{error}</p>}</div><FormFooter busy={busy} label="保存 Asset" onClose={onClose} /></form>
  </Dialog>;
}

export function Environments(props: PageProps) { return <ResourcePage kind="environments" {...props} />; }
export function Assets(props: PageProps) { return <ResourcePage kind="assets" {...props} />; }

function ResourcePage({ kind, snapshot, actions }: PageProps & { kind: 'environments' | 'assets' }) {
  const [query, setQuery] = useState('');
  const [editing, setEditing] = useState<{ id?: string } | null>(null);
  const [deleting, setDeleting] = useState<Environment | Asset | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const environments = kind === 'environments';
  const records = snapshot[kind] ?? [];
  const filtered = records.filter(item => `${item.name} ${item.description}`.toLowerCase().includes(query.toLowerCase()));
  const title = environments ? 'Environment 环境' : 'Asset 配置';
  const Icon = environments ? Boxes : Database;
  const saved = () => actions.deviceBindingChanged(environments ? 'Environment 已保存' : 'Asset 已保存，新值将在下次提交任务时使用');
  async function remove() {
    if (!deleting || busy) return;
    setBusy(true); setError('');
    try { await request(`/${kind}/${deleting.id}/delete`, { body: {} }); await actions.deviceBindingChanged('资源已删除'); setDeleting(null); }
    catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <><PageHeading eyebrow={environments ? 'EXECUTION ENVIRONMENTS' : 'SHARED CONFIGURATION'} title={title}
    description={environments ? '按业务或用途组合 Robot，为流程提供可调度的执行资源。' : '统一维护流程配置。提交时保存值与修订快照，排队中的作业保持原参数。'}
    action={<PermissionButton permission={kind + ".manage"} className="button primary" onClick={() => setEditing({})}><Plus size={16} />{environments ? '创建环境' : '创建 Asset'}</PermissionButton>} />
    <section className="panel"><div className="table-toolbar"><div className="table-tabs"><span>全部{environments ? '环境' : '配置'}</span><b>{records.length}</b></div><SearchBox value={query} onChange={setQuery} placeholder="搜索名称或说明…" /></div>
      {!filtered.length ? <EmptyState icon={Icon} title={query ? '没有匹配的资源' : environments ? '创建你的第一个执行环境' : '将常用配置集中管理'}>{query ? '尝试其他名称或说明。' : environments ? '选择已批准的 Robot 组成环境，然后在流程部署中选择该环境。' : '创建 Asset 后，可在流程部署中绑定同类型的运行参数。'}</EmptyState> : <div className="table-scroll"><table><thead><tr><th>名称 / 说明</th><th>{environments ? 'Robot 成员' : '类型 / 修订'}</th><th>{environments ? '调度状态' : '配置值'}</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{filtered.map(item => <tr key={item.id}><td><span className="named-cell"><span className="entity-icon"><Icon size={18} /></span><span><PermissionButton permission={kind + ".manage"} className="table-title" onClick={() => setEditing({ id: item.id })}>{item.name}</PermissionButton><span className="cell-subtitle description-cell">{item.description || '暂无说明'}</span></span></span></td>
        {'robot_ids' in item ? <><td><strong>{item.robot_ids.length} 个 Robot</strong><span className="cell-subtitle">{item.robot_ids.filter(id => isDeviceReady(snapshot.devices.find(robot => robot.id === id))).length} 个当前就绪</span><span className="cell-subtitle description-cell">{item.robot_ids.map(id => snapshot.devices.find(robot => robot.id === id)?.name ?? id).join('、') || '尚未分配成员'}</span></td><td><StatusBadge state={item.enabled ? 'enabled' : 'disabled'} /></td></> : <><td>{assetTypes[item.type]}<span className="cell-subtitle">修订 {item.revision}</span></td><td><code className="asset-value">{String(item.value) || '（空文本）'}</code></td></>}
        <td className="tabular muted">{dateTime(item.updated_at)}</td><td><div className="row-actions"><PermissionButton permission={kind + ".manage"} className="icon-button" aria-label={`编辑 ${item.name}`} onClick={() => setEditing({ id: item.id })}><Pencil size={16} /></PermissionButton><PermissionButton permission={kind + ".manage"} className="icon-button" aria-label={`删除 ${item.name}`} onClick={() => { setDeleting(item); setError(''); }}><Trash2 size={16} /></PermissionButton></div></td></tr>)}</tbody></table></div>}
    </section>
    {editing && (environments ? <EnvironmentEditor item={snapshot.environments?.find(item => item.id === editing.id)} snapshot={snapshot} onClose={() => setEditing(null)} onSaved={saved} /> : <AssetEditor item={snapshot.assets?.find(item => item.id === editing.id)} snapshot={snapshot} onClose={() => setEditing(null)} onSaved={saved} />)}
    {deleting && <Dialog title="删除资源" description={deleting.name} onClose={() => setDeleting(null)} busy={busy}><div className="dialog-body"><p>删除后无法恢复。仍被流程引用{environments ? '或仍有等待任务' : ''}的资源会阻止删除；历史作业的参数和记录不会受影响。</p>{error && <p role="alert" className="form-error">{error}</p>}</div><footer className="dialog-footer"><button className="button secondary" disabled={busy} onClick={() => setDeleting(null)}>取消</button><button className="button danger" disabled={busy} onClick={() => void remove()}>{busy ? '正在删除…' : '确认删除'}</button></footer></Dialog>}
  </>;
}
