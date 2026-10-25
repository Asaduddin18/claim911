'use client';
import {useEffect,useRef,useState} from 'react';
import {Mic,PhoneOff} from 'lucide-react';
import {Button} from '@/components/ui/button';

export default function CaregiverVoice({active,onRefresh}){
 const call=useRef(null),callId=useRef(null);
 const [consent,setConsent]=useState(false),[state,setState]=useState('idle'),[error,setError]=useState('');
 const busy=['connecting','ringing','active'].includes(state);
 async function request(path,body){
  const response=await fetch('/api/caregiver/cases/'+active.id+'/voice-session'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,cache:'no-store'});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'Voice is unavailable.');return data;
 }
 useEffect(()=>()=>{call.current?.stop().catch(()=>{});},[active.id]);
 useEffect(()=>{if(!active.consent_active){call.current?.stop().catch(()=>{});setState('ended')}},[active.consent_active]);
 async function start(){
  if(!consent||busy||!active.consent_active)return;
  setError('');setState('connecting');
  try{
   const {BolnaWebCall}=await import('@bolna/web-call');
   const client=new BolnaWebCall({debug:false,getSession:async()=>{
    const result=await request('',{recording_consent:true});callId.current=result.call_id;return result.session;
   }});
   call.current=client;
   client.on('state-change',setState);
   client.on('call-end',()=>{setState('ended');onRefresh?.()});
   client.on('error',()=>setError('Voice could not connect. Your case is saved. Review the connection before trying again.'));
   await client.start();
  }catch{setState('ended');setError('Voice could not connect. Your case is saved. Review the connection before trying again.');}
 }
 async function stop(){
  await call.current?.stop();setState('ended');
  if(callId.current)try{await request('/'+callId.current+'/stop')}catch{setError('Your microphone has stopped. Server confirmation is pending.');}
  onRefresh?.();
 }
 if(!active.voice_available)return null;
 return <section className="caregiver-voice" aria-label="Speak to Claim911">
  <div><Mic size={18}/><strong>Talk it through.</strong></div>
  <p>Use your browser microphone for this synthetic case.</p>
  <label className="consent-check"><input type="checkbox" checked={consent} disabled={busy} onChange={e=>setConsent(e.target.checked)}/><span>I agree to record this conversation and save its transcript with my case.</span></label>
  <p role="status" aria-live="polite">{({idle:'Ready when you are.',connecting:'Connecting your voice session…',ringing:'Waiting for Claim911…',active:'You’re connected.',ended:'Voice session ended.'})[state]}</p>
  {error&&<p role="alert">{error}</p>}
  {busy?<Button variant="outline" onClick={stop}><PhoneOff size={16}/> End conversation</Button>:<Button disabled={!consent||!active.consent_active} onClick={start}><Mic size={16}/> Speak to Claim911</Button>}
 </section>;
}
