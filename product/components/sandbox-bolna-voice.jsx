'use client';
import {useEffect,useRef,useState} from 'react';
import {Mic,PhoneOff} from 'lucide-react';
import {Button} from '@/components/ui/button';

export default function SandboxBolnaVoice({runId,available,onRefresh}){
 const clientRef=useRef(null),callIdRef=useRef(null);
 const [consent,setConsent]=useState(false),[state,setState]=useState('idle'),[error,setError]=useState('');
 const active=['connecting','ringing','active'].includes(state);
 useEffect(()=>()=>{clientRef.current?.stop().catch(()=>{});},[runId]);
 async function start(){
  if(!available||!consent||active)return;
  setError('');setState('connecting');
  try{
   const {BolnaWebCall}=await import('@bolna/web-call');
   const options={debug:false,getSession:async()=>{
    const response=await fetch('/api/sandbox/runs/'+runId+'/voice-session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({recording_consent:true}),cache:'no-store'});
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||'Bolna voice is unavailable.');
    callIdRef.current=data.call_id;return data.session;
   }};
   // Playwright may provide a private audio element so its synthetic role actor
   // can transcribe the actual Bolna question. Production callers use the SDK's
   // regular audio element and never see this harness hook.
   if(window.__claim911BolnaAudioElement instanceof HTMLAudioElement)options.audioElement=window.__claim911BolnaAudioElement;
   const client=new BolnaWebCall(options);
   clientRef.current=client;
   client.on('state-change',setState);
   client.on('volume-level',level=>{
    if(Array.isArray(window.__claim911BolnaVolumeEvents))window.__claim911BolnaVolumeEvents.push({level,at:Date.now()});
    if(typeof window.__claim911BolnaVolumeLevel==='function')window.__claim911BolnaVolumeLevel(level);
   });
   client.on('call-end',()=>{setState('ended');onRefresh?.()});
   client.on('error',()=>setError('Bolna could not connect. Review this synthetic run before trying again.'));
   await window.__claim911ResumeAudioTap?.();
   await client.start();
  }catch(e){setState('ended');setError(e.message||'Bolna could not connect. Review this synthetic run before trying again.');}
 }
 async function stop(){
  try{await clientRef.current?.stop()}finally{setState('ended');onRefresh?.()}
 }
 if(!available)return null;
 return <section className="sandbox-bolna" aria-label="Bolna browser voice check">
  <div className="sandbox-bolna-heading"><Mic size={17}/><strong>Bolna assistant voice check</strong></div>
  <p>Speak with the configured Claim911 assistant on this synthetic case. This checks the browser voice path; workflow checkpoints still need independent verification.</p>
  <label className="consent-check"><input type="checkbox" checked={consent} disabled={active} onChange={e=>setConsent(e.target.checked)}/><span>I agree to record this synthetic browser conversation.</span></label>
  <p role="status" aria-live="polite">{({idle:'Ready when you are.',connecting:'Connecting to Bolna…',ringing:'Waiting for the assistant…',active:'Connected to the Bolna assistant.',ended:'Voice session ended.'})[state]}</p>
  {error&&<p role="alert">{error}</p>}
  {active?<Button variant="outline" onClick={stop}><PhoneOff size={16}/> End voice check</Button>:<Button disabled={!consent||!available} onClick={start}><Mic size={16}/> Start Bolna voice check</Button>}
 </section>;
}
