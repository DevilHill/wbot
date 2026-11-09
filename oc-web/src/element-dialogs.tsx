import { useEffect, useRef, useState } from 'react';
import { History, ShieldCheck } from 'lucide-react';
import { Dialog, FormFooter } from './components';
import { createElementRepository, elementErrorMessage, readElementCommit, restoreElements } from './element-api';
import { ElementCatalog } from './element-catalog';
import { intentFor, type MutationIntent } from './element-review';
import type { ElementCommit, ElementRepository } from './element-types';
import { dateTime } from './format';

export function CreateElementRepository({ onClose, onSaved }: { onClose: () => void; onSaved: (repository: ElementRepository) => void }) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const intent = useRef<MutationIntent | null>(null);
  const submitting = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function save() {
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError('');
    const body = { name: name.trim(), description: description.trim() };
    intent.current = intentFor(intent.current, body);
    try {
      const result = await createElementRepository({ ...body, request_id: intent.current.id });
      if (mounted.current) onSaved(result.repository);
    } catch (cause) { if (mounted.current) setError(elementErrorMessage(cause)); }
    finally { submitting.current = false; if (mounted.current) setBusy(false); }
  }
  return <Dialog title="创建共享元素仓库" description="按业务系统组织可复用的页面定位" onClose={onClose} busy={busy}>
    <form onSubmit={event => { event.preventDefault(); void save(); }}><div className="dialog-body parameter-fields">
      <label className="field"><span>仓库名称</span><input autoFocus required maxLength={120} placeholder="例如 ERP 系统页面元素" value={name} disabled={busy} onChange={event => setName(event.target.value)} /></label>
      <label className="field"><span>描述</span><textarea rows={3} maxLength={4000} placeholder="说明适用系统、页面范围或维护约定" value={description} disabled={busy} onChange={event => setDescription(event.target.value)} /></label>
      <p className="inset-note"><ShieldCheck size={15} /> 创建后生成受保护的 main 分支。开发者从 VS Code 提交到自己的分支，由管理端审阅后合并。</p>
      {error && <p className="form-error" role="alert">{error}</p>}
    </div><FormFooter busy={busy} disabled={!name.trim()} label="创建仓库" onClose={onClose} /></form>
  </Dialog>;
}

export function ElementCommitDialog({ repositoryId, commitId, expectedHead, onClose, onRestored }: {
  repositoryId: string; commitId: string; expectedHead: string; onClose: () => void; onRestored: () => void;
}) {
  const [commit, setCommit] = useState<ElementCommit | null>(null);
  const [error, setError] = useState('');
  const [restoring, setRestoring] = useState(false);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const intent = useRef<MutationIntent | null>(null);
  const submitting = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    void readElementCommit(repositoryId, commitId).then(result => { if (!cancelled) setCommit(result.commit); }).catch(cause => { if (!cancelled) setError(elementErrorMessage(cause)); });
    return () => { cancelled = true; mounted.current = false; };
  }, [repositoryId, commitId]);
  async function restore() {
    if (!commit || submitting.current) return;
    submitting.current = true; setBusy(true); setError('');
    const body = { expected_head: expectedHead, commit_id: commit.id, message: message.trim() };
    intent.current = intentFor(intent.current, body);
    try {
      await restoreElements(repositoryId, { ...body, request_id: intent.current.id });
      if (mounted.current) onRestored();
    } catch (cause) { if (mounted.current) setError(`${elementErrorMessage(cause)} 若主分支已变化，请关闭并重新打开此版本。`); }
    finally { submitting.current = false; if (mounted.current) setBusy(false); }
  }
  return <Dialog title="元素版本快照" description={commitId} onClose={onClose} busy={busy} wide>
    <div className="dialog-body element-commit-body">
      {error && <p className="form-error" role="alert">{error}</p>}
      {!commit ? <p className="muted">{error ? '未能读取这个版本。' : '正在读取版本…'}</p> : <>
        <h3>{commit.message}</h3><p className="muted">{commit.author.name} · {commit.author.kind === 'admin' ? '管理端' : '开发设备'} · {dateTime(commit.created_at)}</p>
        <p className="small-label">版本 ID <code>{commit.id}</code></p>
        {commit.restored_from && <p className="inset-note">恢复自版本 <code>{commit.restored_from}</code></p>}
        <ElementCatalog items={commit.items} />
        {commit.id === expectedHead ? <p className="inset-note">这是当前主分支版本。</p> : !restoring ? <button className="button secondary" onClick={() => setRestoring(true)}><History size={15} />将主分支恢复到此版本</button> : <form className="element-restore-form" onSubmit={event => { event.preventDefault(); void restore(); }}>
          <strong>确认恢复主分支</strong><p>恢复会生成一条新提交，保留原有历史。其他开发者拉取后才会使用这个版本，已打包的自动化不受影响。</p>
          <label className="field"><span>恢复原因</span><input required maxLength={2000} value={message} disabled={busy} onChange={event => setMessage(event.target.value)} placeholder="例如新 XPath 在旧版页面失效，恢复上一个可用版本" /></label>
          <div className="row-actions"><button type="button" className="button secondary" disabled={busy} onClick={() => setRestoring(false)}>取消恢复</button><button type="submit" className="button primary" disabled={busy || !message.trim()}>{busy ? '正在恢复…' : '确认恢复并创建提交'}</button></div>
        </form>}
      </>}
    </div>
  </Dialog>;
}
