import { chromium } from '@playwright/test';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const root = path.resolve(import.meta.dirname, '../..');
const smoke = process.argv.includes('--smoke');
const out = path.join(root, 'artifacts');
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'revero-demo-'));
fs.mkdirSync(out, { recursive: true });
const python = path.join(root, 'backend/.venv/bin/python');
const caption = 'For backend interviews, practice SQLite joins. Review one query plan each week.';
const code = 'RVDEMO_live_session';
const steps = [
 ['Save a Reel', 'Revero is a local inbox for ideas worth revisiting. This offline demonstration uses authored sample content and simulated AI and Telegram providers. First, paste an Instagram Reel link. Revero saves a clean link on this computer.'],
 ['Duplicates and invalid links', 'Sharing the same Reel with different tracking parameters returns the original saved record. An unrelated link is rejected, and the input stays available for correction. The original saved Reel remains in the inbox.'],
 ['Read evidence and track an idea', 'Open the saved Reel and add a caption. A durable job moves from queued to ready. Here the provider response is simulated. The takeaway shows its original source excerpt. Choose Track this to turn the suggestion into an action.'],
 ['Confirm a date and finish work', 'Actions keep their supporting evidence. A due date is optional and becomes confirmed only after you choose it. Here we set a date for the new action, then mark a different action done. Completed work leaves the open list.'],
 ['Ask your saved Reels', 'Ask a question about SQLite joins. Full text search retrieves saved excerpts, and each answer points back to its evidence and original Reel. This answer provider is an offline stand in. An unsupported question receives a clear no match reply.'],
 ['Preview and simulate a digest', 'The digest ranks up to three ready Reels for your interests and includes confirmed deadlines independently. Score reasons are visible. This final send is simulated, with no Telegram message leaving the computer. Live model quality and a week of real use remain to be evaluated.'],
];
function run(cmd, args) {
 const result = spawnSync(cmd, args, { cwd: root, encoding: 'utf8' });
 if (result.status !== 0) throw new Error(`${cmd} failed: ${result.stderr?.slice(-1500)}`);
 return result.stdout;
}
async function port() {
 const server = net.createServer();
 await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
 const number = server.address().port;
 await new Promise(resolve => server.close(resolve));
 return number;
}
async function ready(url, process) {
 for (let i=0; i<200; i++) {
  if (process.exitCode !== null) throw new Error('Demo server exited; inspect artifacts/demo-server.log.');
  try { if ((await fetch(url)).ok) return; } catch {}
  await delay(100);
 }
 throw new Error('Demo server startup timed out.');
}
let api, vite, browser, context;
const log = fs.openSync(path.join(out, 'demo-server.log'), 'w');
try {
 const apiPort=await port(), webPort=await port();
 const env={...process.env, PYTHONPATH:path.join(root,'backend'), REVERO_DEMO_DB:path.join(work,'demo.sqlite3'), GEMINI_API_KEY:'', GEMINI_FREE_TIER_CONFIRMED:'false', TELEGRAM_BOT_TOKEN:'', TELEGRAM_CHAT_ID:''};
 api=spawn(python,['-m','uvicorn','evaluation.demo_app:app','--host','127.0.0.1','--port',String(apiPort)],{cwd:root,env,stdio:['ignore',log,log]});
 await ready(`http://127.0.0.1:${apiPort}/api/reels`,api);
 vite=spawn(process.execPath,[path.join(root,'frontend/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',String(webPort),'--strictPort'],{cwd:path.join(root,'frontend'),env:{...env,REVERO_API_TARGET:`http://127.0.0.1:${apiPort}`},stdio:['ignore',log,log]});
 await ready(`http://127.0.0.1:${webPort}`,vite);
 if (!smoke) {
  for(let i=0;i<steps.length;i++) {
   const text=path.join(work,`voice-${i}.txt`), audio=path.join(work,`voice-${i}.aiff`);
   fs.writeFileSync(text,steps[i][1]);
   run('/usr/bin/say',['-v','Samantha','-r','175','-f',text,'-o',audio]);
   const duration=Number(run('ffprobe',['-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',audio]).trim());
   if(duration>19.5) throw new Error(`Narration chapter ${i+1} exceeds its 20-second segment.`);
   run('ffmpeg',['-hide_banner','-loglevel','error','-y','-i',audio,'-af','apad','-t','20','-ar','44100','-ac','1',path.join(work,`voice-${i}.wav`)]);
  }
 }
 browser=await chromium.launch();
 context=await browser.newContext({baseURL:`http://127.0.0.1:${webPort}`,viewport:{width:1280,height:800},...(smoke?{}:{recordVideo:{dir:path.join(work,'video'),size:{width:1280,height:800}}})});
 const page=await context.newPage();
 await page.goto(`http://127.0.0.1:${webPort}`);
 await page.getByRole('navigation',{name:'Workspace'}).waitFor();
 await page.evaluate(()=>{const bar=document.createElement('div');bar.id='demo-disclosure';bar.style.cssText='position:fixed;bottom:0;left:0;right:0;padding:10px 24px;background:#18317c;color:white;font:13px Arial;z-index:10000;pointer-events:none;display:flex;justify-content:space-between';bar.innerHTML='<span id="demo-chapter"></span><span>Offline demo • authored samples • simulated AI + Telegram</span>';document.body.appendChild(bar);});
 const nav=page.getByRole('navigation',{name:'Workspace'});
 let reel;
 async function chapter(index,action) {
  const start=Date.now();
  await page.evaluate(({index,title})=>{document.querySelector('#demo-chapter').textContent=`${index+1}/6  ${title}`;},{index,title:steps[index][0]});
  console.log(`Recording ${index+1}/6: ${steps[index][0]}`);
  await action();
  if(!smoke) {
   const remaining=20000-(Date.now()-start);
   if(remaining<0) throw new Error(`Chapter ${index+1} exceeded its recording slot.`);
   await delay(remaining);
  }
 }
 await chapter(0,async()=>{
  await page.getByLabel('Instagram Reel link').fill(`https://www.instagram.com/reel/${code}/?igsh=demo`);
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.getByText('Saved to your inbox.',{exact:true}).waitFor();
  const rows=await (await page.request.get('/api/reels')).json(); reel=rows.find(row=>row.shortcode===code);
 });
 await chapter(1,async()=>{
  await page.getByLabel('Instagram Reel link').fill(`https://www.instagram.com/reel/${code}/?igsh=another`);
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.getByText('Already saved. This Reel is in your inbox.',{exact:true}).waitFor();
  await delay(smoke?0:1500);
  await page.getByLabel('Instagram Reel link').fill('https://example.com/not-a-reel');
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.locator('.message.error').waitFor();
  await page.getByLabel('Instagram Reel link').fill('');
 });
 await chapter(2,async()=>{
  await page.locator('.saved-list li').filter({hasText:code}).getByRole('button').click();
  await page.getByLabel('Add or replace content').fill(caption);
  await page.getByRole('button',{name:'Attach & queue',exact:true}).click();
  await page.getByText('Queued',{exact:true}).first().waitFor();
  await page.request.post(`http://127.0.0.1:${apiPort}/demo/process/${reel.id}`);
  await page.getByRole('button',{name:'Track this',exact:true}).waitFor();
  await page.getByRole('button',{name:'Track this',exact:true}).click();
  await page.getByRole('button',{name:'Tracked',exact:true}).waitFor();
  await page.locator('.takeaway').scrollIntoViewIfNeeded();
 });
 await chapter(3,async()=>{
  await nav.getByRole('button',{name:'Actions',exact:true}).click();
  const card=page.getByRole('article',{name:caption,exact:true});
  const date=new Date(Date.now()+3*86400000).toLocaleDateString('en-CA',{timeZone:'Asia/Kolkata'});
  await card.getByLabel('Due date (optional)').fill(date);
  await card.getByRole('button',{name:'Confirm date',exact:true}).click();
  await card.getByText(`Confirmed due date: ${date}`,{exact:true}).waitFor();
  const other=page.getByRole('article',{name:'Write a short explanation after each programming exercise.',exact:true});
  await other.getByRole('button',{name:'Done',exact:true}).click();
  await card.scrollIntoViewIfNeeded();
 });
 await chapter(4,async()=>{
  await nav.getByRole('button',{name:'Ask',exact:true}).click();
  await page.getByLabel('Question about your saves').fill('What did I save about SQLite joins?');
  await page.getByRole('button',{name:'Ask Revero',exact:true}).click();
  await page.getByText('Supporting excerpts',{exact:true}).waitFor();
  await delay(smoke?0:3000);
  await page.getByLabel('Question about your saves').fill('What did I save about quantum entanglement research?');
  await page.getByRole('button',{name:'Ask Revero',exact:true}).click();
  await page.getByText('I couldn’t find that in your saves.',{exact:true}).waitFor();
 });
 await chapter(5,async()=>{
  await nav.getByRole('button',{name:'Digest',exact:true}).click();
  await page.locator('.digest-picks li').first().getByText('Why this pick?',{exact:true}).click();
  await delay(smoke?0:2500);
  await page.locator('.digest-deadlines').scrollIntoViewIfNeeded();
  await page.getByRole('button',{name:'Send digest now',exact:true}).click();
  await page.getByText('Delivery status: sent.',{exact:true}).waitFor();
  const deliveries=await (await page.request.get(`http://127.0.0.1:${apiPort}/demo/deliveries`)).json();
  if(deliveries.real_telegram_messages!==0||deliveries.simulated_message_parts<1) throw new Error('Offline delivery check failed.');
 });
 if(smoke) console.log('All six offline demo chapters passed; no real provider calls or messages.');
 else {
  const video=page.video(); await context.close(); context=null;
  const raw=path.join(work,'raw.webm'); await video.saveAs(raw);
  fs.writeFileSync(path.join(work,'audio.txt'),steps.map((_,i)=>`file '${path.join(work,`voice-${i}.wav`)}'`).join('\n'));
  run('ffmpeg',['-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',path.join(work,'audio.txt'),'-c','copy',path.join(work,'narration.wav')]);
  const timestamp=seconds=>`${String(Math.floor(seconds/3600)).padStart(2,'0')}:${String(Math.floor(seconds/60)%60).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')},000`;
  const subtitles=steps.map((step,i)=>`${i+1}\n${timestamp(i*20)} --> ${timestamp((i+1)*20)}\n${step[1]}\n`).join('\n');
  const srt=path.join(out,'revero-demo.srt'); fs.writeFileSync(srt,subtitles);
  run('ffmpeg',['-hide_banner','-loglevel','error','-y','-i',raw,'-i',path.join(work,'narration.wav'),'-i',srt,'-t','120','-map','0:v:0','-map','1:a:0','-map','2:s:0','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-c:a','aac','-c:s','mov_text','-movflags','+faststart',path.join(out,'revero-demo.mp4')]);
  fs.writeFileSync(path.join(out,'demo-manifest.json'),JSON.stringify({scope:'Offline demonstration with authored synthetic samples, deterministic AI stand-ins, and a fake Telegram sender.',duration_seconds:120,chapters:steps.map((step,i)=>({start:i*20,title:step[0],narration:step[1]})),real_provider_calls:0,real_telegram_messages:0},null,2)+'\n');
  console.log(`Saved narrated 120-second demo: ${path.join(out,'revero-demo.mp4')}`);
 }
} finally {
 if(context) await context.close();
 if(browser) await browser.close();
 for(const child of [vite,api]) if(child&&child.exitCode===null) {child.kill('SIGTERM');await Promise.race([new Promise(resolve=>child.once('exit',resolve)),delay(5000)]);}
 fs.closeSync(log);
 fs.rmSync(work,{recursive:true,force:true});
}
