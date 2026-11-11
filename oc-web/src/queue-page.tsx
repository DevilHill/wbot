import { useState } from 'react';
import { Clock3 } from 'lucide-react';
import { EmptyState, PageHeading, SearchBox } from './components';
import { JobsTable, type PageProps } from './pages';
import { activeStates } from './format';

export function Queue({ snapshot, actions }: PageProps) {
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState('queued');
  const pending = snapshot.jobs.filter(job => job.state === 'queued');
  const active = snapshot.jobs.filter(job => activeStates.has(job.state) && job.state !== 'queued');
  const unknown = snapshot.jobs.filter(job => job.state === 'unknown');
  const jobs = [...(scope === 'queued' ? pending : scope === 'unknown' ? unknown : active)]
    .filter(job => `${job.process_name} ${job.device_name} ${job.environment_name ?? ''}`.toLowerCase().includes(query.toLowerCase()))
    .sort((left, right) => (right.priority ?? 50) - (left.priority ?? 50) || left.created_at - right.created_at);
  return <><PageHeading eyebrow="PROCESS RUN QUEUE" title="流程运行队列" description="任务持久化排队；按优先级从高到低、同优先级按提交顺序分配空闲 Robot。" />
    <div className="queue-summary"><div><strong>{pending.length}</strong><span>等待调度</span></div><div><strong>{active.length}</strong><span>派发与执行中</span></div><div><strong>{unknown.length}</strong><span>状态待核实</span></div></div>
    <section className="panel"><div className="table-toolbar"><div className="toolbar-filters"><label className="sr-only" htmlFor="queue-scope">队列范围</label><select id="queue-scope" className="filter-select" value={scope} onChange={event => setScope(event.target.value)}><option value="queued">等待调度</option><option value="active">派发与执行中</option><option value="unknown">状态待核实</option></select></div><SearchBox value={query} onChange={setQuery} placeholder="搜索流程、Robot 或环境…" /></div>{jobs.length ? <JobsTable jobs={jobs} onSelect={actions.showJob} /> : <EmptyState icon={Clock3} title={query ? '没有匹配的任务' : '当前范围内没有任务'}>{query ? '尝试其他流程、Robot 或环境名称。' : '可在流程部署中提交新任务，已结束的任务保存在运行日志中。'}</EmptyState>}</section>
    <p className="page-footnote"><Clock3 size={14} />点击任务查看等待原因或取消等待。派发状态不确定的任务不会自动重跑，也不会释放 Robot 给其他作业。</p></>;
}
