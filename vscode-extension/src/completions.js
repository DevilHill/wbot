'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
function completionContext(source,line) {
  const stores=new Set([...source.matchAll(/\b([A-Za-z_]\w*)\s*=\s*(?:[A-Za-z_]\w*\.)?SelectorStore\s*\(/g)].map(match=>match[1]));
  const match=line.match(/\b([A-Za-z_]\w*)\.get\(\s*(?:(['"])([^'"\n]*)|['"][^'"\n]*['"]\s*,\s*group\s*=\s*(['"])([^'"\n]*))$/);
  if(!match || !stores.has(match[1]))return null;
  return {field:match[4]?'group':'name',prefix:match[5]??match[3],quote:match[4]??match[2]};
}
async function projectElements(directory) {
  let manifest;try{const file=path.join(directory,'wbot.json');if((await fs.stat(file)).size>262144)return [];manifest=JSON.parse(await fs.readFile(file,'utf8'));}catch(error){if(error.code==='ENOENT' || error instanceof SyntaxError)return [];throw error;}
  if(typeof manifest.elements!=='string')return [];
  const root=await fs.realpath(directory),candidate=path.resolve(directory,manifest.elements);
  const relative=path.relative(root,candidate);if(relative.startsWith('..') || path.isAbsolute(relative))return [];
  let real;try{real=await fs.realpath(candidate);}catch(error){if(error.code==='ENOENT')return [];throw error;}
  const realRelative=path.relative(root,real);if(realRelative.startsWith('..') || path.isAbsolute(realRelative) || (await fs.stat(real)).size>2*1024*1024)return [];
  const data=JSON.parse(await fs.readFile(real,'utf8'));return data.format==='wbot-elements' && Array.isArray(data.items)?data.items:[];
}
function registerCompletions(vscode,context,getRecords) {
  context.subscriptions.push(vscode.languages.registerCompletionItemProvider({language:'python',scheme:'file'},{
    async provideCompletionItems(document,position,token) {
      if(!vscode.workspace.isTrusted)return [];
      const line=document.lineAt(position.line).text.slice(0,position.character);
      const match=completionContext(document.getText(),line);if(!match)return [];
      const folder=vscode.workspace.getWorkspaceFolder(document.uri);
      let records=folder?await projectElements(folder.uri.fsPath):[];
      if(!records.length)records=getRecords();
      if(token.isCancellationRequested)return [];
      const seen=new Set();return records.flatMap(record=>{
        const label=record[match.field];if(typeof label!=='string' || seen.has(label) || !label.startsWith(match.prefix))return [];seen.add(label);
        const item=new vscode.CompletionItem(label,vscode.CompletionItemKind.Value);
        item.insertText=label.replace(/\\/g,'\\\\').replaceAll(match.quote,'\\'+match.quote);
        item.range=new vscode.Range(position.line,position.character-match.prefix.length,position.line,position.character);
        item.detail=match.field==='name'?`${record.group} · ${record.xpath}`:'WBot 元素分组';
        item.documentation=new vscode.MarkdownString();item.documentation.appendText(record.description || record.xpath || '项目元素库');return [item];
      });
    }
  },'"',"'"));
}
module.exports={completionContext,projectElements,registerCompletions};
