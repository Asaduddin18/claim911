// Accessibility of actual product views with intercepted synthetic API fixtures.
// This is rendering/keyboard evidence, not live API or workflow evidence.
import {chromium} from 'playwright';
import axe from 'axe-core';
import {writeFile} from 'node:fs/promises';
const output=process.env.CLAIM911_A11Y_REPORT;
if(!output)throw new Error('A new accessibility report path is required.');
const id='00000000-0000-4000-8000-000000002084',doc='00000000-0000-4000-8000-000000002085';
const active={id,name:'Ananya',concern:'We are waiting for final insurance clearance.',language:'en',status:'Your hospital has confirmed the outcome',
 stage:3,stages:['Getting started','Collecting documents','Awaiting a decision','Confirmed outcome'],
 next_action:'Review the reconciliation and unpaid refund.',consent_active:true,coordination_available:false,voice_available:false,
 documents:[{id:doc,name:'Synthetic revised bill.json',kind:'itemized_bill',status:'UPLOADED',evidence_checked:true}],
 packet_permission:{packet_hash:'a'.repeat(64),recipient:'Synthetic TPA claims desk',approved:false,documents:[{id:doc,kind:'itemized_bill',revision:2}]},
 tasks:[{kind:'itemized_bill',owner:'billing',state:'EVIDENCE_COLLECTED'}],
 summary:{statements:[{text:'The hospital confirmed discharge clearance.',source:{issuer:'demo-hospital-billing'}}],pending:['Refund payment remains unverified.']},
 financials:{bill_inr:248000,insurer_payable_inr:230000,patient_payable_inr:18000,deposit_inr:30000,balance_due_inr:0,refund_due_inr:12000},activity:[]};
const report={scope:'PRODUCT_RENDERING_FIXTURES_ONLY',provider_requests:0,operational_writes:0,workflow_verified:false,checks:[],errors:[]};
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>report.errors.push(e.message));
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),path=url.pathname;
  let data;
  if(path==='/api/caregiver/cases')data=[active];
  else if(path.endsWith('/activity'))data={items:[{id:1,stage:'Evidence',title:'Hospital reconciliation checked',at:'2026-10-24T12:00:00Z'}],next_cursor:null};
  else if(path.endsWith('/conversations'))data={items:[{id:doc,participant_role:'hospital',created_at:'2026-10-24T12:00:00Z'}]};
  else if(path.includes('/conversations/'))data={transcript:[{speaker:'assistant',text:'Has clearance been confirmed?'},{speaker:'participant',text:'The hospital has issued its reconciliation.'}]};
  else if(path.endsWith('/packet-permission')){active.packet_permission.approved=true;data=active;}
  else {report.errors.push('Unexpected fixture request: '+path);return route.fulfill({status:418,contentType:'application/json',body:'{"detail":"Fixture boundary blocked this request"}'});}
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
 });
 await page.goto('http://127.0.0.1:3110/',{waitUntil:'networkidle'});
 await page.getByRole('heading',{name:'Ananya, a clearer next step.'}).waitFor();
 await page.getByText('Outcome confirmed',{exact:true}).waitFor();
 if(await page.getByText('Automated follow-up is not connected yet. Your request is saved.',{exact:true}).isVisible())throw new Error('Completed outcome still shows saved-request setup copy');
 await page.addScriptTag({content:axe.source});
 async function audit(view){
  // Let the existing short button transition settle after fixture updates.
  await page.waitForTimeout(250);
  const findings=await page.evaluate(async()=>{const r=await window.axe.run(document,{runOnly:['wcag2a','wcag2aa','wcag21aa']});return r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}));});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  report.checks.push({view,violations:findings,horizontal_overflow:overflow});
 }
 for(const tab of ['Overview','Documents','Permissions','Activity']){
  await page.getByRole('tab',{name:tab,exact:true}).click();await audit('desktop-'+tab.toLowerCase());
  if(tab==='Permissions'){
   await page.getByLabel('I approve sharing only these documents with this recipient.').check();
   await page.getByRole('button',{name:'Approve this packet',exact:true}).click();
   await page.getByText('Permission applies to this exact document packet.').waitFor();await audit('packet-approved');
  }
  if(tab==='Activity'){
   await page.getByRole('button',{name:'Hospital desk'}).click();await page.getByRole('dialog').waitFor();await audit('conversation-dialog');
   let focus=true;for(let n=0;n<8;n++){await page.keyboard.press('Tab');focus&&=await page.evaluate(()=>document.querySelector('[role="dialog"]').contains(document.activeElement));}
   await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'});
   await page.waitForFunction(()=>document.activeElement?.textContent?.includes('Hospital desk'),{},{timeout:2000}).catch(()=>{});
   const returned=await page.getByRole('button',{name:'Hospital desk'}).evaluate(el=>el===document.activeElement);
   report.checks.push({view:'conversation-keyboard',focus_contained:focus,escape_closed:true,focus_returned:returned});
  }
 }
 await page.setViewportSize({width:390,height:844});
 for(const tab of ['Overview','Documents','Permissions','Activity']){await page.getByRole('tab',{name:tab,exact:true}).click();await audit('mobile-'+tab.toLowerCase());}
}catch(e){report.errors.push(e.message);}finally{await browser.close();}
report.passed=!report.errors.length&&!report.checks.some(c=>c.horizontal_overflow||c.violations?.length||c.focus_contained===false||c.focus_returned===false);
await writeFile(output,JSON.stringify(report,null,2)+'\n',{mode:0o600,flag:'wx'});
console.log(JSON.stringify(report));if(!report.passed)process.exitCode=1;
