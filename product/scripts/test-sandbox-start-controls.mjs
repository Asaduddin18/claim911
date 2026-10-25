// Synthetic browser fixtures only. Every API request is intercepted.
import {chromium} from 'playwright';
import {writeFile} from 'node:fs/promises';
const output=process.env.CLAIM911_CONTROL_REPORT;if(!output)throw new Error('Fresh report path required');
const report={scope:'SANDBOX_CONTROL_RENDERING_FIXTURES_ONLY',provider_requests:0,operational_writes:0,checks:[],errors:[]};
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const id='00000000-0000-4000-8000-000000002084';
try{
 for(const [name,operator,worker,paid=true] of [['operator',true,true],['scoped-harness',false,true],['offline-compatibility',true,false],['paid-testing-paused',true,true,false]]){
  const page=await browser.newPage();let starts=0;let state='READY';page.on('pageerror',e=>report.errors.push(e.message));
  await page.route('**/api/**',async route=>{
   const path=new URL(route.request().url()).pathname;
   const run={id,state,checkpoint:0,checkpoint_count:13,execution_scope:'FULL_CASE',created_at:'2026-10-25T00:00:00Z',checkpoints:[{key:'caregiver_intake_confirmed',title:'Caregiver intake',state:'current'}],conversations:[],recent_events:[],callback_waiting:false,outcome:null};
   let data;
   if(path==='/api/sandbox/status')data={runner_available:worker,bolna_browser_available:true,scenario_management_available:operator,paid_testing_allowed:paid,paid_testing_message:'Paid testing is paused. Saved runs remain inspectable; no new voice session will start.'};
   else if(path==='/api/sandbox/runs')data=[run];
   else if(path===`/api/sandbox/runs/${id}`)data=run;
   else if(path.endsWith('/events'))return route.fulfill({status:200,contentType:'text/event-stream',body:': fixture\n\n'});
   else if(path===`/api/sandbox/runs/${id}/start`&&operator&&worker&&route.request().method()==='POST'){starts++;state='RUNNING';data={job_id:'fixture-only'};}
   else{report.errors.push('Unexpected fixture request '+path);return route.fulfill({status:418,body:'{}'});}
   await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('http://127.0.0.1:3130/',{waitUntil:'domcontentloaded'});
  await page.getByRole('heading',{name:'Discharge coordination',exact:true}).waitFor();
  const start=page.getByRole('button',{name:'Start audio run',exact:true});
  const manual=page.getByRole('region',{name:'Bolna browser voice check'});
  // Let the run details finish their independent fixture fetch.
  await page.getByRole('heading',{name:'A delayed discharge, explained.'}).waitFor();
  const hasStart=await start.count()===1,hasManual=await manual.count()===1;
  if(hasStart!==(operator&&worker&&paid)||hasManual!==(paid&&(!worker||!operator)))throw new Error(name+' control boundary mismatch');
  if(operator&&worker&&paid){await start.click();await page.getByRole('button',{name:'Pause safely',exact:true}).waitFor();if(starts!==1)throw new Error('Start must queue exactly once');}
  if(!paid)await page.getByText('Paid testing is paused. Saved runs remain inspectable; no new voice session will start.',{exact:true}).waitFor();
  report.checks.push({name,workflow_start_visible:hasStart,manual_voice_visible:hasManual,fixture_start_requests:starts,passed:true});await page.close();
 }
}catch(e){report.errors.push(e.message);}finally{await browser.close();}
report.passed=!report.errors.length&&report.checks.length===4;
await writeFile(output,JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});console.log(JSON.stringify(report));if(!report.passed)process.exitCode=1;
