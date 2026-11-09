import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, GitMerge, RefreshCw, ShieldCheck } from 'lucide-react';
import { Dialog } from './components';
import { closeElementRequest, elementErrorMessage, mergeElements, readElementReview } from './element-api';
import { ElementComparison } from './element-comparison';
import { canMergeElements, conflictKey, intentFor, reviewedResolutions, type ConflictChoices, type MutationIntent } from './element-review';
import { elementFieldLabels, elementValue, type ElementConflict, type ElementReview } from './element-types';
import { dateTime } from './format';

export const mergeStateLabels = { open: '待合并', merged: '已合并', closed: '已关闭' };

export function ElementConflicts({ conflicts, choices, onChoose, disabled }: {
  conflicts: ElementConflict[]; choices: ConflictChoices; onChoose: (key: string, value: 'main' | 'source') => void; disabled: boolean;
}) {
  return <section className="element-conflicts"><h3><AlertTriangle size={17} />需要处理 {conflicts.length} 项冲突</h3><p>每项选择要保留的内容。不会根据提交时间自动覆盖任何一方。</p>
    {conflicts.map(conflict => {
      const key = conflictKey(conflict.id, conflict.field);
      return <fieldset key={key} disabled={disabled}><legend><code>{conflict.id}</code><span>{conflict.field === '__record__' ? '整个元素（新增 / 删除冲突）' : elementFieldLabels[conflict.field]}</span></legend>
        <details><summary>查看共同起点</summary><pre>{conflict.base === null && conflict.field === '__record__' ? '元素不存在' : elementValue(conflict.base)}</pre></details>
        <div className="element-conflict-options">{(['main', 'source'] as const).map(side => <label key={side} className={choices[key] === side ? 'selected' : ''}><span><input type="radio" name={key} checked={choices[key] === side} onChange={() => onChoose(key, side)} />{side === 'main' ? '保留主分支' : '采用申请版本'}</span><pre>{conflict[side] === null && conflict.field === '__record__' ? '删除这个元素' : elementValue(conflict[side])}</pre></label>)}</div>
      </fieldset>;
    })}
  </section>;
}

