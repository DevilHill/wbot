import { PermissionButton } from './permissions';
import { useRef, useState } from 'react';
import { Check, Monitor, Plus, ShieldCheck, X } from 'lucide-react';
import { changeDeviceBinding, errorMessage } from './api';
import { Dialog, EmptyState, PageHeading, SearchBox, StatusBadge } from './components';
import { isDeviceAuthorized } from './devices';
import { dateTime } from './format';
import type { PageProps } from './pages';
import type { AgentGateway, Device, DeviceBindingAction } from './types';

const bindingLabels = { pending: '待审批', approved: '已批准', rejected: '已拒绝', revoked: '已撤销' };
const actionMessages = { approve: '设备绑定已批准，等待 Assistant 心跳', reject: '绑定申请已拒绝', revoke: '设备绑定已撤销' };

function GatewayNotice({ gateway }: { gateway?: AgentGateway | null }) {
  if (!gateway) return <div className="notice"><Monitor size={18} /><span>远程接入服务尚未启用。启用后，在 Assistant 的 OC 连接设置中提交绑定申请；本机目录接入仍可使用。</span></div>;
  return <div className="notice gateway-notice"><Monitor size={18} /><div><strong>Assistant 连接接入地址</strong><code>{gateway.url}</code><p>{gateway.public_host_required ? `请把监听地址中的 ${gateway.host} 换成这台 OC 电脑可访问的 IP 或域名，保留端口 ${gateway.port}。` : '在 Assistant 的 OC 连接设置中填写这个地址并提交绑定申请。'} 此地址用于设备接入，管理端账号与设备凭据分别管理。</p></div></div>;
}

