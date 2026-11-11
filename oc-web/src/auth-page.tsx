import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { ArrowRight, Eye, EyeOff, LockKeyhole, ShieldCheck } from 'lucide-react';
import { clearSession, errorMessage, getSession, login, LoginRequired, request } from './api';
import { IdentityContext } from './permissions';
import type { Session } from './types';
import './auth.css';

export function AuthenticationBoundary({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    void getSession().then(value => { if (active) setIdentity(value); })
      .catch(cause => { if (active && !(cause instanceof LoginRequired)) setError(errorMessage(cause)); })
      .finally(() => { if (active) setLoading(false); });
    const expired = () => { setIdentity(null); setError('会话已结束，请重新登录。'); };
    window.addEventListener('wbot-login-required', expired);
    return () => { active = false; window.removeEventListener('wbot-login-required', expired); };
  }, []);
  if (loading) return <div className="auth-shell"><div className="initial-loading"><span className="loading-orbit" /><p>正在连接运营中心…</p></div></div>;
  if (!identity || identity.user?.must_change_password) return <AuthPage identity={identity} initialError={error} onAuthenticated={value => { setError(''); setIdentity(value); }} />;
  return <IdentityContext.Provider value={identity}>{children}</IdentityContext.Provider>;
}

function AuthPage({ identity, initialError, onAuthenticated }: { identity: Session | null; initialError: string; onAuthenticated: (session: Session | null) => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [nextPassword, setNextPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);
  const [notice, setNotice] = useState('');
  const changeRequired = Boolean(identity?.user?.must_change_password);
  useEffect(() => { setError(initialError); }, [initialError]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (changeRequired && nextPassword !== confirmation) { setError('两次输入的新密码不一致。'); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      if (changeRequired) {
        await request('/auth/password', { body: { current_password: password, password: nextPassword } });
        clearSession(); onAuthenticated(null); setNotice('密码已更新，请使用新密码登录。');
      } else {
        onAuthenticated(await login(username, password));
      }
      setPassword(''); setNextPassword(''); setConfirmation('');
    } catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }
  return <div className="auth-shell"><section className="auth-story" aria-label="WBot 自动化运营中心"><a className="brand" href="/"><span className="brand-mark">W</span><span>WBot <b>OC</b><small>ORCHESTRATION CENTER</small></span></a>
    <div className="auth-story-copy"><span className="eyebrow">YOUR AUTOMATION, CONNECTED</span><h1>让每一次自动化，<br />都井然有序。</h1><p>连接团队、流程与执行设备。<br />在一个工作空间里，安心交付每一次运行。</p><div className="auth-orbit" aria-hidden="true"><span className="orbit-node">Robot</span><strong>W</strong><span className="orbit-node">Studio</span></div></div><span className="auth-story-footer"><ShieldCheck size={16} />统一身份 · 角色授权 · 集中运营</span></section>
    <section className="auth-form-side"><form className="auth-card" onSubmit={submit}><span className="auth-symbol"><LockKeyhole size={25} /></span><span className="eyebrow">{changeRequired ? 'ACCOUNT SECURITY' : 'WELCOME BACK'}</span><h2>{changeRequired ? '设置你的新密码' : '登录运营中心'}</h2><p>{changeRequired ? `${identity?.user?.display_name}，使用工作空间前，请先替换初始密码。` : '使用管理员为你分配的账号继续。'}</p>
      {!changeRequired && <label className="field">账号<input name="username" autoComplete="username" autoFocus required maxLength={32} value={username} onChange={event => setUsername(event.target.value)} placeholder="输入你的账号" disabled={busy} /></label>}
      <label className="field">{changeRequired ? '当前密码' : '密码'}<span className="password-input"><input name="password" type={visible ? 'text' : 'password'} autoComplete="current-password" autoFocus={changeRequired} required maxLength={256} value={password} onChange={event => setPassword(event.target.value)} placeholder={changeRequired ? '输入当前初始密码' : '输入密码'} disabled={busy} /><button type="button" className="icon-button" aria-label={visible ? '隐藏密码' : '显示密码'} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={17} /> : <Eye size={17} />}</button></span></label>
      {changeRequired && <><label className="field">新密码<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={nextPassword} onChange={event => setNextPassword(event.target.value)} disabled={busy} /><small>至少 12 个字符，建议使用容易记住的长口令。</small></label><label className="field">确认新密码<input type="password" autoComplete="new-password" required minLength={12} maxLength={256} value={confirmation} onChange={event => setConfirmation(event.target.value)} disabled={busy} /></label></>}
      {error && <div className="form-error" role="alert">{error}</div>}{notice && <div className="auth-notice" role="status">{notice}</div>}
      <button className="button primary auth-submit" disabled={busy}>{busy ? '正在处理…' : changeRequired ? '更新密码并重新登录' : '登录'}<ArrowRight size={17} /></button>
      {changeRequired && <button type="button" className="quiet-button" disabled={busy} onClick={async () => { try { await request('/auth/logout', { body: {} }); clearSession(); onAuthenticated(null); } catch (cause) { setError(errorMessage(cause)); } }}>退出当前账号</button>}
      <p className="auth-help">{changeRequired ? '修改密码会结束该账号的其他登录会话。' : '无法登录？请联系工作空间管理员重置密码。'}</p>
    </form><span className="auth-copyright">WBot · 自动化运营中心</span></section></div>;
}
