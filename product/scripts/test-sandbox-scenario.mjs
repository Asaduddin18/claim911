import {chromium} from 'playwright';
import axe from 'axe-core';
import {writeFile} from 'node:fs/promises';
const output=process.env.CLAIM911_SCENARIO_REPORT;if(!output)throw new Error('Fresh output required');
const report={scope:'SCENARIO_RENDERING_FIXTURES_ONLY',provider_requests:0,operational_writes:0,fixture_mutations:0,checks:[],errors:[]};
const id='00000000-0000-4000-8000-000000002084';
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 for(const [label,width,editable] of [['desktop',1440,true],['mobile',390,true],['bound-case',1440,false]]){
  const page=await browser.newPage({viewport:{width,height:900}});let faults=['unsigned_summary'];
  page.on('pageerror',error=>report.errors.push(error.message));
  await page.route('**/api/**',async route=>{
   const path=new URL(route.request().url()).pathname;
   const run={id,state:editable?'PREPARED':'READY',incident_id:editable?null:'bound-case',faults,checkpoint:0,checkpoint_count:13,created_at:'2026-10-25T00:00:00Z',checkpoints:[],conversations:[],recent_events:[],callback_waiting:false,outcome:null};
   let data;
   if(path==='/api/sandbox/status')data={runner_available:false,bolna_browser_available:false,scenario_management_available:true,paid_testing_allowed:false,paid_testing_message:'Paid testing is paused.'};
   else if(path==='/api/sandbox/runs')data=[run];
   else if(path===`/api/sandbox/runs/${id}`)data=run;
   else if(path.endsWith('/events'))return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
   else if(path.endsWith('/faults')&&editable&&route.request().method()==='POST'){
    faults=route.request().postDataJSON().faults;
    if(JSON.stringify([...faults].sort())!==JSON.stringify(['denied_insurer','desk_unavailable','old_bill','unsigned_summary','wrong_admission_invoice']))throw new Error('Unexpected selected fault set');
    report.fixture_mutations++;data={...run,faults};
   }else{report.errors.push('Unexpected fixture request '+path);return route.fulfill({status:418,body:'{}'});}
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto('http://127.0.0.1:3130/',{waitUntil:'domcontentloaded'});
  await page.getByRole('heading',{name:'A delayed discharge, explained.'}).waitFor();
  await page.getByRole('tab',{name:'Scenario',exact:true}).click();
  const invoice=page.getByRole('checkbox',{name:/Invoice belongs to another admission/});
  if(editable){
   await invoice.check();await page.getByRole('checkbox',{name:/Hospital has the old bill/}).check();
   await page.getByRole('checkbox',{name:/Billing sign-off is unavailable/}).check();
   const pending=page.getByRole('checkbox',{name:/Insurer review remains pending/});await pending.check();await page.getByRole('checkbox',{name:/Insurer issues a denial/}).check();if(await pending.isChecked())throw new Error('Conflicting insurer conditions remain selected');
   await Promise.all([page.waitForResponse(r=>r.url().endsWith('/faults')),page.getByRole('button',{name:'Save scenario conditions',exact:true}).click()]);
   await page.getByRole('button',{name:'Save scenario conditions',exact:true}).waitFor();
  }else if(!await invoice.isDisabled()||await page.getByRole('button',{name:'Save scenario conditions',exact:true}).count())throw new Error('Bound case must be read only');
  await page.addScriptTag({content:axe.source});
  const violations=await page.evaluate(async()=>{const result=await window.axe.run(document,{runOnly:['wcag2a','wcag2aa','wcag21aa']});return result.violations.map(v=>({id:v.id,impact:v.impact}));});
  report.checks.push({label,editable,violations,overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),paid_start_visible:await page.getByRole('button',{name:'Start audio run',exact:true}).count()>0});await page.close();
 }
}catch(error){report.errors.push(error.message)}finally{await browser.close()}
report.passed=!report.errors.length&&report.checks.length===3&&report.fixture_mutations===2&&!report.checks.some(c=>c.violations.length||c.overflow||c.paid_start_visible);
await writeFile(output,JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});console.log(JSON.stringify(report));if(!report.passed)process.exitCode=1;
