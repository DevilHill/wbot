'use strict';
const http = require('node:http');
const {readSession} = require('./assistant-client');

async function requestBrowser(directory, endpoint, body) {
  const {url,token} = await readSession(directory);
  const content = endpoint === undefined ? undefined : Buffer.from(JSON.stringify({path:endpoint,...(body === undefined ? {} : {body})}));
  if(content?.length > 2*1024*1024)throw new Error('元素请求超过 2 MiB');
  return new Promise((resolve,reject)=>{
    const request=http.request(url+'/api/browser',{method:content?'POST':'GET',headers:{'X-WBot-Token':token,...(content?{'Content-Type':'application/json','Content-Length':content.length}:{})}},response=>{
      const chunks=[];let size=0;
      response.on('data',chunk=>{size+=chunk.length;if(size>8*1024*1024)request.destroy(new Error('元素响应超过 8 MiB'));else chunks.push(chunk);});
      response.on('error',reject);
      response.on('end',()=>{
        if(response.statusCode===404){reject(new Error('当前 Assistant 不支持元素服务，请升级到 0.9.0 或更新版本并重启 Assistant'));return;}
        if(response.statusCode>=300 && response.statusCode<400){reject(new Error('Assistant 返回重定向，未转发本机会话'));return;}
        let result;try{result=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{reject(new Error('Assistant 元素服务返回无效响应'));return;}
        if(response.statusCode>=400 || result?.ok===false){reject(new Error(result?.error || 'Assistant 元素服务请求失败'));return;}
        resolve(result);
      });
    });
    const timer=setTimeout(()=>request.destroy(new Error('Assistant 元素操作超时，请检查结果后再重试')),15000);
    request.once('close',()=>clearTimeout(timer));
    request.on('error',error=>reject(new Error('无法访问 Assistant 元素服务：'+error.message)));
    request.end(content);
  });
}
module.exports={requestBrowser};
