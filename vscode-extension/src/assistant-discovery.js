"use strict";
const fs = require('node:fs/promises');
const path = require('node:path');
const {execFile} = require('node:child_process');
const {promisify} = require('node:util');
const {assistantStateDir, readSession} = require('./assistant-client');
const {send} = require('./publish-client');

function parseAssistantProcesses(rows) {
  return (Array.isArray(rows) ? rows : [rows]).flatMap(row => {
    if (!Number.isInteger(row?.ProcessId) || !/\s-m\s+app\.assistant\s+serve(?:\s|$)/.test(row.CommandLine || '')) return [];
    const match = row.CommandLine.match(/(?:^|\s)--state-dir(?:=|\s+)(?:"([^"]+)"|(\S+))/);
    if (!match) return [];
    return [{pid:row.ProcessId, directory:match[1] || match[2]}];
  });
}
async function assistantProcesses() {
  if (process.platform !== 'win32') return [];
  const command = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); @(Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" | Where-Object { $_.CommandLine -match '\\s-m\\s+app\\.assistant\\s+serve(?:\\s|$)' } | Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress";
  const {stdout} = await promisify(execFile)('powershell.exe', ['-NoProfile','-NonInteractive','-Command',command], {windowsHide:true,timeout:6000,maxBuffer:128*1024,encoding:'utf8'});
  return parseAssistantProcesses(JSON.parse(stdout.trim() || '[]'));
}
function processAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try { process.kill(pid,0); return true; } catch (error) { return error.code === 'EPERM'; }
}
async function discoverAssistants({directories=[assistantStateDir()], processes, isAlive=processAlive} = {}) {
  // A custom state directory is learned from an actual Assistant process, never by port scanning.
  processes ??= await assistantProcesses().catch(() => []);
  const candidates = new Map();
  for (const directory of directories.filter(Boolean)) {
    try { candidates.set(assistantStateDir(directory), new Set()); } catch { /* Ignore obsolete preferences. */ }
  }
  for (const process of processes) {
    try { const directory=assistantStateDir(process.directory);
      if(!candidates.has(directory))candidates.set(directory,new Set());
      candidates.get(directory).add(process.pid); } catch { /* Ignore invalid process arguments. */ }
  }
  const results = await Promise.all([...candidates].map(async ([directory, expectedPids]) => {
    try {
      const session = await readSession(directory);
      const metadata = JSON.parse(await fs.readFile(path.join(directory,'service.json'),'utf8'));
      if (!isAlive(metadata.pid) || expectedPids.size > 0 && !expectedPids.has(metadata.pid)) return null;
      const {payload} = await send(session.url,'/api/health',{headers:{'X-WBot-Token':session.token},timeout:1800});
      if (payload?.product !== 'wbot-assistant') return null;
      return {directory,pid:metadata.pid,version:String(payload.version || ''),url:session.url};
    } catch { return null; }
  }));
  return results.filter(Boolean);
}
module.exports = {parseAssistantProcesses, discoverAssistants};
