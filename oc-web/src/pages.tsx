import { useMemo, useState } from 'react';
import { Activity, ArrowRight, ArrowUpRight, Box, Check, CircleCheck, Clock3, FileArchive, FolderGit2, Monitor, MoreHorizontal, Pencil, Play, Plus, SearchX, Server, ShieldCheck, Upload } from 'lucide-react';
import { EmptyState, PageHeading, SearchBox, StatusBadge } from './components';
import { isDeviceAuthorized, isDeviceReady } from './devices';
import { activeStates, dateTime, duration, fileSize, stateLabels } from './format';
import type { Device, Job, Package, Process, Section, Session, Snapshot } from './types';

type PageActions = {
  navigate: (section: Section) => void;
  upload: () => void;
  addDevice: () => void;
  editProcess: (process?: Process) => void;
  run: (process: Process) => void;
  showJob: (job: Job) => void;
  showPackage: (item: Package) => void;
  toggleProcess: (process: Process) => void;
  toggleMaintenance: (device: Device) => void;
  deviceBindingChanged: (message: string) => Promise<void>;
  pendingAction: string | null;
};
export type PageProps = { snapshot: Snapshot; actions: PageActions; session?: Session | null };

export function JobsTable({ jobs, onSelect, compact = false }: { jobs: Job[]; onSelect: (job: Job) => void; compact?: boolean }) {
  if (!jobs.length) return <EmptyState icon={Activity} title="还没有作业记录">部署并运行流程后，可在这里追踪执行状态与结果。</EmptyState>;
  return <div className="table-scroll"><table><thead><tr><th>流程 / 作业</th><th>状态</th><th>执行设备</th><th>开始时间</th>{!compact && <th>耗时</th>}<th><span className="sr-only">操作</span></th></tr></thead><tbody>
    {jobs.map(job => <tr key={job.id}><td><button className="table-title" onClick={() => onSelect(job)}>{job.process_name}</button><span className="cell-subtitle mono">{job.id.slice(0, 12)}</span></td><td><StatusBadge state={job.state} />{job.sync_error && <span className="cell-subtitle warning-text">状态同步异常</span>}</td><td><span className="device-label"><Monitor size={14} />{job.device_name}</span></td><td className="tabular muted">{dateTime(job.started_at ?? job.created_at)}</td>{!compact && <td className="tabular muted">{duration(job.started_at, job.finished_at)}</td>}<td><button className="icon-button" aria-label={`查看 ${job.process_name} 作业详情`} onClick={() => onSelect(job)}><ArrowUpRight size={17} /></button></td></tr>)}
  </tbody></table></div>;
}

