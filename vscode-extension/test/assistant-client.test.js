'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {assistantStateDir, requestAssistant} = require('../src/assistant-client');

async function fixture(t, handler) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'wbot-assistant-client-'));
  const server = http.createServer(handler);
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  await fs.writeFile(path.join(directory, 'service.json'), JSON.stringify({url, token:'test-session-token'}));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    await fs.rm(directory, {recursive:true, force:true});
  });
  return {directory, url};
}

test('Assistant 地址只从本机数据目录读取，每次请求重新读取会话', async t => {
  const requests = [];
  const {directory, url} = await fixture(t, (req, res) => {
    let content = '';
    req.on('data', chunk => { content += chunk; });
    req.on('end', () => {
      requests.push({method:req.method, path:req.url, token:req.headers['x-wbot-token'], body:JSON.parse(content)});
      res.writeHead(200, {'Content-Type':'application/json'});
      res.end(JSON.stringify({repositories:[{id:'repo1', name:'共享页面'}]}));
    });
  });
  const body = {library_path:path.resolve('elements.sqlite3')};
  assert.equal((await requestAssistant(directory, 'repositories', body)).repositories[0].id, 'repo1');
  await fs.writeFile(path.join(directory, 'service.json'), JSON.stringify({url, token:'renewed-session-token'}));
  await requestAssistant(directory, 'status', body);
  assert.deepEqual(requests.map(item => item.token), ['test-session-token', 'renewed-session-token']);
  assert.equal(requests[0].method, 'POST');
  assert.equal(requests[0].path, '/api/shared-elements/repositories');
  assert.deepEqual(requests[0].body, body);
});

test('拒绝远程元数据、接口逃逸和相对数据目录', async t => {
  let called = false;
  const {directory} = await fixture(t, (_req, res) => { called = true; res.end('{}'); });
  await assert.rejects(requestAssistant(directory, '../settings', {}), /接口/);
  await fs.writeFile(path.join(directory, 'service.json'), JSON.stringify({url:'http://example.com:8791', token:'secret'}));
  await assert.rejects(requestAssistant(directory, 'status', {}), /127\.0\.0\.1/);
  assert.equal(called, false);
  assert.throws(() => assistantStateDir('relative'), /绝对路径/);
  assert.equal(assistantStateDir(''), path.join(os.homedir(), '.wbot-assistant'));
});

test('重定向不会转发本机会话，服务错误保留清晰提示', async t => {
  let forwarded = false;
  const target = await fixture(t, (_req, res) => { forwarded = true; res.end('{}'); });
  const source = await fixture(t, (req, res) => {
    if (req.url.endsWith('/status')) {
      res.writeHead(302, {Location:target.url}); res.end();
    } else {
      res.writeHead(409, {'Content-Type':'application/json'});
      res.end(JSON.stringify({error:'本地有未提交的元素修改'}));
    }
  });
  await assert.rejects(requestAssistant(source.directory, 'status', {}), /重定向/);
  assert.equal(forwarded, false);
  await assert.rejects(requestAssistant(source.directory, 'pull', {}), /未提交/);
});

test('旧后台和无效 JSON 的诊断能指向升级或连接配置', async t => {
  const {directory} = await fixture(t, (req, res) => {
    if (req.url.endsWith('/status')) { res.writeHead(404); res.end('{}'); }
    else { res.writeHead(200); res.end('<html>invalid</html>'); }
  });
  await assert.rejects(requestAssistant(directory, 'status', {}), /更新.*Assistant/);
  await assert.rejects(requestAssistant(directory, 'repositories', {}), /JSON/);
});
