/* Monaco 编码工作区：文件模型独立保存、运行日志、定位器插入。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const tabs = new Map();
  let state = null, editor = null, active = null, opening = false, polling = false;
  let running = false, startingRun = false, creatingProject = false, clearedRun = '', clearedPrefix = '', fileRequest = 0;
  const message = (text, error = false) => {
    $('studioStatus').textContent = text;
    $('studioStatus').classList.toggle('error', error);
  };
  async function api(action, data = {}) {
    const response = await fetch('/api/studio/' + action, {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({token: state.token, project: state.project, ...data})});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || '编码服务请求失败');
    return result;
  }
  const handle = action => (...args) => Promise.resolve().then(() => action(...args)).catch(error => message(error.message, true));
  const dirty = tab => tab.model.getValue() !== tab.saved;
  const language = path => ({py: 'python', json: 'json', js: 'javascript', html: 'html', css: 'css', md: 'markdown', xml: 'xml', yaml: 'yaml', yml: 'yaml', toml: 'ini'})[path.split('.').pop()] || 'plaintext';

  function renderTabs() {
    $('studioTabs').replaceChildren();
    for (const [path, tab] of tabs) {
      const wrapper = document.createElement('div'); wrapper.className = 'editor-tab' + (path === active ? ' active' : '');
      const name = document.createElement('button'); name.setAttribute('role', 'tab');
      name.setAttribute('aria-selected', String(path === active)); name.title = path;
      name.textContent = (path.endsWith('.py') ? 'Py  ' : '') + path.split('/').pop() + (dirty(tab) ? ' ●' : '');
      name.onclick = () => activate(path);
      const close = document.createElement('button'); close.textContent = '×'; close.setAttribute('aria-label', '关闭 ' + path);
      close.onclick = () => {
        if (dirty(tab) && !window.confirm(path + ' 有未保存更改。确认放弃这些更改并关闭？')) return;
        tabs.delete(path); tab.model.dispose();
        if (active === path) activate(tabs.keys().next().value || null);
        renderTabs();
      };
      wrapper.append(name, close); $('studioTabs').append(wrapper);
    }
  }
  function activate(path) {
    if (active && tabs.has(active)) tabs.get(active).view = editor.saveViewState();
    active = path;
    editor.setModel(path ? tabs.get(path).model : null);
    if (path && tabs.get(path).view) editor.restoreViewState(tabs.get(path).view);
    $('studioWelcome').hidden = !!path;
    $('studioRun').disabled = running || startingRun || !path || !path.endsWith('.py');
    renderTabs();
    document.querySelectorAll('.file-row').forEach(row => row.classList.toggle('active', row.dataset.path === path));
    if (path) { editor.focus(); message(path + ' · ' + state.python); }
  }
  async function openFile(path) {
    if (!editor) return;
    const request = ++fileRequest;
    const project = state.project;
    if (!tabs.has(path)) {
      const result = await api('read', {path});
      if (project !== state.project) return;
      // 同一文件的快速双击只创建一个模型。
      if (!tabs.has(path)) {
        const model = monaco.editor.createModel(result.text, language(path),
          monaco.Uri.parse('file:///wbot/' + project + '/' + path));
        tabs.set(path, {model, saved: result.text, version: result.version});
        model.onDidChangeContent(() => renderTabs());
      }
    }
    if (request === fileRequest) activate(path); else renderTabs();
  }
  async function tree(container = $('studioTree'), path = '', depth = 0) {
    const project = state.project;
    const result = await api('tree', {path});
    if (project !== state.project) return;
    container.replaceChildren();
    if (!result.items.length && !path) container.textContent = '空项目 · 点击 ＋ 新建 Python 文件';
    for (const item of result.items) {
      const row = document.createElement('button'); row.className = 'file-row'; row.dataset.path = item.path;
      row.style.paddingLeft = (12 + depth * 12) + 'px'; row.title = item.path;
      row.setAttribute('role', 'treeitem');
      const icon = document.createElement('span'); icon.className = 'file-icon';
      icon.textContent = item.directory ? '▸' : item.name.endsWith('.py') ? 'Py' : '◇';
      const label = document.createElement('span'); label.textContent = item.name; row.append(icon, label);
      container.append(row);
      if (item.directory) {
        const children = document.createElement('div'); children.hidden = true; container.append(children);
        row.onclick = handle(async () => {
          if (children.hidden) { await tree(children, item.path, depth + 1); children.hidden = false; icon.textContent = '▾'; }
          else { children.hidden = true; icon.textContent = '▸'; }
        });
      } else row.onclick = handle(() => openFile(item.path));
    }
  }
  async function save(path = active) {
    if (!path || !tabs.has(path)) return;
    const tab = tabs.get(path);
    if (tab.saving) await tab.saving;
    if (!dirty(tab)) return;
    const text = tab.model.getValue();
    tab.saving = api('write', {path, text, version: tab.version}).then(result => {
      tab.saved = text; tab.version = result.version; renderTabs(); message('已保存 ' + path);
    }).finally(() => { tab.saving = null; });
    await tab.saving;
  }
  function projectDialog(create) {
    if (!state) return message('编辑器正在加载，请稍候');
    creatingProject = create;
    $('studioProjectTitle').textContent = create ? '新建 Python 项目' : '打开项目';
    $('studioProjectPath').value = create ? state.defaultParent.replaceAll('\\', '/') + '/我的自动化项目' : state.root || '';
    $('studioProjectHint').textContent = create ? '创建新的目录和 main.py，不会覆盖已有目录。' : '打开包含 Python 脚本的本机目录。';
    $('studioProjectError').textContent = '';
    $('studioProjectDialog').showModal(); $('studioProjectPath').focus();
  }
  async function chooseProject(event) {
    event.preventDefault();
    if (opening) return;
    if ([...tabs.values()].some(dirty) && !window.confirm('当前有未保存的更改。确认放弃这些更改并切换项目？')) return;
    opening = true;
    try {
      const next = await api('open', {path: $('studioProjectPath').value.trim(), create: creatingProject});
      for (const tab of tabs.values()) tab.model.dispose(); tabs.clear(); active = null;
      state = next; activate(null);
      $('studioProjectName').textContent = state.name; $('studioProjectName').title = state.root;
      $('studioProjectDialog').close(); await tree();
      const listing = await api('tree');
      if (listing.items.some(item => item.path === 'main.py')) await openFile('main.py');
      message('项目：' + state.root);
    } catch (error) { $('studioProjectError').textContent = error.message; }
    finally { opening = false; }
  }
  async function createFile(event) {
    event.preventDefault();
    try {
      const path = $('studioFilePath').value.trim().replaceAll('\\', '/');
      await api('write', {path, text: '', create: true});
      $('studioFileDialog').close(); await tree(); await openFile(path);
    } catch (error) { $('studioFileError').textContent = error.message; }
  }
  function renderRun(result) {
    const wasRunning = running;
    running = result.running;
    if (wasRunning && !running) message(result.stopped ? '脚本已停止' : '运行结束 · 退出码 ' + result.exitCode);
    $('studioRun').disabled = running || startingRun || !active || !active.endsWith('.py');
    $('studioStop').disabled = !running;
    $('studioRunStatus').textContent = running ? result.path + ' · 运行中' : !result.runId ? '就绪' :
      result.stopped ? result.path + ' · 已停止' : result.path + ' · 退出码 ' + result.exitCode;
    let log = result.log;
    if (clearedRun === result.runId && log.startsWith(clearedPrefix)) log = log.slice(clearedPrefix.length);
    const output = $('studioLog');
    const nearEnd = output.scrollHeight - output.scrollTop - output.clientHeight < 40;
    if (output.textContent !== log) { output.textContent = log || (running ? '正在启动 Python…' : ''); if (nearEnd) output.scrollTop = output.scrollHeight; }
  }
  async function poll() {
    if (!state || polling) return;
    polling = true;
    try { renderRun(await api('status')); }
    catch (error) { message(error.message, true); }
    finally { polling = false; }
  }
  async function run() {
    if (!active || !active.endsWith('.py') || running || startingRun) return;
    const path = active, project = state.project;
    startingRun = true;
    $('studioRun').disabled = true;
    try {
      // 运行前保存所有已打开模块，避免 import 读到旧版本。
      for (const path of tabs.keys()) await save(path);
      if (project !== state.project) throw new Error('项目已切换，运行已取消');
      const result = await api('run', {path, project});
      clearedRun = ''; clearedPrefix = ''; renderRun(result); message('正在运行 ' + result.path);
    } finally {
      startingRun = false;
      $('studioRun').disabled = running || !active || !active.endsWith('.py');
    }
  }
  function insert(text) {
    if (!active) return message('先打开或新建一个 Python 文件，再插入代码', true);
    if (!active.endsWith('.py')) return message('请选择 Python 文件插入自动化代码', true);
    editor.focus(); editor.getContribution('snippetController2').insert(text);
    message('代码已插入 ' + active + ' · Ctrl+S 保存');
  }
  const py = value => JSON.stringify(String(value));
  function insertLocator(record) {
    const current = record || window.XPSWorkbench?.getCurrent();
    if (!current?.xpath) return message('请先抓取元素或选择元素库中的记录', true);
    const saved = record?.id && record?.name;
    const code = 'from wbot import web' + (saved ? ', selector' : '') + '\n\n' +
      (saved ? 'elements = selector.SelectorStore()\n' : '') +
      'browser = web.get(base_url=' + py(location.origin) + ')\n' +
      'element = browser.find(' + (saved ? 'elements.get(' + py(record.name) + ', group=' + py(record.group || '默认') + ')' : py(current.xpath)) +
      ')\n# print(element.get_text())\n';
    if (!active || !active.endsWith('.py')) return message('请选择 Python 文件插入定位器', true);
    const model = editor.getModel(), position = editor.getPosition();
    const line = model.getLineContent(position.lineNumber);
    const indent = line.match(/^\s*/)[0] + (line.trimEnd().endsWith(':') ? '    ' : '');
    const startColumn = line.trim() ? model.getLineMaxColumn(position.lineNumber) : 1;
    const text = (line.trim() ? '\n' : '') + code.trimEnd().split('\n').map(value => indent + value).join('\n') + '\n';
    editor.pushUndoStop();
    editor.executeEdits('wbot-locator', [{range: new monaco.Range(position.lineNumber, startColumn,
      position.lineNumber, model.getLineMaxColumn(position.lineNumber)), text, forceMoveMarkers: true}]);
    editor.pushUndoStop(); editor.focus();
    message('定位器代码已插入 ' + active + ' · Ctrl+S 保存');
  }
  window.WBotStudio = {insertLocator, hasDirty: () => [...tabs.values()].some(dirty)};
  $('studioInsert').onclick = () => insertLocator();
  $('studioSave').onclick = handle(() => save());
  $('studioRun').onclick = handle(run);
  $('studioStop').onclick = handle(async () => renderRun(await api('stop')));
  $('studioOpen').onclick = $('studioWelcomeOpen').onclick = () => projectDialog(false);
  $('studioCreate').onclick = () => projectDialog(true);
  $('studioProjectForm').onsubmit = chooseProject;
  $('studioProjectCancel').onclick = () => $('studioProjectDialog').close();
  $('studioBrowse').onclick = handle(async () => {
    if (!window.pywebview?.api?.choose_folder) return message('浏览器模式下请直接填写本机目录完整路径');
    const value = await window.pywebview.api.choose_folder();
    if (value) $('studioProjectPath').value = value;
  });
  $('studioFileForm').onsubmit = createFile;
  $('studioFileCancel').onclick = () => $('studioFileDialog').close();
  $('studioNewFile').onclick = () => {
    if (!state?.root) return projectDialog(true);
    $('studioFileError').textContent = ''; $('studioFilePath').value = 'script.py';
    $('studioFileDialog').showModal(); $('studioFilePath').select();
  };
  $('studioRefresh').onclick = handle(async () => { if (state?.root) await tree(); });
  $('studioClearLog').onclick = handle(async () => {
    const result = await api('status'); clearedRun = result.runId; clearedPrefix = result.log; $('studioLog').textContent = '';
  });
  document.querySelectorAll('[data-studio-view]').forEach(button => button.onclick = () => {
    document.querySelectorAll('[data-studio-view]').forEach(item => item.classList.toggle('active', item === button));
    $('studioFiles').hidden = button.dataset.studioView !== 'files';
    $('elementLibrary').hidden = button.dataset.studioView !== 'elements';
    $('studioApi').hidden = button.dataset.studioView !== 'api';
  });
  $('studioLocatorToggle').onclick = () => {
    $('studioShell').classList.toggle('locator-hidden');
    $('studioShell').classList.toggle('locator-mobile-open');
  };
  const snippets = {log: 'print(${1:"运行日志"})\n', sleep: 'from time import sleep\nsleep(${1:1})\n',
    browser: 'from wbot import web\nbrowser = web.get(base_url=' + py(location.origin) + ')\n',
    element: 'element = browser.find(${1:"//button"})\n', text: 'print(element.get_text())\n', click: 'element.click()\n'};
  document.querySelectorAll('[data-code]').forEach(button => button.onclick = () => insert(snippets[button.dataset.code]));
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); handle(() => save())(); }
    if (event.key === 'F5') { event.preventDefault(); handle(run)(); }
  }, true);
  window.addEventListener('beforeunload', event => {
    if ([...tabs.values()].some(dirty)) { event.preventDefault(); event.returnValue = ''; }
  });
  $('studioConsoleResize').onpointerdown = event => {
    const start = event.clientY, height = $('studioConsole').clientHeight;
    event.target.setPointerCapture(event.pointerId);
    event.target.onpointermove = move => {
      $('studioConsole').style.height = Math.max(80, Math.min(height + start - move.clientY, $('studioConsole').parentElement.clientHeight - 180)) + 'px';
    };
    event.target.onpointerup = () => { event.target.onpointermove = null; };
  };

  async function boot() {
    const response = await fetch('/api/studio/state'); state = await response.json();
    if (!response.ok || !state.ok) throw new Error(state.error || '无法连接编码服务');
    await new Promise((resolve, reject) => {
      window.require.config({paths: {vs: 'vendor/monaco/vs'}});
      window.require(['vs/editor/editor.main'], resolve, reject);
    });
    editor = monaco.editor.create($('studioEditor'), {model: null, theme: document.documentElement.dataset.theme === 'dark' ? 'vs-dark' : 'vs',
      automaticLayout: true, fontFamily: "Consolas, 'Microsoft YaHei UI', monospace", fontSize: 13,
      lineHeight: 21, minimap: {enabled: true}, scrollBeyondLastLine: false, tabSize: 4,
      insertSpaces: true, padding: {top: 12}, renderWhitespace: 'selection'});
    editor.onDidChangeCursorPosition(event => { $('studioPosition').textContent = `行 ${event.position.lineNumber}, 列 ${event.position.column}　 UTF-8　Python`; });
    new MutationObserver(() => monaco.editor.setTheme(document.documentElement.dataset.theme === 'dark' ? 'vs-dark' : 'vs'))
      .observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});
    monaco.languages.registerCompletionItemProvider('python', {provideCompletionItems: (model, position) => {
      const word = model.getWordUntilPosition(position);
      const range = {startLineNumber: position.lineNumber, endLineNumber: position.lineNumber, startColumn: word.startColumn, endColumn: word.endColumn};
      const suggestions = Object.entries(snippets).map(([label, code]) => ({label: 'wbot_' + label, detail: 'WBot 自动化片段',
        kind: monaco.languages.CompletionItemKind.Snippet, insertText: code.replaceAll('\\$', '$'),
        insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, range}));
      for (const label of ['print', 'len', 'range', 'enumerate', 'str', 'int', 'list', 'dict', 'def', 'class',
        'import', 'from', 'return', 'if', 'else', 'for', 'while', 'try', 'except', 'with', 'True', 'False', 'None']) {
        suggestions.push({label, insertText: label, kind: monaco.languages.CompletionItemKind.Keyword, range});
      }
      return {suggestions};
    }});
    $('studioProjectName').textContent = state.name; $('studioProjectName').title = state.root;
    await poll();
    if (state.root) { await tree(); const result = await api('tree'); if (result.items.some(item => item.path === 'main.py')) await openFile('main.py'); }
    else $('studioTree').innerHTML = '<p class="tree-empty">打开项目目录后，在这里管理 Python 文件。</p>';
    message(state.python + ' · Ctrl+S 保存 · F5 运行');
    setInterval(() => { if (running) poll(); }, 500);
  }
  boot().catch(error => message('编辑器启动失败：' + error.message, true));
})();
