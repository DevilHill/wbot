import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, ArrowUpRight, Box, CheckCircle2, ChevronRight, CircleHelp, FolderGit2, LayoutDashboard, Menu, Monitor, RefreshCw, ShieldCheck, X } from 'lucide-react';
import { errorMessage, getSession, readSnapshot, request } from './api';
import { DeviceDialog, ProcessDialog, RunDialog, UploadDialog } from './forms';
import { Jobs, Overview, Packages, Processes } from './pages';
import { Devices } from './device-page';
import { JobDetails, PackageDetails } from './details';
import type { Device, Job, Package, Process, Section, Session, Snapshot } from './types';

const navigation = [
  { id: 'overview', label: '运营概览', icon: LayoutDashboard },
  { id: 'processes', label: '流程部署', icon: FolderGit2 },
  { id: 'packages', label: '自动化包', icon: Box },
  { id: 'devices', label: '执行设备', icon: Monitor },
  { id: 'jobs', label: '作业记录', icon: Activity },
] as const;
type Modal = { type: 'upload' } | { type: 'device' } | { type: 'process'; process?: Process } | { type: 'run'; process: Process } | { type: 'package'; item: Package } | { type: 'job'; job: Job } | null;
const emptySnapshot: Snapshot = { packages: [], processes: [], devices: [], jobs: [] };

function currentSection(): Section {
  const value = location.hash.slice(1);
  return navigation.some(item => item.id === value) ? value as Section : 'overview';
}

