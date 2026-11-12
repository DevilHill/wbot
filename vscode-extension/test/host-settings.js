"use strict";
const fs=require('node:fs/promises');
const path=require('node:path');
async function configureLegacy(vscode,values) {
 const filename=process.env.WBOT_TEST_SETTINGS_FILE;
 const root=path.resolve(__dirname,'../../build/vscode-tests');
 if(!filename || path.relative(root,path.resolve(filename)).startsWith('..') || path.isAbsolute(path.relative(root,path.resolve(filename))))throw new Error('Host settings must stay in the isolated test directory');
 await fs.mkdir(path.dirname(filename),{recursive:true});
 let settings;try{settings=JSON.parse(await fs.readFile(filename,'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;settings={};}
 for(const [key,value] of Object.entries(values)){if(value===undefined)delete settings['wbot.'+key];else settings['wbot.'+key]=value;}
 await fs.writeFile(filename,JSON.stringify(settings,null,2));
 const deadline=Date.now()+10000;
 while(Date.now()<deadline){const cfg=vscode.workspace.getConfiguration('wbot');if(Object.entries(values).every(([key,value])=>cfg.get(key)===value))return;await new Promise(resolve=>setTimeout(resolve,50));}
 throw new Error('Isolated legacy configuration was not reloaded');
}
module.exports={configureLegacy};