export function Overview({ snapshot, actions }: PageProps) {
  const active = snapshot.jobs.filter(job => activeStates.has(job.state)).length;
  const completed = snapshot.jobs.filter(job => ['succeeded', 'failed', 'stopped', 'interrupted'].includes(job.state));
  const succeeded = completed.filter(job => job.state === 'succeeded').length;
  const authorizedDevices = snapshot.devices.filter(isDeviceAuthorized);
  const online = authorizedDevices.filter(device => device.status !== 'offline').length;
  const ready = snapshot.devices.filter(isDeviceReady).length;
  const steps = [
    { label: '导入自动化包', text: '将开发成果交付到运营中心', complete: snapshot.packages.length > 0, action: actions.upload, icon: Upload },
    { label: '连接执行设备', text: '批准远程绑定或接入本机服务', complete: authorizedDevices.length > 0, action: () => actions.navigate('devices'), icon: Monitor },
    { label: '部署并运行流程', text: '指定版本、设备与运行参数', complete: snapshot.processes.length > 0, action: () => actions.editProcess(), icon: Play },
  ];
  const days = useMemo(() => Array.from({ length: 7 }, (_, index) => {
    const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - (6 - index));
    const start = day.getTime() / 1000;
    const jobs = snapshot.jobs.filter(job => job.created_at >= start && job.created_at < start + 86400);
    return { label: `${day.getMonth() + 1}/${day.getDate()}`, count: jobs.length, success: jobs.filter(job => job.state === 'succeeded').length };
  }), [snapshot.jobs]);
  const highest = Math.max(1, ...days.map(day => day.count));
  return <>
    <div className="welcome-row"><div><span className="eyebrow">AUTOMATION OPERATIONS</span><h1>自动化运营概览</h1><p>从版本交付到执行结果，掌握每一次自动化。</p></div><button className="button primary" onClick={() => actions.editProcess()} disabled={!snapshot.packages.length || !snapshot.devices.some(isDeviceAuthorized)}><Plus size={16} />部署流程</button></div>
    <div className="metric-grid">
      <Metric label="已部署流程" value={snapshot.processes.length} note={`${snapshot.processes.filter(item => item.enabled).length} 个流程已启用`} icon={FolderGit2} />
      <Metric label="正在执行" value={active} note={active ? '任务在 Assistant 后台运行' : '目前没有正在执行的作业'} icon={Activity} />
      <Metric label="在线设备" value={online} note={`已授权 ${authorizedDevices.length} 台执行设备`} icon={Monitor} />
      <Metric label="作业成功率" value={completed.length ? `${Math.round(succeeded / completed.length * 100)}%` : '—'} note={`累计 ${completed.length} 次已结束作业`} icon={CircleCheck} />
    </div>
    <div className="overview-columns"><section className="panel activity-panel"><div className="panel-heading"><div><h2>运行趋势</h2><p>最近 7 天的作业提交情况</p></div><span className="small-label">近 7 天</span></div>
      <div className="chart-summary"><strong>{days.reduce((sum, day) => sum + day.count, 0)}</strong><span>次作业</span><div className="chart-legend"><i />全部提交 <i className="success-dot" />已完成</div></div>
      <div className="bar-chart" aria-label="最近七天作业数量">{days.map(day => <div className="chart-column" key={day.label}><span className="chart-count">{day.count || ''}</span><div className="chart-track"><div className="chart-total" style={{ height: `${day.count / highest * 100}%` }}><div className="chart-success" style={{ height: `${day.count ? day.success / day.count * 100 : 0}%` }} /></div></div><span>{day.label}</span></div>)}</div>
    </section><section className="panel connection-panel"><div className="panel-heading"><div><h2>执行环境</h2><p>连接状态来自 Assistant 实时响应</p></div><Server size={19} /></div>
      <div className="environment-visual"><div className="environment-ring"><Monitor size={31} strokeWidth={1.5} /><span className={ready ? 'connected-dot' : 'disconnected-dot'} /></div><strong>{ready ? '执行设备已就绪' : online ? '暂不可接收新作业' : '等待连接执行设备'}</strong><p>{ready ? `${ready} 台设备空闲，可承接已部署流程` : online ? '在线设备正在运行任务或处于维护模式' : '连接并批准 Assistant，开启第一次运行'}</p></div>
      <button className="text-button" onClick={() => actions.navigate('devices')}>管理执行设备<ArrowRight size={16} /></button>
    </section></div>
    <section className="panel"><div className="panel-heading"><div><h2>最近作业 <span className="count-label">{snapshot.jobs.length}</span></h2><p>跟进最近的执行情况</p></div><button className="text-button" onClick={() => actions.navigate('jobs')}>全部作业<ArrowRight size={15} /></button></div><JobsTable jobs={snapshot.jobs.slice(0, 5)} onSelect={actions.showJob} compact /></section>
    <section className="onboarding"><div className="onboarding-heading"><ShieldCheck size={18} /><h2>从这里开始</h2><span>三个步骤，完成自动化交付</span></div><div className="onboarding-steps">{steps.map((step, index) => <button key={step.label} className="onboarding-step" onClick={step.action} disabled={index === 2 && (!snapshot.packages.length || !snapshot.devices.some(isDeviceAuthorized))}><span className={`step-number ${step.complete ? 'complete' : ''}`}>{step.complete ? <Check size={15} /> : `0${index + 1}`}</span><span><strong>{step.label}</strong><small>{step.text}</small></span><ArrowUpRight size={16} /></button>)}</div></section>
  </>;
}

function Metric({ label, value, note, icon: Icon }: { label: string; value: string | number; note: string; icon: typeof Activity }) {
  return <section className="metric"><div><span>{label}</span><Icon size={18} strokeWidth={1.6} /></div><strong className="metric-value">{value}</strong><p>{note}</p></section>;
}

export function Processes({ snapshot, actions }: PageProps) {
  const [query, setQuery] = useState('');
  const processes = snapshot.processes.filter(item => `${item.name} ${item.description} ${item.package_id}`.toLowerCase().includes(query.toLowerCase()));
  return <><PageHeading eyebrow="PROCESS DEPLOYMENTS" title="流程部署" description="固定自动化版本与执行设备，让业务流程随时可运行。" action={<button className="button primary" onClick={() => actions.editProcess()} disabled={!snapshot.packages.length || !snapshot.devices.some(isDeviceAuthorized)}><Plus size={16} />部署流程</button>} />
    {(!snapshot.packages.length || !snapshot.devices.some(isDeviceAuthorized)) && <div className="notice"><FolderGit2 size={18} /><span>部署前需要自动化包和已批准的执行设备。</span>{!snapshot.packages.length && <button className="text-button" onClick={actions.upload}>导入包<ArrowRight size={14} /></button>}{!snapshot.devices.some(isDeviceAuthorized) && <button className="text-button" onClick={() => actions.navigate('devices')}>管理设备<ArrowRight size={14} /></button>}</div>}
    <section className="panel"><div className="table-toolbar"><div className="table-tabs"><span>全部流程</span><b>{snapshot.processes.length}</b></div><SearchBox value={query} onChange={setQuery} placeholder="搜索流程名称或包版本…" /></div>
      {!processes.length ? <EmptyState icon={query ? SearchX : FolderGit2} title={query ? '没有匹配的流程' : '部署你的第一个流程'}>{query ? '尝试其他名称或版本。' : '将发布包与设备关联，配置运行时的默认参数。'}</EmptyState> : <div className="table-scroll"><table><thead><tr><th>流程名称</th><th>自动化版本</th><th>执行设备</th><th>状态</th><th>操作</th></tr></thead><tbody>{processes.map(process => {
        const device = snapshot.devices.find(item => item.id === process.device_id);
        const canRun = process.enabled && isDeviceReady(device);
        return <tr key={process.id}><td><span className="named-cell"><span className="entity-icon"><FolderGit2 size={17} /></span><span><button className="table-title" onClick={() => actions.editProcess(process)}>{process.name}</button><span className="cell-subtitle description-cell">{process.description || '暂无流程说明'}</span></span></span></td><td><span className="version-label">{process.package_id}</span></td><td><span className="device-label"><Monitor size={14} />{device?.name ?? '未找到设备'}</span></td><td><StatusBadge state={process.enabled ? 'enabled' : 'disabled'} /></td><td><div className="row-actions"><button className="button run-button" onClick={() => actions.run(process)} disabled={!canRun || actions.pendingAction === process.id} title={canRun ? '开始运行' : '需要流程启用，且设备已批准、在线、空闲并未维护'}><Play size={13} />运行</button><button className="icon-button" aria-label={`编辑 ${process.name}`} onClick={() => actions.editProcess(process)}><Pencil size={15} /></button><button className="quiet-button" disabled={actions.pendingAction === process.id} onClick={() => actions.toggleProcess(process)}>{process.enabled ? '停用' : '启用'}</button></div></td></tr>;
      })}</tbody></table></div>}
    </section></>;
}

