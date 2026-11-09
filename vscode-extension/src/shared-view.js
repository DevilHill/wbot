'use strict';

function nextActions(state) {
  if (state.remote_error || state.pending_action) return [];
  if (!state.binding) return ['connectSharedElements'];
  if (state.branch_status === 'merged') return state.dirty ? ['connectSharedElements'] : ['pullSharedElements', 'connectSharedElements'];
  if (state.dirty) return ['sharedElementChanges', 'commitSharedElements'];
  return state.request?.state === 'open' ? [] : ['requestElementMerge'];
}

function createSharedView(vscode, context, readStatus) {
  const changes = new vscode.EventEmitter();
  let state = null, error = '', disposed = false, pending = null, generation = 0;
  const provider = {
    onDidChangeTreeData: changes.event,
    getChildren() {
      if (!state) return [];
      const rows = [
        {label:'仓库', description:state.binding?.repository_name || '尚未连接'},
        {label:'分支', description:state.binding?.branch_name || '选择仓库后创建'},
        {label:'合并申请', description:({open:'等待管理员审阅', merged:'已合并', closed:'已关闭'})[state.request?.state] || '尚未发起', tooltip:state.request?.close_reason || state.request?.title},
      ];
      if (state.pending_action) rows.push({label:'操作待确认', description:state.pending_action});
      for (const change of state.changes || []) {
        const item = change.after || change.before;
        rows.push({label:item?.name || change.id, description:({added:'新增', modified:'修改', deleted:'删除'})[change.type],
          tooltip:item ? `${item.group} / ${item.name}` : change.id, changeId:change.id});
      }
      return rows;
    },
    getTreeItem(row) {
      const item = new vscode.TreeItem(row.label, vscode.TreeItemCollapsibleState.None);
      item.description = row.description;
      item.tooltip = row.tooltip || row.description;
      item.iconPath = new vscode.ThemeIcon(row.changeId ? 'diff' : 'info');
      if (row.changeId) item.command = {command:'wbot.sharedElementChanges', title:'查看元素差异', arguments:[row.changeId]};
      return item;
    }
  };
  const view = vscode.window.createTreeView('wbot.shared', {treeDataProvider:provider});
  function update(value) {
    if (disposed) return;
    state = value;
    error = value.remote_error || '';
    const next = nextActions(value);
    const hints = {connectSharedElements:'连接仓库 / 创建新分支', sharedElementChanges:'查看差异，再提交版本', pullSharedElements:'拉取主分支，或创建新分支', requestElementMerge:'发起合并申请'};
    view.message = error || (value.pending_action ? '上次操作待确认，请刷新状态后重试原操作。' : hints[next[0]] || '等待审阅；新的修改仍可继续提交。');
    view.description = `${value.changes?.length || 0} 项修改`;
    changes.fire();
  }
  async function refresh() {
    if (pending || disposed) return pending;
    const revision = generation;
    pending = readStatus().then(value => { if (revision === generation) update(value); }).catch(reason => {
      if (disposed || revision !== generation) return;
      error = reason.message;
      view.message = '无法读取共享状态：' + error;
      view.description = '连接异常';
    }).finally(() => { pending = null; });
    return pending;
  }
  const timer = setInterval(() => { if (view.visible) refresh(); }, 15000);
  context.subscriptions.push(view, changes, view.onDidChangeVisibility(event => { if (event.visible) refresh(); }),
    {dispose() { disposed = true; generation++; clearInterval(timer); }});
  return {refresh, update, invalidate() { generation++; state = null; view.message = '连接配置已更改，请刷新'; changes.fire(); }, provider};
}

module.exports = {nextActions, createSharedView};
