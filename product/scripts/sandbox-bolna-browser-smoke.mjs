import {chromium,request} from 'playwright';
import {chmod,mkdir,writeFile} from 'node:fs/promises';
import {dirname} from 'node:path';
import {readFile} from 'node:fs/promises';

const appUrl=process.env.CLAIM911_SANDBOX_BROWSER_URL||'http://127.0.0.1:3130/';
const profilePath=process.env.CLAIM911_PROFILE_CONFIG;
const audioPath=process.env.CLAIM911_PARTICIPANT_AUDIO;
const reportPath=process.env.CLAIM911_REPORT_PATH;
const chromePath=process.env.CLAIM911_CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
if(!profilePath||!audioPath||!reportPath)throw new Error('Set private sandbox profile, synthetic audio, and report paths.');
const profile=JSON.parse(await readFile(profilePath,'utf8'));
if(profile.environment!=='sandbox'||profile.live_calls_enabled||profile.bolna_api_key){
 throw new Error('Bolna browser smoke requires an isolated key-free, phone-disabled sandbox profile.');
}
const result={provenance:'BOLNA_WEBRTC_SANDBOX_BROWSER_SMOKE',synthetic:true,phone_dispatch:false,
 assistant:'Bolna',participant:'synthetic caregiver audio fixture',connected:false,ended:false,
 full_case:false,checkpoint_count:0,errors:[]};
let stage='create-sandbox-session',api,browser;
try{
 api=await request.newContext({baseURL:new URL(appUrl).origin});
 const login=await api.post('/api/sessions',{data:{role:'sandbox',credential:profile.operator_token}});
 if(!login.ok())throw new Error('Sandbox session could not be created.');
 stage='prepare-fresh-synthetic-run';
 const created=await api.post('/api/sandbox/runs',{data:{language:'en'}});
 if(!created.ok())throw new Error('Fresh sandbox run could not be prepared.');
 const run=await created.json();result.run_id=run.id;
 const listed=await api.get('/api/sandbox/runs');
 if(!listed.ok())throw new Error('Prepared sandbox run could not be located.');
 const runIndex=(await listed.json()).findIndex(item=>item.id===run.id);
 if(runIndex<0)throw new Error('Prepared run is outside the visible sandbox history.');
 const storageState=await api.storageState();
 browser=await chromium.launch({headless:true,executablePath:chromePath,args:[
  '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
  `--use-file-for-fake-audio-capture=${audioPath}`,'--autoplay-policy=no-user-gesture-required'
 ]});
 const context=await browser.newContext({permissions:['microphone'],serviceWorkers:'block',storageState});
 const page=await context.newPage();page.setDefaultTimeout(20000);
 page.on('response',async response=>{
  if(!/\/voice-session$/.test(new URL(response.url()).pathname)||response.request().method()!=='POST')return;
  result.session_status=response.status();
  try{const body=await response.json();if(body?.call_id)result.call_id=body.call_id;
   result.transport=body?.transport;result.synthetic=body?.synthetic===true;result.phone_dispatch=body?.phone_dispatch;}
  catch{}
 });
 stage='open-sandbox';await page.goto(appUrl,{waitUntil:'networkidle'});
 await page.getByRole('heading',{name:'A safe place to prove it.'}).waitFor();
 const runPage=Math.floor(runIndex/5);
 for(let pageIndex=0;pageIndex<runPage;pageIndex++)await page.getByRole('button',{name:'Next'}).first().click();
 const runChoice=page.locator('.run-choice').nth(runIndex%5);await runChoice.waitFor({state:'visible'});await runChoice.click();
 const voice=page.getByRole('region',{name:'Bolna browser voice check'});
 await voice.waitFor({state:'visible',timeout:20000});
 stage='consent-and-start-browser-session';
 await voice.getByLabel('I agree to record this synthetic browser conversation.').check();
 await voice.getByRole('button',{name:'Start Bolna voice check'}).click();
 const status=voice.locator('[aria-live="polite"]');
 await page.waitForFunction(()=>{
  const text=document.querySelector('.sandbox-bolna [aria-live="polite"]')?.textContent||'';
  return text.includes('Connected to the Bolna assistant.')||text.includes('Bolna could not connect.')||text.includes('Bolna voice is unavailable.');
 },null,{timeout:60000});
 result.connected=(await status.textContent()||'').includes('Connected to the Bolna assistant.');
 if(!result.connected)throw new Error('Bolna browser session did not reach the connected state.');
 stage='synthetic-audio-exchange';
 await page.waitForTimeout(Number(process.env.CLAIM911_EXCHANGE_WAIT_MS||25000));
 stage='end-browser-session';
 await voice.getByRole('button',{name:'End voice check'}).click();
 await page.waitForFunction(()=>document.querySelector('.sandbox-bolna [aria-live="polite"]')?.textContent?.includes('Voice session ended.'));
 result.ended=true;
 stage='read-sandbox-evidence';
 const detail=await api.get('/api/sandbox/runs/'+run.id);
 if(detail.ok()){
  const value=await detail.json();result.state=value.state;result.checkpoint_count=value.checkpoint;
  result.provider_configuration=value.provider_configuration;
  result.conversations=value.conversations||[];
 }
 result.full_case=result.state==='COMPLETED'&&result.checkpoint_count===13;
 await context.close();
}catch(error){result.failed_at=stage;result.errors.push(error?.message||'Sandbox Bolna browser check failed.');}
finally{if(browser)await browser.close();if(api)await api.dispose();}
await mkdir(dirname(reportPath),{recursive:true});
await writeFile(reportPath,JSON.stringify(result,null,2)+'\n',{mode:0o600});
await chmod(reportPath,0o600);
console.log(JSON.stringify({provenance:result.provenance,connected:result.connected,ended:result.ended,
 session_status:result.session_status,transport:result.transport,synthetic:result.synthetic,
 phone_dispatch:result.phone_dispatch,run_id:result.run_id,checkpoint_count:result.checkpoint_count,
 full_case:result.full_case,errors:result.errors}));
if(!result.connected||!result.ended||result.transport!=='BOLNA_WEBRTC'||result.synthetic!==true||result.phone_dispatch!==false)process.exitCode=1;
