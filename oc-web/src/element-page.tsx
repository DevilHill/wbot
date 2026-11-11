import { PermissionButton } from './permissions';
import { useEffect, useState } from 'react';
import { Code2, GitBranch, GitCommitHorizontal, GitMerge, Plus, RefreshCw, ShieldCheck } from 'lucide-react';
import { EmptyState, PageHeading } from './components';
import { elementErrorMessage, readElementRepositories, readElementRepository } from './element-api';
import { ElementCatalog } from './element-catalog';
import { CreateElementRepository, ElementCommitDialog } from './element-dialogs';
import { ElementMergeDialog, mergeStateLabels } from './element-merge-dialog';
import { dateTime } from './format';
import type { ElementMergeRequest, ElementRepository, ElementRepositoryDetail } from './element-types';
import './elements.css';

type ElementTab = 'elements' | 'history' | 'requests';
type ElementModal = { type: 'create' } | { type: 'commit'; repositoryId: string; commitId: string; expectedHead: string } | { type: 'review'; repositoryId: string; requestId: string } | null;

export function SharedElements() {
  const [repositories, setRepositories] = useState<ElementRepository[]>([]);
  const [repositoryId, setRepositoryId] = useState('');
  const [detail, setDetail] = useState<ElementRepositoryDetail | null>(null);
  const [tab, setTab] = useState<ElementTab>('elements');
  const [modal, setModal] = useState<ElementModal>(null);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    setLoading(true); setError('');
    async function load() {
      try {
        const [catalog, current] = await Promise.all([readElementRepositories(), repositoryId ? readElementRepository(repositoryId) : Promise.resolve(null)]);
        if (cancelled) return;
        setRepositories(catalog.items); setDetail(current); setError('');
        if (!repositoryId && catalog.items.length) setRepositoryId(catalog.items[0].id);
      } catch (cause) { if (!cancelled) setError(elementErrorMessage(cause)); }
      finally { if (!cancelled) { setLoading(false); timer = setTimeout(load, 5000); } }
    }
    void load();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [repositoryId, revision]);
  const current = detail?.repository.id === repositoryId ? detail : null;
  function changed(message: string) { setNotice(message); setModal(null); setRevision(value => value + 1); }
  function showCommit(commitId: string) {
    if (current) setModal({ type: 'commit', repositoryId, commitId, expectedHead: current.repository.head });
  }
  return <>
    <PageHeading eyebrow="SHARED ELEMENT REPOSITORIES" title="共享元素" description="让页面定位成为可审阅、可追溯的团队资产。" action={<PermissionButton permission="elements.manage" className="button primary" onClick={() => setModal({ type: 'create' })}><Plus size={16} />创建仓库</PermissionButton>} />
    <div className="element-workflow"><span><Code2 size={17} />VS Code 修改元素</span><i>→</i><span><GitBranch size={17} />提交开发分支</span><i>→</i><span><GitMerge size={17} />OC 审阅合并</span><i>→</i><span><ShieldCheck size={17} />团队拉取主分支</span></div>
    {error && <p className="form-error element-page-message" role="alert">{error} {current && '当前保留上次成功读取的版本。'}</p>}
    {notice && <div className="element-page-notice" role="status"><span>{notice}</span><button className="quiet-button" onClick={() => setNotice('')}>关闭</button></div>}
    <div className="element-repository-selector"><label><span>当前仓库</span><select aria-label="选择共享元素仓库" value={repositoryId} disabled={!repositories.length} onChange={event => { setRepositoryId(event.target.value); setDetail(null); setNotice(''); }}>
      {!repositories.length && <option value="">{loading ? '读取中…' : '尚无仓库'}</option>}{repositories.map(repository => <option key={repository.id} value={repository.id}>{repository.name}</option>)}
    </select></label><button className="button secondary" disabled={loading} onClick={() => setRevision(value => value + 1)}><RefreshCw size={15} className={loading ? 'spinning' : ''} />刷新仓库</button></div>
    {!current ? <section className="panel"><EmptyState icon={Code2} title={loading ? '正在读取元素仓库' : repositories.length ? '暂时无法读取这个仓库' : '建立团队的第一个元素仓库'} action={!loading && !repositories.length && <PermissionButton permission="elements.manage" className="button secondary" onClick={() => setModal({ type: 'create' })}><Plus size={15} />创建共享仓库</PermissionButton>}>{loading ? '正在读取分支、版本和合并申请…' : repositories.length ? '请检查连接后刷新重试。' : '按业务系统创建仓库，让开发者从现有元素库提交 XPath，并在这里统一审阅。'}</EmptyState></section> : <>
      <section className="panel element-repository-panel"><div className="element-repository-heading"><div><h2>{current.repository.name}</h2><p>{current.repository.description || '共享页面元素与 XPath 定位'}</p></div><span className="element-protected"><ShieldCheck size={14} />main 受保护</span></div>
        <div className="element-repository-meta"><span><Code2 size={14} />{current.head.items.length} 个元素</span><span><GitBranch size={14} />{current.branches.length} 个开发分支</span><span><GitMerge size={14} />{current.requests.filter(item => item.state === 'open').length} 个待合并申请</span><button className="quiet-button mono" onClick={() => showCommit(current.repository.head)} title={current.repository.head}><GitCommitHorizontal size={14} />{current.repository.head.slice(0, 12)}</button></div>
        <div className="element-tabs" role="tablist" aria-label="共享元素仓库内容">{([{ id: 'elements', label: '主分支元素', icon: Code2 }, { id: 'history', label: '分支与历史', icon: GitBranch }, { id: 'requests', label: '合并申请', icon: GitMerge }] as const).map(item => <button key={item.id} role="tab" aria-selected={tab === item.id} className={tab === item.id ? 'selected' : ''} onClick={() => setTab(item.id)}><item.icon size={16} />{item.label}{item.id === 'requests' && <b>{current.requests.filter(request => request.state === 'open').length}</b>}</button>)}</div>
        <div role="tabpanel">
          {tab === 'elements' && <ElementCatalog items={current.head.items} />}
          {tab === 'history' && <ElementHistory detail={current} onCommit={showCommit} />}
          {tab === 'requests' && <ElementRequests items={current.requests} onReview={requestId => setModal({ type: 'review', repositoryId, requestId })} />}
        </div>
      </section>
      <p className="page-footnote"><ShieldCheck size={14} />开发分支不会直接改变主分支。合并或恢复生成新版本，开发者主动拉取后生效，已打包自动化保持原有元素快照。</p>
    </>}
    {modal?.type === 'create' && <CreateElementRepository onClose={() => setModal(null)} onSaved={repository => { setRepositories(items => [repository, ...items.filter(item => item.id !== repository.id)]); setRepositoryId(repository.id); setDetail(null); changed('共享元素仓库已创建，可以从 VS Code 连接'); }} />}
    {modal?.type === 'commit' && <ElementCommitDialog key={modal.commitId} {...modal} onClose={() => setModal(null)} onRestored={() => changed('已创建恢复提交，主分支更新完成')} />}
    {modal?.type === 'review' && <ElementMergeDialog key={modal.requestId} {...modal} onClose={() => setModal(null)} onChanged={changed} />}
  </>;
}

