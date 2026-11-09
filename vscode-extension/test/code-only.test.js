'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const core = require('../src/core');

test('编码版入口只提供 Python 脚本及元素辅助工具', () => {
  const manifest = require('../package.json');
  const commands = manifest.contributes.commands.map(item => item.command);
  for (const name of ['newScript','runFile','debugFile','insertElement','pick']) assert.ok(commands.includes('wbot.'+name));
  for (const name of ['sharedElements','connectSharedElements','sharedElementChanges','commitSharedElements',
                     'requestElementMerge','sharedElementStatus','pullSharedElements']) assert.ok(commands.includes('wbot.'+name));
  for (const name of ['newFlow','openWorkbench']) assert.ok(!commands.includes('wbot.'+name));
  assert.ok(!manifest.contributes.customEditors?.length);
  assert.ok(!manifest.activationEvents.some(event => event.startsWith('onCustomEditor:')));
  const welcome = manifest.contributes.viewsWelcome.map(view => view.contents).join('\n');
  assert.ok(welcome.includes('command:wbot.newScript'));
  assert.ok(!welcome.includes('command:wbot.newFlow'));
});

test('新建 Python 模板和编码示例无需浏览器即可实际执行', () => {
  const cfg = {baseUrl:'http://127.0.0.1:1',libraryPath:path.resolve('not-created.sqlite3')};
  const template = core.scriptTemplate(cfg);
  const example = fs.readFileSync(path.join(__dirname,'../examples/code-demo.py'),'utf8');
  const python = process.env.WBOT_TEST_PYTHON || 'python';
  for (const [name,code] of [['template',template],['example',example]]) {
    const result = spawnSync(python,['-I','-X','utf8','-c',code],
      {encoding:'utf8',windowsHide:true,timeout:10000,maxBuffer:1024*1024});
    assert.equal(result.status,0,`${name}: ${result.stdout}${result.stderr}${result.error || ''}`);
    assert.match(result.stdout+result.stderr,/您好，WBot/);
  }
});
