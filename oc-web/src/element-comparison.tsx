import { elementFields, elementFieldLabels, elementValue, type ElementRecord } from './element-types';

export function ElementComparison({ before, after }: { before: ElementRecord | null; after: ElementRecord | null }) {
  const element = after ?? before;
  if (!element) return null;
  const fields = elementFields.filter(field => !before || !after || JSON.stringify(before[field]) !== JSON.stringify(after[field]));
  return <article className="element-change">
    <header><div><strong>{element.group} / {element.name}</strong><code>{element.id}</code></div><span className={`element-change-label ${before ? after ? 'modified' : 'deleted' : 'added'}`}>{before ? after ? '修改元素' : '删除元素' : '新增元素'}</span></header>
    <div className="element-diff-heading"><span>字段</span><span>变更前</span><span>申请版本</span></div>
    {fields.map(field => <div className="element-diff-row" key={field}><span>{elementFieldLabels[field]}</span><pre className="element-before">{before ? elementValue(before[field]) : '尚不存在'}</pre><pre className="element-after">{after ? elementValue(after[field]) : '将被删除'}</pre></div>)}
  </article>;
}
