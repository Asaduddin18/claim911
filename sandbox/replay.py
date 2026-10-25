"""Portable captured-run replay. No provider calls, scripts or external assets."""
import hashlib,json,wave
from html import escape
from pathlib import Path
from uuid import UUID


def join_captured_turns(paths,destination):
 """Join recorded PCM turns with a short pause, without synthesizing audio."""
 frames=[];format=None
 for path in paths:
  with wave.open(str(path),'rb') as source:
   current=(source.getnchannels(),source.getsampwidth(),source.getframerate())
   if source.getcomptype()!='NONE' or (format is not None and current!=format):
    raise ValueError('Captured turns must share an uncompressed audio format')
   format=current;frames.append(source.readframes(source.getnframes()))
 if not frames:return False
 channels,width,rate=format
 pause=b'\0'*(int(rate*.3)*channels*width)
 with wave.open(str(destination),'wb') as target:
  target.setnchannels(channels);target.setsampwidth(width);target.setframerate(rate)
  target.writeframes(pause.join(frames))
 return True


def render(snapshot,conversations):
 summary=snapshot['summary'];parts=[];interruptions=[]
 complete=snapshot.get('full_case_completed',True)
 intro=('Bolna is the Claim911 assistant. Its conversation partners are synthetic institution staff and a caregiver. These captured conversations and institution checks belong to one completed case, with successful phases retained across reviewed resumptions. This replay remains available offline.' if complete else 'Verified conversations from an unfinished synthetic case. The case will resume from its next unverified checkpoint; these phases do not need another call.')
 progress=('13 of 13 state checkpoints independently verified.' if complete else str(snapshot['verified_checkpoints'])+' of 13 checkpoints verified. The complete voice workflow is not yet verified.')
 for call in conversations:
  if not call['turns']:
   interruptions.append('<li>'+escape(call['purpose'].replace('_',' ').title())+': interrupted attempt; no verified audio archive.</li>')
   continue
  turns=''.join('<article><strong>'+escape(t['speaker'])+'</strong><p>'+escape(t['text'])+'</p><audio controls preload="none" src="'+escape(t['audio'],quote=True)+'"></audio></article>' for t in call['turns'])
  combined=('<p>Play the complete captured conversation</p><audio controls preload="none" src="'+escape(call['conversation_audio'],quote=True)+'"></audio><small>Captured turns joined with short pauses. Original call timing is not reproduced.</small>' if call.get('conversation_audio') else '')
  parts.append('<details><summary>'+escape(call['purpose'].replace('_',' ').title())+' · '+escape(call['state'])+'</summary>'+combined+turns+'</details>')
 if interruptions:parts.append('<details><summary>Review history: '+str(len(interruptions))+' interrupted attempts</summary><p>These attempts did not discard the case or replace its successful recordings. They do not count as completed checkpoints.</p><ul>'+''.join(interruptions)+'</ul></details>')
 statements=''.join('<li>'+escape(s['text'])+' <small>Source: '+escape(s['source']['issuer'])+'</small></li>' for s in summary['statements'])
 pending=''.join('<li>'+escape(p)+'</li>' for p in summary['pending'])
 return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claim911 captured demonstration</title><style>
 body{margin:0;background:#faf9f6;color:#24332d;font:17px/1.6 system-ui,sans-serif}main{max-width:850px;margin:auto;padding:36px 22px}h1{font-size:36px;line-height:1.2}h2{margin-top:38px}small{display:block;color:#5c6c63}.label{padding:12px 18px;background:#e7eee8;border-radius:12px}details{background:white;border:1px solid #dedfd7;border-radius:12px;margin:12px 0;padding:16px}summary{cursor:pointer;font-weight:600}article{padding:18px 0;border-top:1px solid #eee}audio{width:100%;max-width:480px}li{margin:12px 0}
 </style><main><p class="label">RECORDED REPLAY · Synthetic case · No live calls or actions</p><h1>'''+('From “approval pending” to a verified explanation.' if complete else 'Claim911: verified phase recordings.')+'''</h1><p>'''+escape(intro)+'''</p><p><strong>'''+escape(progress)+'''</strong> Conversation quality is evaluated separately.</p><h2>'''+('Verified outcome' if complete else 'What these recordings establish')+'''</h2><ul>'''+statements+'''</ul><h2>Still to confirm</h2><ul>'''+pending+'''</ul><h2>Recorded conversations</h2><p>'''+('Attempts and interruptions are preserved alongside successful conversations.' if complete else 'Bolna is the assistant. The other speakers are synthetic role participants. These are recorded conversations, not live calls.')+'''</p>'''+''.join(parts)+'</main></html>'


def export(conn,run_id,*,core,verifier,destination):
 from sandbox import runs
 run=runs.get(conn,run_id)
 if run['state']!='COMPLETED' or run['origin']!='AUDIO_DEMONSTRATION':raise ValueError('A completed actual audio demonstration is required')
 evaluation=verifier.audit(str(run['incident_id']))
 if not evaluation['passed'] or evaluation['fixture_audio_allowed']:raise ValueError('Actual audio and every independent state gate must verify')
 response=core.get('/v1/incidents/'+str(run['incident_id']));response.raise_for_status();data=response.json()
 if not data['incident']['is_test']:raise ValueError('Only synthetic cases may be exported')
 calls=data['calls']
 if len(calls)>40:raise ValueError('Replay export exceeds its bounded conversation count')
 destination=Path(destination);destination.mkdir(parents=True,exist_ok=False);audio=destination/'audio';audio.mkdir()
 conversations=[];total=0
 for call in calls:
  if call['mode']!='SANDBOX_AUDIO' or not call.get('transcript'):continue
  cid=str(UUID(str(call['id'])))
  transcript=call['transcript']
  if call.get('sandbox_audio_provenance')=='BOLNA_WEBRTC':
   archived=core.get(f'/v1/sandbox/incidents/{run["incident_id"]}/audio-calls/{cid}/browser-archive')
   if archived.status_code==404:
    conversations.append({'id':cid,'purpose':call['purpose'],'state':'AUDIO_NOT_VERIFIED','turns':[]})
    continue
   archived.raise_for_status();transcript=archived.json()['turns']
  response=core.get(f'/v1/sandbox/incidents/{run["incident_id"]}/audio-calls/{cid}/artifacts');response.raise_for_status();artifacts=response.json()
  if len(artifacts)!=len(transcript):raise ValueError('Incomplete audio archive')
  turns=[]
  for index,(turn,artifact) in enumerate(zip(transcript,artifacts)):
   if artifact['turn_index']!=index or artifact['content_hash']!=turn['audio_sha256']:raise ValueError('Transcript/audio binding mismatch')
   aid=str(UUID(str(artifact['id'])));response=core.get(f'/v1/sandbox/incidents/{run["incident_id"]}/audio/{aid}');response.raise_for_status()
   total+=len(response.content)
   if total>200_000_000:raise ValueError('Replay size limit reached')
   name=cid+'-'+str(index)+'.wav';(audio/name).write_bytes(response.content)
   turns.append({'speaker':turn['speaker'],'text':turn['text'],'audio':'audio/'+name,'pcm_sha256':artifact['content_hash'],'wav_sha256':hashlib.sha256(response.content).hexdigest()})
  conversation={'id':cid,'purpose':call['purpose'],'state':call['state'],'turns':turns}
  combined_name=cid+'-conversation.wav'
  if join_captured_turns([destination/t['audio'] for t in turns],audio/combined_name):
   conversation['conversation_audio']='audio/'+combined_name
   conversation['conversation_audio_sha256']=hashlib.sha256((audio/combined_name).read_bytes()).hexdigest()
  conversations.append(conversation)
 snapshot={'run_id':str(run_id),'synthetic':True,'presentation_mode':'RECORDED_REPLAY','live':False,'evaluation':evaluation,'summary':data['complex_workflow']['caregiver_summary'],'conversations':conversations}
 (destination/'capture.json').write_text(json.dumps(snapshot,indent=2,default=str))
 (destination/'index.html').write_text(render(snapshot,conversations))
 return destination/'index.html'