export function ElementMergeDialog({ repositoryId, requestId, onClose, onChanged }: {
  repositoryId: string; requestId: string; onClose: () => void; onChanged: (message: string) => void;
}) {
  const [review, setReview] = useState<ElementReview | null>(null);
  const [choices, setChoices] = useState<ConflictChoices>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [error, setError] = useState('');
  const [closing, setClosing] = useState(false);
  const [reason, setReason] = useState('');
  const [changeLimit, setChangeLimit] = useState(50);
  const revision = useRef(0);
  const submitting = useRef(false);
  const mounted = useRef(true);
  const intent = useRef<MutationIntent | null>(null);
  const refresh = useCallback(async () => {
    const current = ++revision.current;
    setLoading(true); setError('');
    try {
      const response = await readElementReview(repositoryId, requestId);
      if (mounted.current && current === revision.current) { setReview(response); setChoices({}); setNeedsRefresh(false); setChangeLimit(50); }
    } catch (cause) { if (mounted.current && current === revision.current) { setError(elementErrorMessage(cause)); setNeedsRefresh(true); } }
    finally { if (mounted.current && current === revision.current) setLoading(false); }
  }, [repositoryId, requestId]);
  useEffect(() => { mounted.current = true; void refresh(); return () => { mounted.current = false; revision.current += 1; }; }, [refresh]);

  async function submit(action: 'merge' | 'close') {
    if (!review || submitting.current || loading || needsRefresh) return;
    if (action === 'merge' && !canMergeElements(review, choices)) return;
    submitting.current = true; setBusy(true); setError('');
    try {
      if (action === 'merge') {
        const body = { expected_main: review.main_head, expected_source: review.source_head, resolutions: reviewedResolutions(review, choices) };
        intent.current = intentFor(intent.current, { action, ...body });
        await mergeElements(repositoryId, requestId, { ...body, request_id: intent.current.id });
      } else {
        const body = { expected_source: review.source_head, reason: reason.trim() };
        intent.current = intentFor(intent.current, { action, ...body });
        await closeElementRequest(repositoryId, requestId, { ...body, request_id: intent.current.id });
      }
      if (mounted.current) onChanged(action === 'merge' ? '元素变更已合并到主分支' : '合并申请已关闭');
    } catch (cause) {
      if (mounted.current) { setError(elementErrorMessage(cause)); setNeedsRefresh(true); }
    } finally { submitting.current = false; if (mounted.current) setBusy(false); }
  }
  const actionable = review?.request.state === 'open';
  return <Dialog title={review?.request.title ?? '审阅元素合并申请'} description={review ? `${review.request.branch_name} → main` : '正在读取申请'} onClose={onClose} busy={busy} wide>
    <div className="dialog-body element-review-body">
      <div className="element-review-toolbar"><span className={`element-request-state ${review?.request.state ?? 'open'}`}>{review ? mergeStateLabels[review.request.state] : '读取中'}</span><button className="button secondary" disabled={busy || loading} onClick={() => void refresh()}><RefreshCw size={14} />{loading ? '读取中…' : '刷新审阅'}</button></div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {needsRefresh && <p className="inset-note">请先刷新审阅，核对最新分支版本并重新选择冲突结果。若元素重名，请让开发者改名后提交新版本。</p>}
      {review && <>
        <p className="muted">提交设备 {review.request.device_name} · {dateTime(review.request.created_at)}</p>
        {review.request.description && <p className="element-request-description">{review.request.description}</p>}
        <dl className="element-review-revisions"><div><dt>当前主分支</dt><dd><code>{review.main_head}</code></dd></div><div><dt>本次申请版本</dt><dd><code>{review.source_head}</code></dd></div><div><dt>共同起点</dt><dd><code>{review.base_commit}</code></dd></div></dl>
        {review.request.close_reason && <p className="inset-note">关闭原因：{review.request.close_reason}</p>}
        {review.request.merge_commit && <p className="inset-note">合并提交 <code>{review.request.merge_commit}</code></p>}
        {actionable && (review.conflicts.length ? <ElementConflicts conflicts={review.conflicts} choices={choices} onChoose={(key, value) => setChoices(current => ({ ...current, [key]: value }))} disabled={busy || loading || needsRefresh} /> : <div className="element-merge-ready"><ShieldCheck size={18} /><div><strong>没有需要手动处理的冲突</strong><p>不同元素和不同字段的变更可以自动合并。请核对下方 XPath 和定位范围。</p></div></div>)}
        <div className="element-section-heading"><h3>申请中的变更 <span>{review.changes.length}</span></h3><small>开发分支起点 → 申请版本</small></div>
        {!review.changes.length ? <p className="inset-note">此申请未包含元素内容变更，可以关闭申请。</p> : review.changes.slice(0, changeLimit).map(change => <ElementComparison key={change.id} before={change.before} after={change.after} />)}
        {review.changes.length > changeLimit && <button className="button secondary" onClick={() => setChangeLimit(value => value + 50)}>继续查看后 50 项变更</button>}
        {closing && actionable && <form id="close-element-request" className="element-close-form" onSubmit={event => { event.preventDefault(); void submit('close'); }}><label className="field"><span>关闭原因</span><textarea required maxLength={2000} rows={3} value={reason} disabled={busy} onChange={event => setReason(event.target.value)} placeholder="说明需要修改或重新验证的内容，开发者可在 VS Code 中查看。" /></label></form>}
      </>}
    </div>
    <footer className="dialog-footer element-review-footer">
      {actionable ? closing ? <><button className="button secondary" disabled={busy} onClick={() => setClosing(false)}>继续审阅</button><button className="button danger" type="submit" form="close-element-request" disabled={busy || loading || needsRefresh || !reason.trim()}>{busy ? '正在处理…' : '确认关闭申请'}</button></> : <><button className="button secondary" disabled={busy || loading || needsRefresh} onClick={() => setClosing(true)}>关闭申请</button><button className="button primary" disabled={busy || loading || needsRefresh || !review || !review.changes.length || !canMergeElements(review, choices)} onClick={() => void submit('merge')}><GitMerge size={16} />{busy ? '正在合并…' : '批准并合并到 main'}</button></> : <button className="button secondary" onClick={onClose}>关闭</button>}
    </footer>
  </Dialog>;
}
