import {chromium,request} from 'playwright';
import {chmod,mkdir,readFile,writeFile} from 'node:fs/promises';
import {dirname,resolve} from 'node:path';

const runtime=resolve(process.env.CLAIM911_RUNTIME||resolve(process.cwd(),'../../../work/claim911-runtime'));
const reportPath=resolve(process.env.CLAIM911_A11Y_REPORT||resolve(process.cwd(),'../../Claim911_Accessibility_Caregiver_Controller.json'));
const chromePath=process.env.CLAIM911_CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const operational=JSON.parse(await readFile(resolve(runtime,'operational/coordinator.json'),'utf8'));
const surfaces=[
 {name:'caregiver',url:process.env.CLAIM911_CAREGIVER_URL||'http://127.0.0.1:3110/',credential:null},
 {name:'controller',url:process.env.CLAIM911_CONTROLLER_URL||'http://127.0.0.1:3120/',credential:operational.operator_token},
];
const result={environment:'operational',checks:[],errors:[]};
let browser;

async function audit(page,surface,view,{dialog=false}={}){
 if(dialog)await page.keyboard.press('Alt+Shift+A');
 else await page.getByRole('button',{name:'Run accessibility check'}).click();
 const output=page.getByTestId('accessibility-results');
 await output.waitFor({state:'visible',timeout:45000});
 const full=JSON.parse(await output.textContent());
 const check={surface,view,violations:(full.violations||[]).map(v=>({id:v.id,impact:v.impact,nodeCount:v.nodes?.length||0})),passes:full.passes||0};
 result.checks.push(check);
 return check;
}

try{
 browser=await chromium.launch({headless:true,executablePath:chromePath});
 for(const surface of surfaces){
  let api,context;
  try{
   const origin=new URL(surface.url).origin;
   api=await request.newContext({baseURL:origin});
   const payload={role:surface.name};
   if(surface.credential)payload.credential=surface.credential;
   const login=await api.post('/api/sessions',{data:payload});
   if(!login.ok())throw new Error(`${surface.name} session failed with HTTP ${login.status()}`);
   context=await browser.newContext({storageState:await api.storageState(),viewport:{width:1440,height:1000}});
   const page=await context.newPage();page.setDefaultTimeout(15000);
   page.on('pageerror',error=>result.errors.push({surface:surface.name,type:'pageerror',message:error.message}));
   await page.goto(new URL('/?audit=1',surface.url).toString(),{waitUntil:'networkidle'});
   if(surface.name==='caregiver'){
    await page.locator('.welcome').waitFor();
    await audit(page,surface.name,'home');
    await page.getByRole('button',{name:'Tell us what’s happening'}).click();
    const dialog=page.getByRole('dialog');await dialog.waitFor();
    await audit(page,surface.name,'intake-dialog',{dialog:true});
    const focusChecks=[];
    for(let i=0;i<12;i++){
     await page.keyboard.press('Tab');
     focusChecks.push(await page.evaluate(()=>Boolean(document.querySelector('[role="dialog"]')?.contains(document.activeElement))));
    }
    result.checks.push({surface:surface.name,view:'intake-keyboard-focus',focusStayedInDialog:focusChecks.every(Boolean)});
    await page.keyboard.press('Escape');
    const escapeClosed=await dialog.waitFor({state:'hidden',timeout:2500}).then(()=>true).catch(()=>false);
    const focusReturned=await page.evaluate(()=>document.activeElement?.textContent?.includes('Tell us what’s happening')||false);
    result.checks.push({surface:surface.name,view:'intake-keyboard-dismissal',escapeClosed,focusReturned});
   }else{
    await page.locator('.operator-page').waitFor();
    if(await page.locator('.operator-login').count()){
     await page.getByLabel('Workspace credential').fill(surface.credential);
     await page.getByRole('button',{name:'Open workspace'}).click();
    }
    await page.getByRole('heading',{name:'Cases needing coordination'}).waitFor();
    await audit(page,surface.name,'operations-queue');
   }
   await page.setViewportSize({width:390,height:844});
   await page.waitForTimeout(120);
   const layout=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,
    horizontalOverflow:document.documentElement.scrollWidth>innerWidth}));
   result.checks.push({surface:surface.name,view:'mobile-layout',...layout});
   await context.close();
  }catch(error){result.errors.push({surface:surface.name,type:error?.name||'Error',message:error?.message||'Surface audit failed.'});}
  finally{if(context)await context.close();if(api)await api.dispose();}
 }
}catch(error){result.errors.push({type:error?.name||'Error',message:error?.message||'Accessibility browser could not start.'});}
finally{if(browser)await browser.close();}

await mkdir(dirname(reportPath),{recursive:true});
await writeFile(reportPath,JSON.stringify(result,null,2)+'\n',{mode:0o600});
await chmod(reportPath,0o600);
console.log(JSON.stringify({checks:result.checks.map(c=>({surface:c.surface,view:c.view,
 violations:c.violations?.length??null,horizontalOverflow:c.horizontalOverflow??null,
 focusStayedInDialog:c.focusStayedInDialog??null,escapeClosed:c.escapeClosed??null,
 focusReturned:c.focusReturned??null})),errors:result.errors}));
const failed=result.errors.length||result.checks.some(c=>c.violations?.length||c.horizontalOverflow||
 c.view==='intake-keyboard-focus'&&!c.focusStayedInDialog||c.view==='intake-keyboard-dismissal'&&(!c.escapeClosed||!c.focusReturned));
if(failed)process.exitCode=1;
