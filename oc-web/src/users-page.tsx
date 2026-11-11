import { useEffect, useState, type FormEvent } from 'react';
import { KeyRound, Pencil, Plus, ShieldCheck, Users } from 'lucide-react';
import { clearSession, errorMessage, request } from './api';
import { Dialog, FormFooter, PageHeading, SearchBox } from './components';
import { dateTime } from './format';
import type { Role, User } from './types';

export const roleNames: Record<string, string> = { admin: '管理员', developer: '开发者', operator: '操作员', viewer: '只读用户' };

export function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Record<string, string>>({});
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState<{ user?: User; reset?: boolean } | null>(null);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void Promise.all([request<{ items: User[] }>('/users'), request<{ items: Role[]; permissions: Record<string, string> }>('/roles')])
      .then(([accounts, catalog]) => { if (!cancelled) { setUsers(accounts.items); setRoles(catalog.items); setPermissions(catalog.permissions); setError(''); } })
      .catch(cause => { if (!cancelled) setError(errorMessage(cause)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [revision]);
  const filtered = users.filter(user => `${user.username} ${user.display_name}`.toLowerCase().includes(query.toLowerCase()));
  return <><PageHeading eyebrow="ACCESS MANAGEMENT" title="账号与权限" description="按团队职责分配访问权限。账号禁用、角色变更或重置密码后，现有会话立即失效。" action={<button className="button primary" onClick={() => setEditing({})}><Plus size={16} />创建账号</button>} />
    <div className="role-grid">{roles.map(role => <section className="role-card" key={role.id}><ShieldCheck size={21} /><h3>{role.name}</h3><ul>{role.permissions.map(permission => <li key={permission}>{permissions[permission]}</li>)}</ul></section>)}</div>
    {error && <div role="alert" className="form-error">{error}<button className="quiet-button" onClick={() => setRevision(value => value + 1)}>重试</button></div>}{notice && <p className="auth-notice" role="status">{notice}</p>}
    <section className="panel"><div className="table-toolbar"><div className="table-tabs"><Users size={17} /><span>团队账号</span><b>{users.length}</b></div><SearchBox value={query} onChange={setQuery} placeholder="搜索账号或显示名称…" /></div>
      {loading ? <p className="inset-note">正在读取账号…</p> : !filtered.length ? <p className="inset-note">没有匹配的账号。</p> : <div className="table-scroll"><table><thead><tr><th>成员</th><th>角色</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{filtered.map(user => <tr key={user.id}><td><strong>{user.display_name}</strong><span className="cell-subtitle">{user.username}</span></td><td>{roleNames[user.role]}</td><td><span className={`status status-${user.enabled ? 'enabled' : 'disabled'}`}><i />{user.enabled ? '已启用' : '已禁用'}</span>{user.must_change_password && <span className="cell-subtitle">下次登录须修改密码</span>}</td><td className="muted">{dateTime(user.updated_at)}</td><td><div className="row-actions"><button className="button secondary" onClick={() => setEditing({ user })}><Pencil size={14} />编辑</button><button className="quiet-button" onClick={() => setEditing({ user, reset: true })}><KeyRound size={14} />重置密码</button></div></td></tr>)}</tbody></table></div>}
    </section>{editing && <UserEditor {...editing} roles={roles} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); setNotice('账号已保存，权限变更已生效。'); setRevision(value => value + 1); }} />}</>;
}

function UserEditor({ user, reset, roles, onClose, onSaved }: { user?: User; reset?: boolean; roles: Role[]; onClose: () => void; onSaved: () => void }) {
  const [username, setUsername] = useState('');
  const [name, setName] = useState(user?.display_name ?? '');
  const [role, setRole] = useState(user?.role ?? 'viewer');
  const [enabled, setEnabled] = useState(user?.enabled ?? true);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError('');
    const body = reset ? { password } : user ? { display_name: name, role, enabled } : { username, display_name: name || username, password, role };
    try { await request(user ? `/users/${encodeURIComponent(user.id)}` : '/users', { method: user ? 'PATCH' : 'POST', body }); onSaved(); }
    catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title={reset ? '重置密码' : user ? '编辑账号' : '创建团队账号'} description={user ? `${user.display_name} · ${user.username}` : '新账号首次登录时需要修改初始密码。'} onClose={onClose} busy={busy}><form onSubmit={submit}><div className="dialog-body form-stack">
    {!reset && <>{!user && <label className="field">登录账号<input required pattern="[a-z][a-z0-9_.\-]{2,31}" maxLength={32} value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" /><small>3–32 位，以小写字母开头，可含数字、点、下划线和连字符。</small></label>}<label className="field">显示名称<input maxLength={80} required={!!user} value={name} onChange={event => setName(event.target.value)} /></label><label className="field">角色<select value={role} onChange={event => setRole(event.target.value)}>{roles.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>{user && <label className="field">账号状态<select value={enabled ? 'enabled' : 'disabled'} onChange={event => setEnabled(event.target.value === 'enabled')}><option value="enabled">启用</option><option value="disabled">禁用</option></select><small>禁用会立即结束此账号的所有登录会话。</small></label>}</>}
    {(!user || reset) && <label className="field">临时密码<input type="password" required minLength={12} maxLength={256} autoComplete="new-password" value={password} onChange={event => setPassword(event.target.value)} /><small>至少 12 个字符。请通过可信渠道告知成员，首次登录后必须更换。</small></label>}{error && <p role="alert" className="form-error">{error}</p>}
    </div><FormFooter busy={busy} label={reset ? '确认重置' : '保存账号'} onClose={onClose} /></form></Dialog>;
}

export function PasswordDialog({ onClose }: { onClose: () => void }) {
  const [current, setCurrent] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    if (password !== confirmation) { setError('两次输入的新密码不一致。'); return; }
    setBusy(true); setError('');
    try { await request('/auth/password', { body: { current_password: current, password } }); clearSession(); window.dispatchEvent(new Event('wbot-login-required')); }
    catch (cause) { setError(errorMessage(cause)); } finally { setBusy(false); }
  }
  return <Dialog title="修改登录密码" description="修改后需要重新登录，其他设备上的会话也会结束。" onClose={onClose} busy={busy}><form onSubmit={submit}><div className="dialog-body form-stack"><label className="field">当前密码<input type="password" autoComplete="current-password" required maxLength={256} value={current} onChange={event => setCurrent(event.target.value)} /></label><label className="field">新密码<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={password} onChange={event => setPassword(event.target.value)} /></label><label className="field">确认新密码<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirmation} onChange={event => setConfirmation(event.target.value)} /></label>{error && <p className="form-error" role="alert">{error}</p>}</div><FormFooter busy={busy} label="修改并重新登录" onClose={onClose} /></form></Dialog>;
}