export function Devices({ snapshot, actions, session }: PageProps) {
  const [query, setQuery] = useState('');
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [revokeDevice, setRevokeDevice] = useState<Device | null>(null);
  const submitting = useRef(false);
  const requests = snapshot.devices.filter(device => device.transport === 'agent' && device.binding_state === 'pending');
  const devices = snapshot.devices.filter(device => !requests.includes(device) && `${device.name} ${device.id}`.toLowerCase().includes(query.toLowerCase()));
  const busy = pendingAction !== null || actions.pendingAction !== null;

  async function changeBinding(device: Device, action: DeviceBindingAction) {
    if (submitting.current || actions.pendingAction) return;
    submitting.current = true;
    setPendingAction(device.id); setError('');
    try {
      await changeDeviceBinding(device.id, action);
      setRevokeDevice(null);
      await actions.deviceBindingChanged(actionMessages[action]);
    } catch (cause) { setError(`${device.name}：${errorMessage(cause)}`); }
    finally { submitting.current = false; setPendingAction(null); }
  }

  return <>
    <PageHeading eyebrow="ROBOT CONNECTIONS" title="Robot 连接" description="一个 Assistant 连接对应一个 Robot。审批连接后，可加入 Environment 承接流程任务。" action={<PermissionButton permission="robots.manage" className="button primary" onClick={actions.addDevice}><Plus size={16} />接入本机设备</PermissionButton>} />
    <GatewayNotice gateway={session?.agent_gateway} />
    {error && !revokeDevice && <p className="form-error device-action-error" role="alert">{error}</p>}
    <section className="panel binding-panel"><div className="panel-heading"><div><h2>待审批申请 <span className="count-label">{requests.length}</span></h2><p>批准前，请与设备使用者核对 Assistant 中显示的设备 ID 和核验码。</p></div><ShieldCheck size={20} /></div>
      {!requests.length ? <p className="binding-empty">暂无待审批申请。Assistant 提交申请后会自动显示在这里。</p> : <div className="table-scroll"><table><thead><tr><th>设备 / 设备 ID</th><th>核验码</th><th>申请时间</th><th>审批</th></tr></thead><tbody>{requests.map(device => <tr key={device.id}>
        <td><strong>{device.name}</strong><span className="cell-subtitle mono">{device.id}</span></td><td><code className="verification-code">{device.verification_code ?? '—'}</code></td><td className="tabular muted">{dateTime(device.created_at)}</td>
        <td><div className="row-actions"><PermissionButton permission="robots.manage" className="button primary" disabled={busy || !device.verification_code} aria-label={`批准 ${device.name} 绑定`} onClick={() => void changeBinding(device, 'approve')}><Check size={14} />{pendingAction === device.id ? '处理中…' : '批准'}</PermissionButton><PermissionButton permission="robots.manage" className="button secondary" disabled={busy} aria-label={`拒绝 ${device.name} 绑定`} onClick={() => void changeBinding(device, 'reject')}><X size={14} />拒绝</PermissionButton></div></td>
      </tr>)}</tbody></table></div>}
    </section>
    <section className="panel"><div className="table-toolbar"><div className="table-tabs"><span>设备与绑定记录</span><b>{snapshot.devices.length - requests.length}</b></div><SearchBox value={query} onChange={setQuery} placeholder="搜索设备名称或 ID…" /></div>
      {!devices.length ? <EmptyState icon={Monitor} title={query ? '没有匹配的设备' : '还没有已处理的设备'} action={!query && <PermissionButton permission="robots.manage" className="button secondary" onClick={actions.addDevice}><Plus size={15} />接入本机 Assistant</PermissionButton>}>{query ? '尝试其他设备名称或 ID。' : '批准远程 Assistant 的申请，或连接同一台电脑的 Assistant 服务。'}</EmptyState> : <div className="device-grid">{devices.map(device => {
        const authorized = isDeviceAuthorized(device);
        const remote = device.transport === 'agent';
        const binding = device.binding_state ?? (remote ? 'pending' : 'approved');
        return <article className="device-card" key={device.id}><div className="device-card-top"><span className="entity-icon large"><Monitor size={23} /></span><StatusBadge state={device.status} /></div><h3>{device.name}</h3><p className="small-label">{remote ? '远程 Assistant · agent' : '本机目录接入 · local'}</p>
          <dl><div><dt>所属环境</dt><dd>{(snapshot.environments ?? []).filter(item => item.robot_ids.includes(device.id)).map(item => item.name).join("、") || "未加入"}</dd></div><div><dt>连接授权</dt><dd><span className={`binding-state binding-${binding}`}>{bindingLabels[binding]}</span></dd></div><div><dt>维护模式</dt><dd>{device.maintenance ? '已开启' : '未开启'}</dd></div><div><dt>正在执行</dt><dd>{device.active_jobs} 个作业</dd></div><div><dt>{remote ? '最近心跳' : '最近连接'}</dt><dd>{dateTime(device.last_seen)}</dd></div></dl>
          <p className="device-path"><span>设备 ID</span><code>{device.id}</code>{!remote && <><span>本机数据目录</span><code>{device.state_dir}</code></>}</p>
          {!authorized && <p className="device-error">当前绑定不可接收新任务。请在 Assistant 重新申请，再核对并审批新的记录。</p>}{device.error && <p className="device-error">{device.error}</p>}
          <div className="device-card-actions">{authorized && <PermissionButton permission="robots.manage" className="button secondary full-width" disabled={busy} onClick={() => actions.toggleMaintenance(device)}>{device.maintenance ? '结束维护' : '设为维护'}</PermissionButton>}{remote && binding === 'approved' && <PermissionButton permission="robots.manage" className="button danger full-width" disabled={busy} onClick={() => { setError(''); setRevokeDevice(device); }}>撤销绑定</PermissionButton>}</div>
        </article>;
      })}</div>}
    </section>
    <p className="page-footnote"><ShieldCheck size={14} />维护、拒绝或撤销会阻止新任务，已运行任务继续执行并上报。绑定审批不代表设备当前在线。</p>
    {revokeDevice && <Dialog title="撤销设备绑定" description={revokeDevice.name} onClose={() => { setRevokeDevice(null); setError(''); }} busy={pendingAction !== null}>
      <form onSubmit={event => { event.preventDefault(); void changeBinding(revokeDevice, 'revoke'); }}><div className="dialog-body"><p>撤销后，这台 Assistant 无法再通过当前绑定领取新任务或下载包。尚未领取的派发会标记失败，已领取但未开始的任务也可能无法启动。已经运行的任务会继续，并可上报状态、日志和结果。</p><dl className="run-summary"><div><dt>设备</dt><dd>{revokeDevice.name}</dd></div><div><dt>设备 ID</dt><dd>{revokeDevice.id}</dd></div></dl><p className="inset-note">需要重新连接时，须由 Assistant 创建新的绑定申请，再由管理端批准。</p>{error && <p className="form-error" role="alert">{error}</p>}</div><footer className="dialog-footer"><button type="button" className="button secondary" disabled={pendingAction !== null} onClick={() => { setRevokeDevice(null); setError(''); }}>取消</button><button type="submit" className="button danger" disabled={busy}>{pendingAction ? '正在撤销…' : '确认撤销绑定'}</button></footer></form>
    </Dialog>}
  </>;
}