export function ElementHistory({ detail, onCommit }: { detail: ElementRepositoryDetail; onCommit: (id: string) => void }) {
  return <div className="element-history"><div className="element-section-heading"><h3>开发分支</h3><small>分支归属对应的已绑定设备</small></div>
    {!detail.branches.length ? <p className="inset-note">还没有开发分支。开发者从 VS Code 连接仓库后，可以创建个人分支。</p> : <div className="element-branches">{detail.branches.map(branch => <article key={branch.id}><GitBranch size={19} /><div><strong>{branch.name}</strong><span>{branch.device_name} · {dateTime(branch.updated_at)}</span></div><span className={`element-request-state ${branch.status === 'merged' ? 'merged' : 'open'}`}>{branch.status === 'merged' ? '已合并' : '开发中'}</span><button className="button secondary" onClick={() => onCommit(branch.head)}>查看快照</button></article>)}</div>}
    <div className="element-section-heading"><h3>提交历史</h3><small>最近 {detail.commits.length} 条提交 · 包含开发分支</small></div><div className="table-scroll"><table className="element-history-table"><thead><tr><th>版本 / 提交说明</th><th>提交来源</th><th>时间</th><th>查看</th></tr></thead><tbody>{detail.commits.map(commit => <tr key={commit.id}><td><strong>{commit.message}</strong><span className="cell-subtitle mono">{commit.id.slice(0, 12)}{commit.id === detail.repository.head && <b className="element-head-label">main</b>}</span></td><td>{commit.author.name}<span className="cell-subtitle">{commit.author.kind === 'admin' ? '管理端' : '开发设备'}</span></td><td className="tabular muted">{dateTime(commit.created_at)}</td><td><button className="button secondary" onClick={() => onCommit(commit.id)}>查看版本</button></td></tr>)}</tbody></table></div>
  </div>;
}

export function ElementRequests({ items, onReview }: { items: ElementMergeRequest[]; onReview: (id: string) => void }) {
  const [filter, setFilter] = useState<'all' | ElementMergeRequest['state']>('open');
  const filtered = items.filter(item => filter === 'all' || item.state === filter);
  return <><div className="table-toolbar"><div className="table-tabs"><span>合并申请</span><b>{filtered.length}</b></div><select className="filter-select" aria-label="筛选合并申请状态" value={filter} onChange={event => setFilter(event.target.value as typeof filter)}><option value="open">待合并</option><option value="merged">已合并</option><option value="closed">已关闭</option><option value="all">全部申请</option></select></div>
    {!filtered.length ? <EmptyState icon={GitMerge} title="暂无符合条件的合并申请">开发者提交分支版本后，可在 VS Code 发起合并申请。待合并的变更会自动出现在这里。</EmptyState> : <div className="table-scroll"><table className="element-requests-table"><thead><tr><th>申请 / 开发分支</th><th>提交设备</th><th>状态</th><th>更新于</th><th>审阅</th></tr></thead><tbody>{filtered.map(item => <tr key={item.id}><td><button className="table-title" onClick={() => onReview(item.id)}>{item.title}</button><span className="cell-subtitle mono">{item.branch_name} → main</span></td><td>{item.device_name}</td><td><span className={`element-request-state ${item.state}`}>{mergeStateLabels[item.state]}</span></td><td className="tabular muted">{dateTime(item.updated_at)}</td><td><button className="button secondary" onClick={() => onReview(item.id)}>{item.state === 'open' ? '审阅变更' : '查看详情'}</button></td></tr>)}</tbody></table></div>}
  </>;
}
