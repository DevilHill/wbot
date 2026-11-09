'use strict';
const {randomUUID} = require('node:crypto');
const {libraryPath} = require('./core');
const {assistantStateDir, requestAssistant} = require('./assistant-client');
const {nextActions} = require('./shared-view');
const {createSharedElementDocuments} = require('./shared-element-documents');

function createSharedElementCommands({vscode, context, settings, refresh, request = requestAssistant, onStatus = () => {}}) {
  const documents = createSharedElementDocuments(vscode, context);
  const pendingIntents = new Map();
  let busy = false;

  function currentOptions() {
    const configured = settings();
    return {directory:assistantStateDir(configured.assistantStateDir), library:libraryPath(configured.libraryPath)};
  }

  function call(options, action, body = {}) {
    const titles = {repositories:'读取共享仓库', status:'查询分支与审批状态', diff:'读取本地差异', connect:'创建开发分支', commit:'提交元素版本', request:'发送合并申请', pull:'拉取主分支'};
    return vscode.window.withProgress({location:vscode.ProgressLocation.Notification, title:'WBot：' + titles[action]},
      async () => {
        const result = await request(options.directory, action, action === 'repositories' ? {} : {library_path:options.library, ...body});
        if (action === 'status') onStatus(result);
        return result;
      });
  }

  function expected(current) {
    return {expected_fingerprint:current.fingerprint, expected_branch:current.binding?.branch_id || null,
      expected_head:current.binding?.head || null};
  }

  async function mutate(options, action, body) {
    const signature = JSON.stringify([options, action, body]);
    if (!pendingIntents.has(signature)) pendingIntents.set(signature, randomUUID());
    const result = await call(options, action, {...body, request_id:pendingIntents.get(signature)});
    pendingIntents.delete(signature);
    return result;
  }

  function requireBinding(current) {
    if (!current.binding) throw new Error('当前元素库尚未连接共享仓库，请先执行“连接共享元素仓库 / 创建分支”');
  }

  function requireOpenBranch(current) {
    requireBinding(current);
    if (current.remote_error) throw new Error(current.remote_error);
    if (current.branch_status !== 'open') throw new Error('当前分支已经合并，请拉取主分支后创建新的个人分支');
  }

  async function connectSharedElements(options) {
    const catalog = await call(options, 'repositories');
    if (!catalog.items.length) {
      await vscode.window.showInformationMessage('OC 暂无共享元素仓库，请管理员先在“共享元素”中创建仓库。');
      return;
    }
    const selected = await vscode.window.showQuickPick(catalog.items.map(repository => ({
      label:repository.name, description:repository.description || '', detail:repository.id, repository
    })), {placeHolder:'选择共享元素仓库', matchOnDescription:true});
    if (!selected) return;
    const current = await call(options, 'status');
    const carryChanges = current.branch_status === 'merged' && !current.remote_error &&
      selected.repository.id === current.binding?.repository_id;
    if (current.binding && current.dirty && !carryChanges) {
      throw new Error('当前元素库有未提交修改；仅已合并分支可把修改带到同仓库的新分支，其他情况请先提交');
    }
    const name = await vscode.window.showInputBox({title:'创建个人元素分支', value:'fix-elements', ignoreFocusOut:true,
      prompt:'从共享主分支创建；已有同 ID 本地元素会保留为待提交修改',
      validateInput:value => !value.trim() || value.trim().length > 80 ? '分支名称须为 1–80 个字符' : undefined});
    if (name == null) return;
    const effect = carryChanges ? '会基于最新主分支整合当前本地修改；同一字段发生冲突时会停止并保留本地内容。' :
      '主分支中的新元素将加入当前元素库；已有同 ID 元素保留本地内容，同名冲突会停止操作。';
    const choice = await vscode.window.showInformationMessage(
      `连接「${selected.repository.name}」并创建分支「${name.trim()}」？${effect}`,
      {modal:true}, '连接并创建分支');
    if (choice !== '连接并创建分支') return;
    const result = await mutate(options, 'connect', {repository_id:selected.repository.id, branch_name:name.trim(), ...expected(current)});
    await refresh(true);
    await vscode.window.showInformationMessage(`已连接共享元素仓库「${selected.repository.name}」。编辑元素后可查看差异、提交版本并发起合并申请。`);
    return result;
  }

  async function sharedElementChanges(options, changeId) {
    const current = await call(options, 'status');
    requireBinding(current);
    const difference = await call(options, 'diff');
    const choices = difference.changes.filter(change => change.id).map(change => ({label:(change.after || change.before)?.name || change.id, description:({added:'新增', modified:'修改', deleted:'删除'})[change.type], id:change.id}));
    choices.push({label:'查看完整快照差异', id:null});
    const selected = typeof changeId === 'string' ? {id:changeId} : await vscode.window.showQuickPick(choices, {title:'选择要审阅的元素'});
    if (!selected) return;
    const subset = items => selected.id ? items.filter(item => item.id === selected.id) : items;
    await documents.diff(subset(difference.before), subset(difference.after),
      `${current.binding.repository_name} / ${current.binding.branch_name}：提交版本 ↔ 本地修改`);
    return difference;
  }

  async function commitSharedElements(options) {
    const current = await call(options, 'status');
    requireOpenBranch(current);
    if (!current.dirty) { await vscode.window.showInformationMessage('当前没有需要提交的元素修改。'); return; }
    const message = await vscode.window.showInputBox({title:'提交共享元素版本', ignoreFocusOut:true,
      prompt:`将 ${current.changes.length} 项元素变更提交到个人分支 ${current.binding.branch_name}；主分支由管理员合并`,
      validateInput:value => !value.trim() || value.trim().length > 500 ? '提交说明须为 1–500 个字符' : undefined});
    if (message == null) return;
    const result = await mutate(options, 'commit', {message:message.trim(), ...expected(current)});
    await vscode.window.showInformationMessage(`元素版本已提交：${result.commit.id.slice(0, 12)}。可发起合并申请；已有打开的申请会包含这次提交。`);
    return result;
  }

  async function requestElementMerge(options) {
    const current = await call(options, 'status');
    requireOpenBranch(current);
    if (current.dirty) throw new Error('请先提交本地元素修改，再发起合并申请');
    if (current.request?.state === 'open') {
      await vscode.window.showInformationMessage(`已有合并申请「${current.request.title}」等待管理员处理；后续提交会更新这个申请。`);
      return current.request;
    }
    const title = await vscode.window.showInputBox({title:'元素合并申请标题', value:current.binding.branch_name, ignoreFocusOut:true,
      validateInput:value => !value.trim() || value.trim().length > 200 ? '标题须为 1–200 个字符' : undefined});
    if (title == null) return;
    const description = await vscode.window.showInputBox({title:'合并说明', ignoreFocusOut:true,
      prompt:'说明修改原因、涉及页面和验证方式，可留空', validateInput:value => value.length > 10000 ? '说明最多 10000 个字符' : undefined});
    if (description == null) return;
    const result = await mutate(options, 'request', {title:title.trim(), description:description.trim(), ...expected(current)});
    await vscode.window.showInformationMessage(`已发起合并申请「${result.request.title}」，等待 OC 管理员审阅。`);
    return result;
  }

  async function pullSharedElements(options) {
    const current = await call(options, 'status');
    requireBinding(current);
    if (current.dirty) throw new Error('本地有未提交修改，不能拉取主分支；请先保留或提交这些修改');
    if (current.remote_error) throw new Error(current.remote_error);
    if (current.branch_status !== 'merged') throw new Error('个人分支尚未合并，不能用主分支覆盖它；请先提交合并申请并等待管理员处理');
    const choice = await vscode.window.showInformationMessage('把已合并主分支同步到当前元素库？本地内容将更新为主分支版本，后续修改需创建新的个人分支。',
      {modal:true}, '拉取主分支');
    if (choice !== '拉取主分支') return;
    const result = await mutate(options, 'pull', expected(current));
    await vscode.window.showInformationMessage('已同步共享元素主分支。继续开发前，请创建新的个人分支。');
    await refresh(true);
    return result;
  }

  async function sharedElementStatus(options) {
    const current = await call(options, 'status');
    await documents.status({元素库:options.library, 已连接:!!current.binding,
      仓库:current.binding?.repository_name || null, 分支:current.binding?.branch_name || null,
      分支状态:current.branch_status, 本地未提交修改:current.dirty, 变更数量:current.changes.length,
      合并申请:current.request, 待确认操作:current.pending_action || null, 连接提示:current.remote_error || '', 版本信息:current.binding});
    return current;
  }

  async function sharedElements(options) {
    const choices = [
      {label:'$(repo) 连接仓库 / 创建个人分支', detail:'选择 OC 共享仓库，保留现有本地元素', run:connectSharedElements},
      {label:'$(diff) 查看本地差异', detail:'对比已提交版本与本地 XPath、名称和页面信息', run:sharedElementChanges},
      {label:'$(git-commit) 提交元素版本', detail:'保存到个人分支，不直接修改共享主分支', run:commitSharedElements},
      {label:'$(git-pull-request) 发起合并申请', detail:'交由 OC 管理员审阅并合并', run:requestElementMerge},
      {label:'$(info) 查看分支与合并状态', detail:'查看未提交修改、审批结果和连接状态', run:sharedElementStatus},
      {label:'$(cloud-download) 拉取已合并主分支', detail:'只允许已合并且没有本地修改的工作副本', run:pullSharedElements}
    ];
    const current = await call(options, 'status');
    const suggested = nextActions(current).map(name => commands[name]);
    const available = choices.filter(choice => suggested.includes(choice.run) || choice.run === sharedElementStatus || (current.binding && choice.run === sharedElementChanges));
    const selected = await vscode.window.showQuickPick(available, {title:current.binding ? `${current.binding.repository_name} / ${current.binding.branch_name}` : '连接共享仓库', placeHolder:current.remote_error || (current.pending_action ? '上次操作待确认，请查看状态' : '选择下一步操作')});
    if (selected) return selected.run(options);
  }

  const commands = {sharedElements, connectSharedElements, sharedElementChanges,
    commitSharedElements, requestElementMerge, sharedElementStatus, pullSharedElements};
  return Object.fromEntries(Object.entries(commands).map(([name, handler]) => [name, async (...args) => {
    if (busy) throw new Error('共享元素操作仍在进行，请先完成当前操作');
    busy = true;
    try { return await handler(currentOptions(), ...args); }
    finally { busy = false; }
  }]));
}

module.exports = {createSharedElementCommands};
