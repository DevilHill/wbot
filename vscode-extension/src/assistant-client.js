'use strict';
const fs = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {bridgeUrl} = require('./core');

function assistantStateDir(value) {
  if (!value) return path.join(os.homedir(), '.wbot-assistant');
  if (typeof value !== 'string') throw new Error('wbot.assistantStateDir 必须为绝对路径');
  if (value.startsWith('~/') || value.startsWith('~\\')) value = path.join(os.homedir(), value.slice(2));
  if (!path.isAbsolute(value)) throw new Error('wbot.assistantStateDir 必须为绝对路径');
  return value;
}

async function readSession(directory) {
  const filename = path.join(assistantStateDir(directory), 'service.json');
  let metadata;
  try {
    if ((await fs.stat(filename)).size > 16384) throw new Error('Assistant 服务记录过大');
    metadata = JSON.parse(await fs.readFile(filename, 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') throw new Error('未找到 Assistant 后台；请先启动，并确认 wbot.assistantStateDir 指向其数据目录');
    throw new Error('无法读取 Assistant 服务记录：' + error.message);
  }
  if (!metadata || typeof metadata !== 'object') throw new Error('Assistant 服务记录格式无效');
  const url = bridgeUrl(metadata.url);
  if (!new URL(url).port) throw new Error('Assistant 服务记录缺少本机端口');
  if (typeof metadata.token !== 'string' || !metadata.token || metadata.token.length > 1024 || /[\r\n]/.test(metadata.token)) {
    throw new Error('Assistant 服务记录缺少有效会话');
  }
  return {url, token:metadata.token};
}

async function requestAssistant(directory, action, body = {}, timeout = 30000) {
  if (!/^[a-z][a-z-]*$/.test(action)) throw new Error('共享元素接口无效');
  const {url, token} = await readSession(directory);
  const content = Buffer.from(JSON.stringify(body));
  if (content.length > 2 * 1024 * 1024) throw new Error('共享元素请求超过 2 MiB');
  return new Promise((resolve, reject) => {
    const request = http.request(url + '/api/shared-elements/' + action, {
      method:'POST', headers:{'X-WBot-Token':token, 'Content-Type':'application/json', 'Content-Length':content.length}
    }, response => {
      if (response.statusCode >= 300 && response.statusCode < 400) {
        response.resume(); reject(new Error('Assistant 返回重定向，未转发本机会话；请检查数据目录')); return;
      }
      let size = 0;
      const chunks = [];
      response.on('data', chunk => {
        size += chunk.length;
        if (size > 8 * 1024 * 1024) request.destroy(new Error('共享元素响应超过 8 MiB'));
        else chunks.push(chunk);
      });
      response.on('error', reject);
      response.on('end', () => {
        if (response.statusCode === 404) {
          reject(new Error('共享元素接口不可用，请更新并重启 Assistant 后台，确认数据目录正确')); return;
        }
        let payload;
        try { payload = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
        catch { reject(new Error(`Assistant 返回的不是 JSON（HTTP ${response.statusCode}）`)); return; }
        if (response.statusCode < 200 || response.statusCode >= 300) {
          reject(new Error(payload?.error || `共享元素请求失败（HTTP ${response.statusCode}）`)); return;
        }
        if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
          reject(new Error('Assistant 共享元素响应格式无效')); return;
        }
        resolve(payload);
      });
    });
    const timer = setTimeout(() => request.destroy(new Error('Assistant 请求超时；操作可能已提交，请查看状态后重试')), timeout);
    request.once('close', () => clearTimeout(timer));
    request.on('error', error => reject(new Error(`无法访问本机 Assistant：${error.message}`)));
    request.end(content);
  });
}

module.exports = {assistantStateDir, requestAssistant};
