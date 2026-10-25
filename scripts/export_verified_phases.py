"""Export existing verified phase audio and screen videos, without provider use."""
import argparse,json,hashlib,shutil,sys
from pathlib import Path
from datetime import datetime,timezone
from html import escape
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordinator.app import create_app
from simulator.app import create_app as institution_app
from sandbox import runs
from sandbox.checkpoints import CheckpointVerifier
from sandbox.replay import join_captured_turns
from sandbox.executor import PHASES

NAMES=['Caregiver intake','Hospital references','TPA query','Corrected bill','Signed summary and callback','Implant invoice','Exact packet approval','Hospital submission','Receiving-side receipt','Query closure and enhancement linkage','Insurer decision','Hospital reconciliation','Caregiver handoff']


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 for key in ('runtime','run-id','output'):parser.add_argument('--'+key,required=True)
 args=parser.parse_args();root=Path(args.runtime).resolve()/'sandbox';destination=Path(args.output).resolve();destination.mkdir(parents=True,exist_ok=True)
 cfg=json.loads((root/'coordinator.json').read_text());sim=json.loads((root/'simulator.json').read_text())
 if cfg.get('environment')!='sandbox' or sim.get('environment')!='sandbox':raise ValueError('Synthetic sandbox profiles required')
 reports={}
 for path in (root/'bolna-archives').glob(args.run_id+'-*.report.json'):
  report=json.loads(path.read_text())
  if report.get('call_id') and report.get('run_id')==args.run_id:reports[report['call_id']]=report
 with TestClient(create_app(cfg)) as core,TestClient(institution_app(sim)) as institutions:
  core.headers['Authorization']='Bearer '+cfg['operator_token']
  verifier=CheckpointVerifier(core,institutions,read_tokens=sim['tokens'],public_keys={'claims':cfg['receipt_public_key'],'hospital':cfg['hospital_public_key'],'insurer':cfg['insurer_public_key']})
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:run=runs.get(conn,args.run_id)
  response=core.get('/v1/incidents/'+str(run['incident_id']));response.raise_for_status();snapshot=response.json();steps=[]
  for index,key in enumerate(run['manifest']['checkpoints']):
   number=index+1;folder=destination/f'{number:02d}';folder.mkdir(exist_ok=True);purpose=PHASES[key][0]
   verified=number<=run['checkpoint'];check=verifier.inspect(key,str(run['incident_id'])) if verified else {'passed':False,'reason':'Pending at export time'}
   if verified and not check['passed']:raise ValueError('Previously completed checkpoint no longer verifies')
   (folder/'verification.json').write_text(json.dumps(check,indent=2,default=str))
   step={'number':number,'name':NAMES[index],'checkpoint':key,'verified':verified,'voice_step':purpose is not None,'evidence':f'{number:02d}/verification.json','calls':[]}
   if verified and purpose:
    candidates=[c for c in snapshot['calls'] if c['purpose']==purpose and c.get('sandbox_audio_provenance')=='BOLNA_WEBRTC']
    for call in candidates:
     cid=str(call['id']);archived=core.get(f'/v1/sandbox/incidents/{run["incident_id"]}/audio-calls/{cid}/browser-archive')
     if archived.status_code==404:continue
     archived.raise_for_status();turns=archived.json()['turns'];audio=core.get(f'/v1/sandbox/incidents/{run["incident_id"]}/audio-calls/{cid}/artifacts');audio.raise_for_status();artifacts=audio.json()
     if len(turns)!=len(artifacts):raise ValueError('Incomplete captured conversation')
     call_dir=folder/cid;call_dir.mkdir(exist_ok=True);files=[];transcript=[]
     for turn,artifact in zip(turns,artifacts):
      if artifact['content_hash']!=turn['audio_sha256']:raise ValueError('Audio binding mismatch')
      wav=core.get(f'/v1/sandbox/incidents/{run["incident_id"]}/audio/{artifact["id"]}');wav.raise_for_status();path=call_dir/f'{artifact["turn_index"]:02d}.wav';path.write_bytes(wav.content);files.append(path)
      transcript.append(f"**{turn['speaker'].title()}**: {turn['text']}")
     join_captured_turns(files,call_dir/'conversation.wav');(call_dir/'transcript.md').write_text('\n\n'.join(transcript)+'\n')
     entry={'call_id':cid,'audio':str((call_dir/'conversation.wav').relative_to(destination)),'transcript':str((call_dir/'transcript.md').relative_to(destination)),'video':None,'audio_timing':'Captured turns joined with 300 ms pauses; original timing is not reproduced.'}
     report=reports.get(cid,{})
     if report.get('screen_recording'):
      source=Path(report['screen_recording']).resolve()
      if not source.is_relative_to(root/'bolna-archives'):raise ValueError('Unexpected screen recording location')
      if source.is_file():shutil.copyfile(source,call_dir/'screen.webm');entry['video']=str((call_dir/'screen.webm').relative_to(destination))
     step['calls'].append(entry)
    if not step['calls']:raise ValueError('Verified voice checkpoint has no exported recording')
   steps.append(step)
  manifest={'run_id':args.run_id,'exported_at':datetime.now(timezone.utc).isoformat(),'verified_checkpoints':run['checkpoint'],'synthetic':True,'assistant_provider':'Bolna WebRTC','participant_provider':'Synthetic role participants with Azure speech','provider_requests_started_by_export':0,'screen_videos_have_separate_audio':True,'steps':steps}
  (destination/'artifacts.json').write_text(json.dumps(manifest,indent=2))
 rows=[];sections=[]
 for step in steps:
  state='Verified' if step['verified'] else 'Pending';links=[]
  for i,call in enumerate(step['calls'],1):
   label=f'Call {i}' if len(step['calls'])>1 else 'Call'
   links.append(f'<a href="{call["audio"]}">{label} audio</a> · '+(f'<a href="{call["video"]}">screen video</a> · ' if call['video'] else '')+f'<a href="{call["transcript"]}">transcript</a>')
   sections.append(f'<details><summary>{step["number"]}. {escape(step["name"])}: {label}</summary><audio controls preload="none" src="{call["audio"]}"></audio>'+(f'<video controls preload="none" src="{call["video"]}"></video>' if call['video'] else '')+'</details>')
  if step['verified'] and not step['voice_step']:links=['Non-call stage: <a href="'+step['evidence']+'">verification evidence</a>']
  rows.append(f'<tr><td>{step["number"]}</td><td>{escape(step["name"])}</td><td>{state}</td><td>'+('<br>'.join(links) or 'Will be appended')+'</td></tr>')
 html='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Claim911 voice artifacts</title><style>body{font:16px/1.5 system-ui;background:#faf9f6;color:#24332d;margin:0}main{max-width:1100px;margin:auto;padding:32px 20px}table{border-collapse:collapse;width:100%;background:white}td,th{text-align:left;padding:13px;border-bottom:1px solid #ddd}details{padding:16px;background:white;margin:12px 0;border-radius:12px}audio,video{display:block;width:100%;margin:16px 0}video{max-height:600px}a{color:#27654a}</style><main><h1>Claim911: audio, video and evidence</h1><p>Bolna is the assistant. All participants and case data are synthetic.</p><p><strong>'''+str(run['checkpoint'])+''' of 13 stages verified at this export.</strong> Pending stages will be appended to this same index.</p><p>Audio and screen videos are separate files, not yet stitched. Conversation audio joins the original captured turns with short pauses. Full transcripts and verification records are included. Earlier unsigned-summary calls remain available alongside its successful callback.</p><table><tr><th>Step</th><th>Stage</th><th>Status</th><th>Artifacts</th></tr>'''+''.join(rows)+'</table><h2>Play recordings</h2>'+''.join(sections)+'</main></html>'
 (destination/'index.html').write_text(html)
 locations=['# Claim911 artifact locations','','Bolna assistant; synthetic participants and case data. Audio and video are separate. Captured audio turns are joined with short pauses; original timing is not reproduced.','',f"{run['checkpoint']} of 13 stages verified at export.",'']
 for step in steps:
  locations.extend([f"## {step['number']}. {step['name']}",'','Verified.' if step['verified'] else 'Pending. Will be appended.',''])
  for number,call in enumerate(step['calls'],1):
   locations.extend([f'Call {number}:',''])
   for label,key in [('Audio','audio'),('Screen video','video'),('Transcript','transcript')]:
    if call.get(key):locations.append(f'- [{label}]({destination/call[key]})')
   locations.append('')
  locations.extend([f"[Verification evidence]({destination/step['evidence']})",''])
 (destination/'ARTIFACTS.md').write_text('\n'.join(locations))
 print(json.dumps({'verified_checkpoints':run['checkpoint'],'recorded_calls':sum(len(s['calls']) for s in steps),'index':str(destination/'index.html'),'provider_calls_started':0}))


if __name__=='__main__':main()
