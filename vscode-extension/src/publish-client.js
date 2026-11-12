'use strict';
const http = require('node:http');
const https = require('node:https');
const fs = require('node:fs/promises');
const {readSession} = require('./assistant-client');

function ocOrigin(value) {
  let url; try { url = new URL(value); } catch { throw new Error('OC 地址无效'); }
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/' ||
      !(url.protocol === 'https:' || url.protocol === 'http:' && url.hostname === '127.0.0.1')) {
    throw new Error('OC 地址须为 HTTPS 站点地址；本机测试可使用 http://127.0.0.1:端口');
  }
  return url.origin;
}
function send(origin, endpoint, {method='GET',headers={},body,timeout=90000} = {}) {
  const content = body === undefined ? undefined : Buffer.isBuffer(body) ? body : Buffer.from(JSON.stringify(body));
  if (content?.length > 64*1024*1024) throw new Error('发布包超过 64 MiB');
  const url = new URL(endpoint,origin);
  return new Promise((resolve,reject)=>{
    const request = (url.protocol==='https:'?https:http).request(url,{method,headers:{...headers,...(content?{'Content-Length':content.length}: {})}},response=>{
      if(response.statusCode>=300 && response.statusCode<400){response.resume();reject(new Error('发布服务返回重定向，未转发登录凭据或发布包'));return;}
      let size=0;const chunks=[];
      response.on('data',chunk=>{size+=chunk.length;if(size>2*1024*1024)request.destroy(new Error('发布回执超过限制'));else chunks.push(chunk);});
      response.on('error',reject);
      response.on('end',()=>{
        let payload;try{payload=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{reject(new Error(`发布服务返回无效回执（HTTP ${response.statusCode}）`));return;}
        if(response.statusCode<200 || response.statusCode>=300){reject(new Error(payload?.error?.message || payload?.error || `发布失败（HTTP ${response.statusCode}）`));return;}
        resolve({payload,headers:response.headers});
      });
    });
    const timer=setTimeout(()=>request.destroy(new Error('发布响应超时；结果未确认，请在目标包列表核对后再发布同一版本')),timeout);
    request.once('close',()=>clearTimeout(timer));request.on('error',reject);request.end(content);
  });
}
function receipt(payload,manifest) {
  const installed=payload?.package;
  if(typeof installed?.id!=='string' || installed.manifest?.name!==manifest.name || installed.manifest?.version!==manifest.version)throw new Error('发布回执与包版本不匹配，请到目标端核对');
  return installed;
}
async function publishAssistant(directory,built) {
  const {url,token}=await readSession(directory);
  const response=await send(url,'/api/packages',{method:'POST',headers:{'X-WBot-Token':token,'Content-Type':'application/json'},body:{path:built.path}});
  return receipt(response.payload,built.manifest);
}
async function publishOC(origin,credentials,built) {
  origin=ocOrigin(origin);
  const stat=await fs.stat(built.path);if(!stat.isFile() || stat.size>64*1024*1024)throw new Error('发布包无效或超过 64 MiB');
  const bytes=await fs.readFile(built.path);
  const login=await send(origin,'/api/v1/system/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:credentials,timeout:15000});
  const session=login.payload?.data;
  const cookie=login.headers['set-cookie']?.find(item=>item.startsWith('wbot_session='))?.split(';')[0];
  if(!cookie || typeof session?.token!=='string')throw new Error('OC 登录回执无效，请更新 OC');
  const headers={'Cookie':cookie,'X-WBot-Token':session.token};
  try {
    if(session.user?.must_change_password)throw new Error('请先在 OC 网页修改初始密码，再发布');
    if(!session.permissions?.includes('packages.manage'))throw new Error('当前 OC 账号没有上传自动化包的权限');
    const response=await send(origin,'/api/v1/oc/packages',{method:'POST',headers:{...headers,'Content-Type':'application/octet-stream'},body:bytes});
    return receipt(response.payload?.data,built.manifest);
  } finally {
    await send(origin,'/api/v1/system/auth/logout',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:{},timeout:5000}).catch(()=>{});
  }
}
module.exports={ocOrigin,send,receipt,publishAssistant,publishOC};
