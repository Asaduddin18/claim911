import {chromium,request} from 'playwright';
import {chmod,mkdir,readFile,writeFile} from 'node:fs/promises';
import {dirname,resolve} from 'node:path';

const baseURL=process.env.CLAIM911_SANDBOX_URL||'http://127.0.0.1:3130/';
const runtime=resolve(process.env.CLAIM911_RUNTIME||resolve(process.cwd(),'../../../work/claim911-runtime'));
const reportPath=resolve(process.env.CLAIM911_A11Y_REPORT||resolve(process.cwd(),'../../Claim911_Accessibility_Sandbox.json'));
const chromePath=process.env.CLAIM911_CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const profile=JSON.parse(await readFile(resolve(runtime,'sandbox/coordinator.json'),'utf8'));
const result={surface:'sandbox',environment:'synthetic',phone_dispatch:false,checks:[],errors:[]};
let api,browser;

async function audit(page,label,{dialog=false}={}){
  if(dialog)await page.keyboard.press('Alt+Shift+A');
  else await page.getByRole('button',{name:'Run accessibility check'}).click();
  const output=page.getByTestId('accessibility-results');
  await output.waitFor({state:'visible',timeout:45000}).catch(async error=>{
    const panel=await page.locator('#claim911-audit-panel').innerText().catch(()=>'<audit panel missing>');
    const button=await page.locator('#claim911-audit-panel button').evaluate(el=>({disabled:el.disabled,text:el.innerText})).catch(()=>null);
    await page.screenshot({path:resolve(dirname(reportPath),'Claim911_Sandbox_A11y_Debug.png')}).catch(()=>{});
    throw new Error(error.message+'; audit panel: '+panel.slice(0,1200)+'; button: '+JSON.stringify(button));
  });
  const report=JSON.parse(await output.textContent());
  result.checks.push({view:label,violations:report.violations||[],passes:report.passes||0,
    incomplete:report.incomplete||[]});
  return report;
}

try{
  api=await request.newContext({baseURL:new URL(baseURL).origin});
  const login=await api.post('/api/sessions',{data:{role:'sandbox',credential:profile.operator_token}});
  if(!login.ok())throw new Error('Sandbox session could not be created.');
  browser=await chromium.launch({headless:true,executablePath:chromePath});
  const context=await browser.newContext({storageState:await api.storageState(),viewport:{width:1440,height:1000}});
  const page=await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror',error=>result.errors.push({type:'pageerror',message:error.message}));
  await page.goto(new URL('/?audit=1',baseURL).toString(),{waitUntil:'networkidle'});
  await page.getByRole('heading',{name:'A safe place to prove it.'}).waitFor();
  await audit(page,'sandbox-home');

  const runs=page.locator('.run-choice');
  const runCount=await runs.count();
  if(runCount){
    await runs.first().click();
    await page.getByRole('tab',{name:'Conversations'}).click();
    await audit(page,'sandbox-run-conversations');
    const conversation=page.locator('.conversation-choice').first();
    if(await conversation.count()){
      await conversation.click();
      await page.getByRole('dialog').waitFor({state:'visible'});
      await audit(page,'sandbox-conversation-drawer',{dialog:true});
      const focusChecks=[];
      for(let index=0;index<5;index++){
        await page.keyboard.press('Tab');
        focusChecks.push(await page.evaluate(()=>({insideDialog:Boolean(document.querySelector('[role="dialog"]')?.contains(document.activeElement)),
          role:document.activeElement?.getAttribute('role')||document.activeElement?.tagName.toLowerCase()})));
      }
      result.checks.push({view:'sandbox-dialog-keyboard-focus',focusChecks,
        focusStayedInDialog:focusChecks.every(item=>item.insideDialog)});
      await page.getByRole('dialog').press('Escape');
      const escapeClosed=await page.getByRole('dialog').waitFor({state:'hidden',timeout:2500})
        .then(()=>true).catch(()=>false);
      if(!escapeClosed)await page.getByRole('button',{name:'Close conversation'}).click();
      await page.getByRole('dialog').waitFor({state:'hidden'});
      const focusReturn=await page.evaluate(()=>({
        returnedToTrigger:document.activeElement?.classList.contains('conversation-choice'),
        activeTag:document.activeElement?.tagName.toLowerCase(),
        activeClass:typeof document.activeElement?.className==='string'?document.activeElement.className:'',
        activeLabel:(document.activeElement?.innerText||'').slice(0,100),
      }));
      result.checks.push({view:'sandbox-dialog-keyboard-dismissal',escapeClosed,...focusReturn});
    }else result.checks.push({view:'sandbox-conversation-drawer',skipped:'No conversation is available in the newest saved run.'});

    await page.getByRole('tab',{name:'Outcome'}).click();
    await audit(page,'sandbox-outcome');

    await page.setViewportSize({width:390,height:844});
    await page.waitForTimeout(150);
    const layout=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,
      horizontalOverflow:document.documentElement.scrollWidth>innerWidth}));
    result.checks.push({view:'sandbox-mobile-layout',...layout});
    await page.screenshot({path:resolve(dirname(reportPath),'Claim911_Sandbox_Mobile_A11y.png'),fullPage:true});
  }else result.checks.push({view:'sandbox-run-journeys',skipped:'No saved run is available to inspect.'});
  await context.close();
}catch(error){result.errors.push({type:error?.name||'Error',message:error?.message||'Sandbox accessibility audit failed.'});}
finally{
  if(browser)await browser.close();
  if(api)await api.dispose();
}
await mkdir(dirname(reportPath),{recursive:true});
await writeFile(reportPath,JSON.stringify(result,null,2)+'\n',{mode:0o600});
await chmod(reportPath,0o600);
console.log(JSON.stringify({surface:result.surface,checks:result.checks.map(c=>({view:c.view,
  violations:c.violations?.length??null,horizontalOverflow:c.horizontalOverflow??null,skipped:c.skipped??null})),errors:result.errors}));
const keyboardFailed=result.checks.some(c=>
  c.view==='sandbox-dialog-keyboard-focus'&&!c.focusStayedInDialog||
  c.view==='sandbox-dialog-keyboard-dismissal'&&(!c.escapeClosed||!c.returnedToTrigger));
if(result.errors.length||keyboardFailed||result.checks.some(c=>c.violations?.length||c.horizontalOverflow))process.exitCode=1;
