'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const http=require('node:http');
const {ocOrigin,publishAssistant,publishOC,send}=require('../src/publish-client');

test('OC 地址限制凭据传输；拒绝远端明文、内嵌认证和路径',()=>{
 assert.equal(ocOrigin('https://oc.example'),'https://oc.example');
 for(const value of ['http://192.168.1.1','https://user:password@oc.example','https://oc.example/path','file:///tmp'])assert.throws(()=>ocOrigin(value));
});
test('发布只使用正确目标的凭据，收到对应版本回执后完成，并退出 OC 会话',async t=>{
 const directory=await fs.mkdtemp(path.join(os.tmpdir(),'wbot-publish-'));t.after(()=>fs.rm(directory,{recursive:true,force:true}));
 const manifest={name:'demo',version:'1.0.0'};const archive=path.join(directory,'demo.wbot.zip');await fs.writeFile(archive,'archive');
 let logout=false,uploads=0;
 const server=http.createServer((req,res)=>{
  const chunks=[];req.on('data',chunk=>chunks.push(chunk));req.on('end',()=>{
   const content=Buffer.concat(chunks);res.setHeader('Content-Type','application/json');
   if(req.url==='/api/v1/system/auth/login'){
    assert.equal(JSON.parse(content).username,'developer');assert.equal(req.headers['x-wbot-token'],undefined);
    res.setHeader('Set-Cookie','wbot_session=test-session; HttpOnly');return res.end(JSON.stringify({data:{token:'csrf',permissions:['packages.manage'],user:{must_change_password:false}}}));
   }
   if(req.url==='/api/v1/system/auth/logout'){logout=true;assert.equal(req.headers.cookie,'wbot_session=test-session');return res.end('{"data":{}}');}
   if(req.url==='/api/v1/oc/packages'){
    uploads++;assert.equal(req.headers['x-wbot-token'],'csrf');assert.equal(content.toString(),'archive');assert.equal(req.headers['content-type'],'application/octet-stream');return res.end(JSON.stringify({data:{package:{id:'package',manifest}}}));
   }
   if(req.url==='/api/packages'){
    assert.equal(req.headers['x-wbot-token'],'local-only');assert.equal(req.headers.cookie,undefined);assert.equal(JSON.parse(content).path,archive);return res.end(JSON.stringify({package:{id:'local',manifest}}));
   }
   res.writeHead(302,{Location:'https://example.com'});res.end();
  });
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>{server.closeAllConnections();server.close();});
 const origin=`http://127.0.0.1:${server.address().port}`;
 await fs.writeFile(path.join(directory,'service.json'),JSON.stringify({url:origin,token:'local-only'}));
 const built={path:archive,manifest};
 assert.equal((await publishOC(origin,{username:'developer',password:'test-password'},built)).id,'package');assert.equal(logout,true);assert.equal(uploads,1);
 assert.equal((await publishAssistant(directory,built)).id,'local');
 await assert.rejects(send(origin,'/redirect'),/重定向/);
 await assert.rejects(publishAssistant(directory,{...built,manifest:{...manifest,version:'2.0.0'}}),/不匹配/);
});
test('真实 Assistant 接收发布，重复版本回执一致且不会自动运行',async t=>{
 const {startSharedFixture}=require('./shared-fixture');
 const {runProjectCommand}=require('../src/project');
 const fixture=await startSharedFixture();t.after(()=>fixture.close());
 const directory=await fs.mkdtemp(path.join(os.tmpdir(),'wbot-publish-real-'));t.after(()=>fs.rm(directory,{recursive:true,force:true}));
 const project=path.join(directory,'project');const options={python:process.env.WBOT_TEST_PYTHON||'python',runtime:path.resolve(__dirname,'../..'),project};
 await runProjectCommand({...options,action:'init',name:'publish-real'});
 const built=await runProjectCommand({...options,action:'build'});
 const first=await publishAssistant(fixture.assistant_dir,built);
 const again=await publishAssistant(fixture.assistant_dir,built);
 assert.equal(first.id,again.id);
 const {readSession}=require('../src/assistant-client');const {url,token}=await readSession(fixture.assistant_dir);
 const jobs=await send(url,'/api/jobs',{headers:{'X-WBot-Token':token}});
 assert.deepEqual(jobs.payload.items,[]);
});
