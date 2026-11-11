import { useRef, useState, type FormEvent } from 'react';
import { FileArchive, Upload, Monitor } from 'lucide-react';
import { request, errorMessage } from './api';
import { Dialog, FormFooter, ParameterFields } from './components';
import { fileSize } from './format';
import { initialParameterValues, parseParameterValues } from './parameters';
import { snapshotUploadFile } from './upload';
import { isDeviceAuthorized } from './devices';
import type { Job, Package, Process, Session, Snapshot } from './types';

type FormActions = { onClose: () => void; onSaved: (message: string) => void };

export function UploadDialog({ onClose, onSaved }: FormActions) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const readingFile = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);
  async function selectFile(selected: File | null) {
    if (busy || readingFile.current) return;
    setFile(null); setError('');
    if (!selected) return;
    readingFile.current = true;
    setBusy(true);
    try { setFile(await snapshotUploadFile(selected)); }
    catch (cause) {
      if (fileInput.current) fileInput.current.value = '';
      setError(errorMessage(cause));
    }
    finally { readingFile.current = false; setBusy(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file || busy) return;
    setBusy(true); setError('');
    try {
      const result = await request<{ package: Package }>('/packages', { file });
      onSaved(`已导入 ${result.package.manifest.name} ${result.package.manifest.version}`);
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title="导入自动化包" description="上传 Studio 构建的版本，随后将它部署为可运行的流程。" onClose={onClose} busy={busy}>
    <form onSubmit={submit}><div className="dialog-body">
      <label className={`upload-zone ${file ? 'has-file' : ''}`}><span className="upload-symbol">{file ? <FileArchive size={28} /> : <Upload size={28} />}</span><strong>{file?.name ?? '选择自动化发布包'}</strong><span>{file ? fileSize(file.size) : '.wbot.zip 或 .zip · 最大 68 MiB'}</span><input ref={fileInput} aria-label="选择自动化发布包" type="file" accept=".zip" required disabled={busy} onChange={event => { const selected = event.target.files?.[0] ?? null; void selectFile(selected); }} /></label>
      <p className="inset-note">相同名称和版本的内容不可覆盖。更新自动化时，请先在 Studio 中增加版本号。</p>
      {error && <p className="form-error" role="alert">{error}</p>}
    </div><FormFooter busy={busy} label="导入发布包" onClose={onClose} /></form>
  </Dialog>;
}

export function DeviceDialog({ session, onClose, onSaved }: FormActions & { session: Session | null }) {
  const [name, setName] = useState('本机 Assistant');
  const [directory, setDirectory] = useState(session?.default_assistant_dir ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError('');
    try { await request('/devices', { body: { name: name.trim(), state_dir: directory.trim().replace(/^"(.*)"$/, '$1') } }); onSaved('执行设备已接入'); }
    catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title="接入本机执行设备" description="连接与 OC 位于同一台电脑上的 Assistant 后台服务。" onClose={onClose} busy={busy}>
    <form onSubmit={submit}><div className="dialog-body"><div className="information-box"><Monitor size={19} /><p>先启动本机 Assistant 后台服务，再填写它使用的数据目录。其他电脑上的 Assistant 应在客户端提交绑定申请，由管理端审批。</p></div>
      <label className="field"><span>设备名称</span><input value={name} onChange={event => setName(event.target.value)} maxLength={80} required autoFocus /></label>
      <label className="field"><span>Assistant 数据目录</span><input value={directory} onChange={event => setDirectory(event.target.value)} placeholder="Assistant 服务的数据目录完整路径" required /><small>使用启动 Assistant 时的 --state-dir 目录；默认目录已自动填写。</small></label>
      {error && <p className="form-error" role="alert">{error}</p>}
    </div><FormFooter busy={busy} label="连接设备" onClose={onClose} /></form>
  </Dialog>;
}

export function ProcessDialog({ snapshot, process, onClose, onSaved }: FormActions & { snapshot: Snapshot; process?: Process }) {
  const authorizedDevices = snapshot.devices.filter(isDeviceAuthorized);
  const [name, setName] = useState(process?.name ?? '');
  const [description, setDescription] = useState(process?.description ?? '');
  const [packageId, setPackageId] = useState(process?.package_id ?? snapshot.packages[0]?.id ?? '');
  const [deviceId, setDeviceId] = useState(process?.device_id ?? authorizedDevices[0]?.id ?? '');
  const [environmentId, setEnvironmentId] = useState(process?.environment_id ?? '');
  const [targetType, setTargetType] = useState(process?.environment_id ? 'environment' : 'robot');
  const [bindings, setBindings] = useState<Record<string, string>>(process?.asset_bindings ?? {});
  const deviceAuthorized = isDeviceAuthorized(snapshot.devices.find(item => item.id === deviceId));
  const targetValid = targetType === 'robot' ? deviceAuthorized : snapshot.environments?.some(item => item.id === environmentId);
  const selectedPackage = snapshot.packages.find(item => item.id === packageId);
  const [values, setValues] = useState(() => initialParameterValues(selectedPackage?.manifest.parameters ?? {}, process?.defaults));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  function changePackage(id: string) {
    setPackageId(id);
    setBindings({});
    setValues(initialParameterValues(snapshot.packages.find(item => item.id === id)?.manifest.parameters ?? {}));
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy || !selectedPackage) return;
    setError('');
    if (!targetValid) { setError('请选择已批准的 Robot 或已创建的 Environment。'); return; }
    try {
      const definitions = Object.fromEntries(Object.entries(selectedPackage.manifest.parameters).map(([key, value]) => [key, { ...value, required: false }]));
      const defaults = parseParameterValues(definitions, values);
      setBusy(true);
      await request(process ? `/processes/${encodeURIComponent(process.id)}` : '/processes', {
        method: process ? 'PATCH' : 'POST', body: { name: name.trim(), description: description.trim(), package_id: packageId, device_id: targetType === 'robot' ? deviceId : '', environment_id: targetType === 'environment' ? environmentId : '', asset_bindings: bindings, defaults, enabled: process?.enabled ?? true },
      });
      onSaved(process ? '流程部署已更新，已有作业保持原版本与参数' : '流程已部署，可以开始运行');
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title={process ? '编辑流程部署' : '部署自动化流程'} description="为自动化版本指定执行设备，创建业务人员可识别的流程。" onClose={onClose} busy={busy}>
    <form onSubmit={submit}><div className="dialog-body">
      <label className="field"><span>流程名称</span><input required autoFocus maxLength={120} placeholder="例如：每日订单整理" value={name} onChange={event => setName(event.target.value)} /></label>
      <label className="field"><span>流程说明 <small>选填</small></span><textarea rows={2} maxLength={1000} placeholder="说明用途与运行前提，方便团队使用" value={description} onChange={event => setDescription(event.target.value)} /></label>
      <label className="field"><span>自动化包版本</span><select required value={packageId} onChange={event => changePackage(event.target.value)}><option value="" disabled>选择已导入的版本</option>{snapshot.packages.map(item => <option key={item.id} value={item.id}>{item.manifest.name} · v{item.manifest.version}</option>)}</select></label>
      <label className="field"><span>执行目标类型</span><select value={targetType} onChange={event => setTargetType(event.target.value)}><option value="robot">指定 Robot</option><option value="environment">Environment 自动分配</option></select></label>
      {targetType === 'robot' ? <label className="field"><span>Robot</span><select required value={deviceAuthorized ? deviceId : ''} onChange={event => setDeviceId(event.target.value)}><option value="" disabled>选择已批准的 Robot</option>{authorizedDevices.map(item => <option key={item.id} value={item.id}>{item.name}{item.maintenance ? '（维护中）' : item.status === 'offline' ? '（离线）' : ''}</option>)}</select></label> : <label className="field"><span>Environment</span><select required value={environmentId} onChange={event => setEnvironmentId(event.target.value)}><option value="" disabled>选择执行环境</option>{(snapshot.environments ?? []).map(item => <option value={item.id} key={item.id}>{item.name} · {item.robot_ids.length} 个 Robot{item.enabled ? '' : '（已暂停）'}</option>)}</select><small>运行队列将选择环境中已批准、在线且空闲的 Robot。</small></label>}
      <div className="section-divider"><h3>默认运行参数</h3><p>运行时可以覆盖。切换包版本将重新读取其默认值。</p></div>
      <ParameterFields definitions={selectedPackage?.manifest.parameters ?? {}} values={values} onChange={setValues} optional />
      <div className="asset-bindings"><h3>Asset 参数绑定</h3><p className="inset-note">绑定值优先于默认参数，提交时读取 Asset 当前修订并保存快照。</p>{Object.entries(selectedPackage?.manifest.parameters ?? {}).map(([key, definition]) => <label className="field" key={key}><span>{key}</span><select value={bindings[key] ?? ''} onChange={event => { const next = { ...bindings }; if (event.target.value) next[key] = event.target.value; else delete next[key]; setBindings(next); }}><option value="">使用默认值或手动输入</option>{(snapshot.assets ?? []).filter(asset => asset.type === definition.type || definition.type === 'number' && asset.type === 'integer').map(asset => <option key={asset.id} value={asset.id}>{asset.name} · 修订 {asset.revision}</option>)}</select></label>)}</div>
      {error && <p className="form-error" role="alert">{error}</p>}
    </div><FormFooter busy={busy} disabled={!targetValid || !selectedPackage} label={process ? '保存部署' : '创建部署'} onClose={onClose} /></form>
  </Dialog>;
}

export function RunDialog({ process, snapshot, onClose, onStarted }: { process: Process; snapshot: Snapshot; onClose: () => void; onStarted: (job: Job) => void }) {
  const selectedPackage = snapshot.packages.find(item => item.id === process.package_id);
  const device = snapshot.devices.find(item => item.id === process.device_id);
  const environment = snapshot.environments?.find(item => item.id === process.environment_id);
  const canRun = process.enabled && (process.environment_id ? Boolean(environment) : isDeviceAuthorized(device));
  const definitions = Object.fromEntries(Object.entries(selectedPackage?.manifest.parameters ?? {}).filter(([name]) => !process.asset_bindings?.[name]));
  const [priority, setPriority] = useState(50);
  const [values, setValues] = useState(() => initialParameterValues(selectedPackage?.manifest.parameters ?? {}, process.defaults));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<{ signature: string; id: string } | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy || !selectedPackage) return;
    setError('');
    if (!canRun) { setError('流程必须已启用，且目标 Robot 已批准或 Environment 存在。'); return; }
    try {
      const parameters = parseParameterValues(definitions, values);
      const signature = JSON.stringify([parameters, priority]);
      if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
      setBusy(true);
      const result = await request<{ job: Job }>(`/processes/${encodeURIComponent(process.id)}/enqueue`, { body: { parameters, priority, request_id: pending.current.id } });
      onStarted(result.job);
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title="提交运行队列" description={process.name} onClose={onClose} busy={busy}>
    <form onSubmit={submit}><div className="dialog-body"><dl className="run-summary"><div><dt>固定版本</dt><dd>{process.package_id}</dd></div><div><dt>执行目标</dt><dd>{environment?.name ?? device?.name ?? '目标不存在'}</dd></div></dl>
      <label className="field"><span>优先级</span><select value={priority} onChange={event => setPriority(Number(event.target.value))}><option value={10}>低 · 10</option><option value={50}>普通 · 50</option><option value={90}>高 · 90</option></select></label>
      <ParameterFields definitions={definitions} values={values} onChange={setValues} />
      {Object.keys(process.asset_bindings ?? {}).length > 0 && <div className="asset-bindings"><h3>从 Asset 注入</h3>{Object.entries(process.asset_bindings ?? {}).map(([name, id]) => { const asset = snapshot.assets?.find(item => item.id === id); return <p key={name}>{name} ← {asset?.name ?? 'Asset 不存在'}<span className="cell-subtitle">{asset ? `修订 ${asset.revision} · ${String(asset.value)}` : '请修改流程绑定'}</span></p>; })}</div>}
      <p className="inset-note">没有空闲 Robot 时进入等待。关闭管理页面不会停止调度；OC 服务需保持运行。</p>
      {!canRun && <p className="information-box warning">请确认流程已启用，且执行目标有效。</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </div><FormFooter busy={busy} disabled={!canRun || !selectedPackage} label="提交队列" onClose={onClose} /></form>
  </Dialog>;
}
