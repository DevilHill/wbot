import { useRef, useState, type FormEvent } from 'react';
import { FileArchive, Upload, Monitor } from 'lucide-react';
import { request, errorMessage } from './api';
import { Dialog, FormFooter, ParameterFields } from './components';
import { fileSize } from './format';
import { initialParameterValues, parseParameterValues } from './parameters';
import { snapshotUploadFile } from './upload';
import { isDeviceAuthorized, isDeviceReady } from './devices';
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
  const deviceAuthorized = isDeviceAuthorized(snapshot.devices.find(item => item.id === deviceId));
  const selectedPackage = snapshot.packages.find(item => item.id === packageId);
  const [values, setValues] = useState(() => initialParameterValues(selectedPackage?.manifest.parameters ?? {}, process?.defaults));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  function changePackage(id: string) {
    setPackageId(id);
    setValues(initialParameterValues(snapshot.packages.find(item => item.id === id)?.manifest.parameters ?? {}));
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy || !selectedPackage) return;
    setError('');
    if (!deviceAuthorized) { setError('请选择已批准的执行设备；原设备可能已被拒绝或撤销。'); return; }
    try {
      const definitions = Object.fromEntries(Object.entries(selectedPackage.manifest.parameters).map(([key, value]) => [key, { ...value, required: false }]));
      const defaults = parseParameterValues(definitions, values);
      setBusy(true);
      await request(process ? `/processes/${encodeURIComponent(process.id)}` : '/processes', {
        method: process ? 'PATCH' : 'POST', body: { name: name.trim(), description: description.trim(), package_id: packageId, device_id: deviceId, defaults, enabled: process?.enabled ?? true },
      });
      onSaved(process ? '流程部署已更新，已有作业保持原版本与参数' : '流程已部署，可以开始运行');
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title={process ? '编辑流程部署' : '部署自动化流程'} description="为自动化版本指定执行设备，创建业务人员可识别的流程。" onClose={onClose} busy={busy}>
    <form onSubmit={submit}><div className="dialog-body">
      <label className="field"><span>流程名称</span><input required autoFocus maxLength={120} placeholder="例如：每日订单整理" value={name} onChange={event => setName(event.target.value)} /></label>
      <label className="field"><span>流程说明 <small>选填</small></span><textarea rows={2} maxLength={1000} placeholder="说明用途与运行前提，方便团队使用" value={description} onChange={event => setDescription(event.target.value)} /></label>
      <label className="field"><span>自动化包版本</span><select required value={packageId} onChange={event => changePackage(event.target.value)}><option value="" disabled>选择已导入的版本</option>{snapshot.packages.map(item => <option key={item.id} value={item.id}>{item.manifest.name} · v{item.manifest.version}</option>)}</select></label>
      <label className="field"><span>执行设备</span><select required value={deviceAuthorized ? deviceId : ''} onChange={event => setDeviceId(event.target.value)}><option value="" disabled>选择已批准的执行设备</option>{authorizedDevices.map(item => <option key={item.id} value={item.id}>{item.name} · {item.transport === 'agent' ? '远程' : '本机'}{item.maintenance ? '（维护中）' : item.status === 'offline' ? '（离线）' : ''}</option>)}</select><small>仅显示已批准的设备。待审批、已拒绝和已撤销的远程绑定不可部署。</small></label>
      {!deviceAuthorized && <p className="information-box warning">当前没有选中已批准的设备。请先完成绑定审批，或选择其他设备。</p>}
      <div className="section-divider"><h3>默认运行参数</h3><p>运行时可以覆盖。切换包版本将重新读取其默认值。</p></div>
      <ParameterFields definitions={selectedPackage?.manifest.parameters ?? {}} values={values} onChange={setValues} optional />
      {error && <p className="form-error" role="alert">{error}</p>}
    </div><FormFooter busy={busy} disabled={!deviceAuthorized || !selectedPackage} label={process ? '保存部署' : '创建部署'} onClose={onClose} /></form>
  </Dialog>;
}

export function RunDialog({ process, snapshot, onClose, onStarted }: { process: Process; snapshot: Snapshot; onClose: () => void; onStarted: (job: Job) => void }) {
  const selectedPackage = snapshot.packages.find(item => item.id === process.package_id);
  const device = snapshot.devices.find(item => item.id === process.device_id);
  const canRun = process.enabled && isDeviceReady(device);
  const [values, setValues] = useState(() => initialParameterValues(selectedPackage?.manifest.parameters ?? {}, process.defaults));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<{ signature: string; id: string } | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy || !selectedPackage) return;
    setError('');
    if (!canRun) { setError('执行设备必须已批准、在线、空闲且未处于维护模式。'); return; }
    try {
      const parameters = parseParameterValues(selectedPackage.manifest.parameters, values);
      const signature = JSON.stringify(parameters);
      if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
      setBusy(true);
      const result = await request<{ job: Job }>(`/processes/${encodeURIComponent(process.id)}/run`, { body: { parameters, request_id: pending.current.id } });
      onStarted(result.job);
    } catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title="运行流程" description={process.name} onClose={onClose} busy={busy}>
    <form onSubmit={submit}><div className="dialog-body"><dl className="run-summary"><div><dt>固定版本</dt><dd>{process.package_id}</dd></div><div><dt>执行设备</dt><dd>{device?.name ?? process.device_id}</dd></div></dl>
      <ParameterFields definitions={selectedPackage?.manifest.parameters ?? {}} values={values} onChange={setValues} />
      <p className="inset-note">作业交给 Assistant 后台执行。关闭管理端页面不会中断任务。</p>
      {!canRun && <p className="information-box warning">当前流程或设备不可运行。请确认流程已启用，设备绑定已批准、在线且未处于维护模式。</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </div><FormFooter busy={busy} disabled={!canRun || !selectedPackage} label="开始运行" onClose={onClose} /></form>
  </Dialog>;
}
