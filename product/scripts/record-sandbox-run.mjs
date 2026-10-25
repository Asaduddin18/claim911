// Observe one scoped synthetic run. Never starts a call or changes case state.
import {chromium} from 'playwright';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
const profile=JSON.parse(await readFile(process.argv[2],'utf8'));
if(profile.synthetic!==true||!profile.run_id||!profile.credential||!profile.output_dir)
 throw new Error('A private, run-scoped observer profile is required.');
await mkdir(profile.output_dir,{recursive:true,mode:0o700});
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context=await browser.newContext({serviceWorkers:'block',viewport:{width:1440,height:1000},
 recordVideo:{dir:profile.output_dir,size:{width:1440,height:1000}}});
const page=await context.newPage(),started=Date.now(),events=[];
try{
 await page.goto('http://127.0.0.1:3130/',{waitUntil:'networkidle'});
 const signedIn=await page.evaluate(async p=>{
  const r=await fetch('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({role:'sandbox_harness',credential:p.credential,run_id:p.run_id})});return r.ok;
 },profile);
 if(!signedIn)throw new Error('Observer could not enter its scoped run.');
 await page.goto('http://127.0.0.1:3130/?run='+profile.run_id,{waitUntil:'networkidle'});
 await page.locator('.run-detail').scrollIntoViewIfNeeded();
 let previous=-1;
 while(Date.now()-started<7200000){
  const state=await page.evaluate(async id=>{const r=await fetch('/api/sandbox/runs/'+id,{cache:'no-store'});if(!r.ok)throw new Error('Run unavailable');return r.json();},profile.run_id);
  if(state.checkpoint!==previous){
   previous=state.checkpoint;events.push({at_ms:Date.now()-started,checkpoint:state.checkpoint,state:state.state});
   await page.getByRole('tab',{name:'Progress',exact:true}).click();
   await page.locator('.run-detail').scrollIntoViewIfNeeded();
   await page.screenshot({path:profile.output_dir+'/checkpoint-'+state.checkpoint+'.png'});
  }
  if(state.state==='COMPLETED'){
   await page.getByRole('tab',{name:'Outcome',exact:true}).click();await page.waitForTimeout(3000);
   await page.screenshot({path:profile.output_dir+'/verified-outcome.png',fullPage:true});break;
  }
  if(state.state==='CANCELLED')break;
  await page.waitForTimeout(2000);
 }
}finally{
 const video=await page.video().path();await context.close();await browser.close();
 await writeFile(profile.output_dir+'/screen-capture.json',JSON.stringify({synthetic:true,run_id:profile.run_id,
  screen_recording:video,started_at:new Date(started).toISOString(),checkpoint_events:events,
  calls_started_by_observer:0,case_writes_by_observer:0},null,2),{mode:0o600});
}
