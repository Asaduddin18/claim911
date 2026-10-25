import {chromium} from 'playwright';
import axe from 'axe-core';
import {writeFile} from 'node:fs/promises';
const output=process.env.CLAIM911_A11Y_REPORT;if(!output)throw new Error('Fresh report path required');
const id='00000000-0000-4000-8000-000000002084';
let fixtureCancelled=false;
const report={fixture_mutations:0,scope:'CONTROLLER_RENDERING_FIXTURES_ONLY',provider_requests:0,operational_writes:0,checks:[],errors:[]};
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>report.errors.push(e.message));
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname;let data;
  if(path==='/api/controller/cases')data=[{id,title:'Synthetic discharge coordination',state:'DISCREPANCY_OPEN'}];
  else if(path===`/api/controller/cases/${id}`)data={documents:[{id:'proof-1',filename:'Synthetic discharge summary.txt'}]};
  else if(path.endsWith('/callbacks/callback-2')&&route.request().method()==='DELETE'){fixtureCancelled=true;report.fixture_mutations++;data={id:'callback-2',state:'CANCELLED'};}
  else if(path.endsWith('/callbacks'))data=[{id:'callback-1',purpose:'RECORDS_DOCUMENT',state:'UNCERTAIN',attempts:1,available_at:'2026-10-25T00:00:00Z',original_received_at:'2026-10-24T23:00:00Z',target_at:'2026-10-25T02:00:00Z',result:{summary:'The session ended before dispatch could be confirmed.'}},{id:'callback-2',purpose:'BILLING_DOCUMENT',state:fixtureCancelled?'CANCELLED':'WAITING',attempts:0,available_at:'2026-10-25T00:00:00Z'}];
  else if(path.endsWith('/activity'))data={items:[{id:1,stage:'Evidence',title:'Signed summary still needed',at:'2026-10-25T00:00:00Z'}],next_cursor:null};
  else if(path.endsWith('/conversations'))data={items:[{id:'call-1',participant_role:'hospital',created_at:'2026-10-25T00:00:00Z'}],next_offset:null};
  else if(path.endsWith('/conversations/call-1'))data={transcript:[{speaker:'assistant',text:'Is the signed summary ready?'},{speaker:'participant',text:'It still awaits a signature.'}]};
  else if(path===`/api/controller/cases/${id}/decisions`)data={observations:[{reference:'document:synthetic',status:'uploaded',summary:'The discharge summary is unsigned.'}],proposals:[{id:'proposal-1',desk:'medical_records',summary:'Ask medical records for the signed discharge summary.',expected_checkpoint:'signed_summary_checked',evidence_references:['document:synthetic']}],policy_decisions:[{proposal_id:'proposal-1',state:'permitted',reason:'Investigation consent is current. Document sharing needs exact approval.'}]};
  else{report.errors.push('Unexpected request: '+path);return route.fulfill({status:418,body:'{}'});}
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.goto('http://127.0.0.1:3120/',{waitUntil:'networkidle'});await page.getByRole('heading',{name:'Cases needing coordination'}).waitFor();await page.addScriptTag({content:axe.source});
 async function audit(view){const violations=await page.evaluate(async()=>{const r=await window.axe.run(document,{runOnly:['wcag2a','wcag2aa','wcag21aa']});return r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}));});report.checks.push({view,violations,horizontal_overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)});}
 for(const [view,width,height] of [['desktop',1440,1000],['mobile',390,844]]){
  fixtureCancelled=false;await page.setViewportSize({width,height});const opener=page.getByRole('button',{name:/Synthetic discharge coordination/});await opener.click();await page.getByRole('heading',{name:'Ask medical records for the signed discharge summary.'}).waitFor();await audit(view+'-proposal');await page.getByText('Supporting evidence (1)').click();await audit(view+'-evidence');
  await page.getByRole('tab',{name:'Documents',exact:true}).click();await page.getByRole('heading',{name:'Case documents'}).waitFor();await audit(view+'-documents');
  await page.getByRole('tab',{name:'Follow-ups',exact:true}).click();await page.getByText('Execution uncertain',{exact:true}).waitFor();await audit(view+'-followups');await page.getByRole('button',{name:'Cancel scheduled follow-up',exact:true}).click();await page.getByText('Cancelled',{exact:true}).waitFor();await audit(view+'-followup-cancelled');await page.getByRole('tab',{name:'Activity & conversations',exact:true}).click();await page.getByRole('button',{name:'Hospital desk'}).waitFor();await audit(view+'-activity');
  await page.getByRole('button',{name:'Hospital desk'}).click();await page.getByRole('heading',{name:'Case conversation',exact:true}).waitFor();await audit(view+'-conversation');
  await page.getByRole('button',{name:'Back to activity',exact:true}).click();await page.getByRole('heading',{name:'Case conversation',exact:true}).waitFor({state:'hidden'});
  await page.waitForFunction(()=>document.activeElement?.textContent?.includes('Hospital desk'),{},{timeout:2000}).catch(()=>{});const returned=await page.getByRole('button',{name:'Hospital desk'}).evaluate(el=>el===document.activeElement);report.checks.push({view:view+'-transcript-return',focus_returned:returned,focus_debug:await page.evaluate(()=>({active:document.activeElement?.outerHTML?.slice(0,500),dialogs:document.querySelectorAll('[role=dialog]').length,buttons:[...document.querySelectorAll('.conversation-choice')].map(el=>({html:el.outerHTML.slice(0,300),hidden:el.closest('[hidden]')?.outerHTML.slice(0,100),visible:!!el.offsetParent}))}))});
  let contained=true;
  for(let i=0;i<8;i++){await page.keyboard.press('Tab');contained&&=await page.evaluate(()=>document.querySelector('[role="dialog"]').contains(document.activeElement));}
  await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'});await opener.evaluate(el=>new Promise(resolve=>{let tries=0;const poll=()=>{if(document.activeElement===el||tries++>100)resolve();else setTimeout(poll,20)};poll()}));report.checks.push({view:view+'-keyboard',focus_contained:contained,escape_closed:true,focus_returned:await opener.evaluate(el=>el===document.activeElement)});
 }
}catch(e){report.errors.push(e.message);}finally{await browser.close();}
report.passed=!report.errors.length&&!report.checks.some(c=>c.horizontal_overflow||c.violations?.length||c.focus_contained===false||c.focus_returned===false);await writeFile(output,JSON.stringify(report,null,2)+'\n',{flag:'wx',mode:0o600});console.log(JSON.stringify(report));if(!report.passed)process.exitCode=1;