export default function App() {
  const [section, setSection] = useState<Section>(currentSection);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot>(emptySnapshot);
  const [session, setSession] = useState<Session | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const [toast, setToast] = useState<{ message: string; error: boolean } | null>(null);
  const [modal, setModal] = useState<Modal>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const refreshInFlight = useRef<Promise<void> | null>(null);
  const mounted = useRef(false);

  const refresh = useCallback(() => {
    if (refreshInFlight.current) return refreshInFlight.current;
    setRefreshing(true);
    refreshInFlight.current = Promise.all([getSession(), readSnapshot()]).then(([identity, state]) => {
      if (mounted.current) { setSession(identity); setSnapshot(state); setLoaded(true); setConnectionError(''); }
    }).catch(cause => { if (mounted.current) setConnectionError(errorMessage(cause)); }).finally(() => {
      if (mounted.current) setRefreshing(false);
      refreshInFlight.current = null;
    });
    return refreshInFlight.current;
  }, []);
  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      await refresh();
      if (!cancelled) timer = setTimeout(poll, 3000);
    }
    void poll();
    return () => { cancelled = true; mounted.current = false; clearTimeout(timer); };
  }, [refresh]);
  useEffect(() => {
    const update = () => { setSection(currentSection()); setSidebarOpen(false); };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  useEffect(() => {
    if (!toast || toast.error) return;
    const timer = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(timer);
  }, [toast]);

  function navigate(next: Section) { location.hash = next; setSection(next); setSidebarOpen(false); }
  function saved(message: string) { setModal(null); setToast({ message, error: false }); void refresh(); }
  async function mutate(id: string, path: string, body: unknown, message: string) {
    if (pendingAction) return;
    setPendingAction(id);
    try { await request(path, { method: 'PATCH', body }); setToast({ message, error: false }); await refresh(); }
    catch (cause) { setToast({ message: errorMessage(cause), error: true }); }
    finally { setPendingAction(null); }
  }
  const actions = {
    navigate,
    upload: () => setModal({ type: 'upload' }),
    addDevice: () => setModal({ type: 'device' }),
    editProcess: (process?: Process) => setModal({ type: 'process', process }),
    run: (process: Process) => setModal({ type: 'run', process }),
    showJob: (job: Job) => setModal({ type: 'job', job }),
    showPackage: (item: Package) => setModal({ type: 'package', item }),
    toggleProcess: (process: Process) => void mutate(process.id, `/processes/${encodeURIComponent(process.id)}`, { enabled: !process.enabled }, process.enabled ? '流程已停用' : '流程已启用'),
    toggleMaintenance: (device: Device) => void mutate(device.id, `/devices/${encodeURIComponent(device.id)}`, { maintenance: !device.maintenance }, device.maintenance ? '设备已结束维护' : '设备已进入维护模式'),
    deviceBindingChanged: async (message: string) => {
      setToast({ message, error: false });
      if (refreshInFlight.current) await refreshInFlight.current;
      await refresh();
    },
    pendingAction,
  };
  const Page = { overview: Overview, processes: Processes, packages: Packages, devices: Devices, jobs: Jobs }[section];
  const activeSection = navigation.find(item => item.id === section)!;
  const closeModal = () => setModal(null);
  return <div className="app-shell">
    {sidebarOpen && <button className="sidebar-scrim" aria-label="收起导航" onClick={() => setSidebarOpen(false)} />}
    <aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}><a href="#overview" className="brand" onClick={() => navigate('overview')}><span className="brand-mark">W</span><span>WBot <b>OC</b><small>ORCHESTRATION CENTER</small></span></a>
      <div className="workspace"><span className="workspace-icon">企</span><div><strong>{session?.organization ?? '默认组织'}</strong><small>自动化运营中心</small></div><ShieldCheck size={15} /></div>
      <div className="nav-caption">工作空间</div><nav aria-label="主导航">{navigation.map(item => <a href={`#${item.id}`} key={item.id} className={section === item.id ? 'active' : ''} aria-current={section === item.id ? 'page' : undefined} onClick={() => setSidebarOpen(false)}><item.icon size={19} strokeWidth={1.65} /><span>{item.label}</span>{item.id === 'processes' && snapshot.processes.length > 0 && <small>{snapshot.processes.length}</small>}</a>)}</nav>
      <div className="sidebar-bottom"><div className="preview-card"><ShieldCheck size={18} /><strong>接入预览</strong><p>单组织 · Assistant 绑定审批</p><span>数据保存在当前 OC 服务</span></div><div className="operator"><span className="avatar">L</span><div><strong>本地操作员</strong><small>本机管理模式</small></div></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumb"><button className="icon-button mobile-menu" aria-label="展开导航" onClick={() => setSidebarOpen(true)}><Menu size={20} /></button><span>工作空间</span><ChevronRight size={14} /><strong>{activeSection.label}</strong></div><div className="topbar-actions"><span className={`connection-indicator ${connectionError ? 'is-offline' : ''}`}><i />{connectionError ? '连接异常' : loaded ? '服务已连接' : '正在连接'}</span><span className="header-divider" /><button className="icon-button" aria-label="刷新数据" disabled={refreshing} onClick={() => void refresh()}><RefreshCw size={17} className={refreshing ? 'spinning' : ''} /></button><span className="preview-label">PREVIEW 0.1</span></div></header>
      <main>{connectionError && <div className="connection-banner" role="alert"><CircleHelp size={18} /><span>{connectionError}{loaded && ' 页面保留最后一次成功读取的数据。'}</span><button className="quiet-button" onClick={() => void refresh()} disabled={refreshing}>重新连接</button></div>}
        {!loaded ? <div className="initial-loading"><span className="loading-orbit" /><h2>{connectionError ? '暂时无法读取运营数据' : '正在连接运营中心'}</h2><p>{connectionError ? '请检查 OC 服务，然后点击重新连接。' : '正在读取流程、设备与作业状态…'}</p></div> : <Page snapshot={snapshot} actions={actions} session={session} />}
        <footer className="page-footer"><span>WBot OC <i />自动化运营中心</span><span>本地预览 · 数据实时同步<ArrowUpRight size={12} /></span></footer>
      </main>
    </div>
    {toast && <div className={`toast ${toast.error ? 'toast-error' : ''}`} role={toast.error ? 'alert' : 'status'}><CheckCircle2 size={18} /><span>{toast.message}</span><button className="icon-button" onClick={() => setToast(null)} aria-label="关闭消息"><X size={16} /></button></div>}
    {modal?.type === 'upload' && <UploadDialog onClose={closeModal} onSaved={saved} />}
    {modal?.type === 'device' && <DeviceDialog session={session} onClose={closeModal} onSaved={saved} />}
    {modal?.type === 'process' && <ProcessDialog process={modal.process} snapshot={snapshot} onClose={closeModal} onSaved={saved} />}
    {modal?.type === 'run' && <RunDialog process={modal.process} snapshot={snapshot} onClose={closeModal} onStarted={job => { setModal({ type: 'job', job }); navigate('jobs'); void refresh(); }} />}
    {modal?.type === 'package' && <PackageDetails item={modal.item} onClose={closeModal} />}
    {modal?.type === 'job' && <JobDetails key={modal.job.id} job={snapshot.jobs.find(item => item.id === modal.job.id) ?? modal.job} onClose={closeModal} onChanged={() => void refresh()} />}
  </div>;
}
