import { useState } from 'react';
import { Code2 } from 'lucide-react';
import { EmptyState, SearchBox } from './components';
import { elementValue, type ElementRecord } from './element-types';

export function ElementCatalog({ items }: { items: ElementRecord[] }) {
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(100);
  const filtered = items.filter(item => `${item.group} ${item.name} ${item.xpath} ${item.description}`.toLowerCase().includes(query.toLowerCase()));
  return <>
    <div className="table-toolbar"><div className="table-tabs"><span>页面元素</span><b>{filtered.length}</b></div><SearchBox value={query} onChange={value => { setQuery(value); setLimit(100); }} placeholder="搜索页面、元素或 XPath…" /></div>
    {!filtered.length ? <EmptyState icon={Code2} title={query ? '没有匹配的元素' : '这个版本还没有元素'}>{query ? '尝试其他名称或 XPath。' : '开发者可以在 VS Code 中提交元素，并向主分支发起合并申请。'}</EmptyState> : <div className="table-scroll"><table className="element-table"><thead><tr><th>页面 / 元素</th><th>XPath 与定位详情</th></tr></thead><tbody>{filtered.slice(0, limit).map(item => <tr key={item.id}>
      <td><strong>{item.name}</strong><span className="cell-subtitle">{item.group}</span></td><td><code className="element-xpath">{item.xpath}</code><details className="element-metadata"><summary>查看定位详情</summary><dl><div><dt>元素 ID</dt><dd><code>{item.id}</code></dd></div><div><dt>页面 URL</dt><dd>{item.url || '未设置'}</dd></div><div><dt>描述</dt><dd>{item.description || '未填写'}</dd></div><div><dt>框架定位</dt><dd><pre>{elementValue(item.frame)}</pre></dd></div></dl></details></td>
    </tr>)}</tbody></table></div>}
    {filtered.length > limit && <div className="element-load-more"><button className="button secondary" onClick={() => setLimit(value => value + 100)}>再显示 100 个元素</button><span className="muted">已显示 {limit} / {filtered.length}</span></div>}
  </>;
}
