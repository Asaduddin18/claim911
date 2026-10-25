import {chromium,request} from 'playwright';
import {chmod,mkdir,writeFile} from 'node:fs/promises';
import {dirname} from 'node:path';

const appUrl=process.env.CLAIM911_BROWSER_URL||'http://127.0.0.1:3110/';
const audioPath=process.env.CLAIM911_PARTICIPANT_AUDIO;
const reportPath=process.env.CLAIM911_REPORT_PATH;
const chromePath=process.env.CLAIM911_CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
if(!audioPath||!reportPath)throw new Error('Set CLAIM911_PARTICIPANT_AUDIO and CLAIM911_REPORT_PATH to private local paths.');

const result={provenance:'BOLNA_WEBRTC_BROWSER_SMOKE',synthetic:true,phone_dispatch:false,
 assistant:'Bolna',participant:'synthetic caregiver audio',connected:false,ended:false,transcript:[],errors:[]};
let stage='launch';
const api=await request.newContext({baseURL:new URL(appUrl).origin});
let browser;
try{
 stage='create-caregiver-session';
 const login=await api.post('/api/sessions',{data:{role:'caregiver'}});
 if(!login.ok())throw new Error('Caregiver session could not be created.');
 stage='create-synthetic-case';
 const created=await api.post('/api/caregiver/cases',{data:{name:'Synthetic caregiver',
  concern:'We are ready to leave, but the hospital says final insurance approval is pending. The discharge summary still needs a signature.',
  language:'en',investigation_consent:true}});
 if(!created.ok())throw new Error('Synthetic caregiver case could not be created.');
 const caseData=await created.json();result.case_id=caseData.id;
 const storageState=await api.storageState();

browser=await chromium.launch({headless:true,executablePath:chromePath,args:[
 '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
 `--use-file-for-fake-audio-capture=${audioPath}`,'--autoplay-policy=no-user-gesture-required'
]});
try{
 const context=await browser.newContext({permissions:['microphone'],serviceWorkers:'block',storageState});
 const page=await context.newPage();page.setDefaultTimeout(20000);
 page.on('response',async response=>{
  if(!/\/voice-session$/.test(new URL(response.url()).pathname)||response.request().method()!=='POST')return;
  try{const body=await response.json();if(body?.call_id)result.call_id=body.call_id;result.session_status=response.status();}
  catch{result.session_status=response.status();}
 });
 stage='open-caregiver-app';await page.goto(appUrl,{waitUntil:'networkidle'});
 stage='check-voice-consent';
 const voice=page.getByRole('region',{name:'Speak to Claim911'});
 await voice.waitFor({state:'visible',timeout:30000});
 await voice.getByLabel('I agree to record this conversation and save its transcript with my case.').check();
 stage='start-bolna-browser-session';await voice.getByRole('button',{name:'Speak to Claim911'}).click();
 const live=voice.locator('[aria-live="polite"]');
 await page.waitForFunction(()=>{
  const node=document.querySelector('.caregiver-voice [aria-live="polite"]');
  const text=node?.textContent||'';
  return text.includes('connected')||text.includes('could not connect')||text.includes('unavailable');
 },null,{timeout:45000});
 const state=await live.textContent();result.connected=Boolean(state&&state.toLowerCase().includes('connected'));
 if(!result.connected){result.errors.push('Bolna browser session did not reach the connected state.');}
 else{
  stage='synthetic-audio-exchange';
  await page.waitForTimeout(Number(process.env.CLAIM911_EXCHANGE_WAIT_MS||35000));
  stage='end-browser-session';
  await voice.getByRole('button',{name:'End conversation'}).click();
  await page.waitForFunction(()=>document.querySelector('.caregiver-voice [aria-live="polite"]')?.textContent?.toLowerCase().includes('ended'));
  result.ended=true;
 }
 const detail=await page.evaluate(async id=>{
  const item=await fetch('/api/caregiver/cases/'+id,{cache:'no-store'}).then(r=>r.ok?r.json():null);
  const conversations=await fetch('/api/caregiver/cases/'+id+'/conversations',{cache:'no-store'}).then(r=>r.ok?r.json():null);
  const items=conversations?.items||[];const details=[];
  for(const call of items){const saved=await fetch('/api/caregiver/cases/'+id+'/conversations/'+call.id,{cache:'no-store'});if(saved.ok)details.push(await saved.json())}
  return {case_id:item?.id,voice_available:item?.voice_available,conversations:details};
 },result.case_id);
 if(detail){result.voice_available=detail.voice_available;result.conversations=detail.conversations;}
 await context.close();
}catch(error){result.failed_at=stage;result.errors.push(error?.name||'Browser smoke test failed');}
finally{await browser.close();}
}catch(error){result.failed_at=stage;result.errors.push(error?.name||'Browser smoke test failed before browser launch');}
finally{await api.dispose();}
await mkdir(dirname(reportPath),{recursive:true});
 const turns=result.conversations?.flatMap(item=>item.transcript||[])||[];
 result.participant_audio_received=turns.some(turn=>turn.speaker!=='assistant'&&/user|caregiver|participant/i.test(turn.speaker||''));
 result.provider_state=result.conversations?.[0]?.state||null;
 await writeFile(reportPath,JSON.stringify(result,null,2)+'\n',{mode:0o600});await chmod(reportPath,0o600);
console.log(JSON.stringify({provenance:result.provenance,connected:result.connected,ended:result.ended,
 voice_available:result.voice_available,session_status:result.session_status,participant_audio_received:result.participant_audio_received,provider_state:result.provider_state,errors:result.errors}));
if(!result.connected||!result.ended)process.exitCode=1;
