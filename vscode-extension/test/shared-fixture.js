'use strict';
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const {once} = require('node:events');
const {spawn} = require('node:child_process');

async function startSharedFixture() {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'wbot-shared-client-'));
  const child = spawn(process.env.WBOT_TEST_PYTHON || 'python',
    ['-X', 'utf8', path.join(__dirname, 'shared_elements_fixture.py'), directory],
    {windowsHide:true, stdio:['pipe', 'pipe', 'pipe']});
  let errors = '';
  child.stderr.on('data', chunk => { errors += chunk.toString(); });
  child.on('error', error => { errors += error.message; });
  const lines = readline.createInterface({input:child.stdout})[Symbol.asyncIterator]();
  async function receive() {
    const {value, done} = await lines.next();
    if (done) throw new Error('共享元素测试服务已退出：' + errors);
    return JSON.parse(value);
  }
  async function close() {
    if (child.exitCode === null && child.pid) {
      const closed = once(child, 'close');
      child.stdin.end(JSON.stringify({action:'stop'}) + '\n');
      const timer = setTimeout(() => child.kill(), 5000);
      await closed;
      clearTimeout(timer);
    }
    await fs.rm(directory, {recursive:true, force:true});
  }
  const startupTimer = setTimeout(() => child.kill(), 10000);
  let metadata;
  try { metadata = await receive(); }
  catch (error) { await close(); throw error; }
  finally { clearTimeout(startupTimer); }
  return {...metadata, close, async command(action, values = {}) {
    child.stdin.write(JSON.stringify({action, ...values}) + '\n');
    return (await receive()).result;
  }};
}

module.exports = {startSharedFixture};