export function Packages({ snapshot, actions }: PageProps) {
  const [query, setQuery] = useState('');
  const packages = snapshot.packages.filter(item => item.id.toLowerCase().includes(query.toLowerCase()));
  return <><PageHeading eyebrow="PACKAGE REGISTRY" title="自动化包" description="集中保存 Studio 发布的成果，每个版本都有确定的内容。" action={<button className="button primary" onClick={actions.upload}><Upload size={16} />导入发布包</button>} />
    <section className="panel"><div className="table-toolbar"><div className="table-tabs"><span>全部版本</span><b>{snapshot.packages.length}</b></div><SearchBox value={query} onChange={setQuery} placeholder="搜索自动化包…" /></div>
      {!packages.length ? <EmptyState icon={FileArchive} title={query ? '没有匹配的版本' : '交付你的第一个自动化'} action={!query && <button className="button secondary" onClick={actions.upload}><Upload size={15} />导入发布包</button>}>{query ? '尝试其他名称或版本号。' : '上传 Studio 构建的 .wbot.zip 发布包，开始管理与部署。'}</EmptyState> : <div className="table-scroll"><table><thead><tr><th>包名称</th><th>版本</th><th>入口文件</th><th>大小</th><th>导入时间</th><th>详情</th></tr></thead><tbody>{packages.map(item => <tr key={item.id}><td><span className="named-cell"><span className="entity-icon amber"><Box size={18} /></span><button className="table-title" onClick={() => actions.showPackage(item)}>{item.manifest.name}</button></span></td><td><span className="version-label">v{item.manifest.version}</span></td><td className="muted mono">{item.manifest.entry}</td><td className="muted tabular">{fileSize(item.size_bytes)}</td><td className="muted tabular">{dateTime(item.created_at)}</td><td><button className="icon-button" aria-label={`查看 ${item.id} 清单`} onClick={() => actions.showPackage(item)}><MoreHorizontal size={18} /></button></td></tr>)}</tbody></table></div>}
    </section><p className="page-footnote"><ShieldCheck size={14} />导入时校验文件完整性；同名同版本的内容不可覆盖。</p></>;
}

export function Jobs({ snapshot, actions }: PageProps) {
  const [query, setQuery] = useState('');
  const [state, setState] = useState('all');
  const jobs = snapshot.jobs.filter(job => (state === 'all' || job.state === state) && `${job.id} ${job.process_name} ${job.device_name}`.toLowerCase().includes(query.toLowerCase()));
  return <><PageHeading eyebrow="JOB MONITORING" title="作业记录" description="追踪每次运行的状态、输入与输出，定位执行中的问题。" />
    <section className="panel"><div className="table-toolbar"><div className="table-tabs"><span>全部作业</span><b>{snapshot.jobs.length}</b></div><div className="toolbar-filters"><label className="sr-only" htmlFor="job-state">筛选作业状态</label><select className="filter-select" id="job-state" value={state} onChange={event => setState(event.target.value)}><option value="all">全部状态</option>{['running', 'preparing', 'succeeded', 'failed', 'stopped', 'interrupted', 'dispatching', 'unknown', 'stopping'].map(value => <option value={value} key={value}>{stateLabels[value]}</option>)}</select><SearchBox value={query} onChange={setQuery} placeholder="搜索流程、设备或作业 ID…" /></div></div>
      {snapshot.jobs.length && !jobs.length ? <EmptyState icon={SearchX} title="没有符合条件的作业">调整搜索内容或状态筛选。</EmptyState> : <JobsTable jobs={jobs} onSelect={actions.showJob} />}
    </section><p className="page-footnote"><Clock3 size={14} />时间以浏览器所在时区显示。状态未同步时，以最后一次确认结果为准。</p></>;
}
