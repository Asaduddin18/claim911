"""Bind captured browser turns to actual completed Bolna provider evidence."""
import base64
import hashlib
import re
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from fastapi import HTTPException
from psycopg.types.json import Jsonb


def provider_turns(transcript):
    result=[]
    for line in transcript.splitlines():
        match=re.match(r'^\s*(assistant|user)\s*:\s*(.*)$',line,re.I)
        if match:
            speaker='assistant' if match[1].lower()=='assistant' else 'participant'
            if result and result[-1]['speaker']==speaker:result[-1]['text']+=' '+match[2].strip()
            else:result.append({'speaker':speaker,'text':match[2].strip()})
        elif line.strip() and result:result[-1]['text']+=' '+line.strip()
    return result


def provider_evidence(config,call,body,*,fetch):
    if (call['mode']!='SANDBOX_AUDIO' or call['sandbox_audio_provenance']!='BOLNA_WEBRTC'
        or not call['execution_id'] or call['execution_id']!=str(body.execution_id)
        or call['state']!='COMPLETED' or not call['recording_consent']):
        raise HTTPException(409,'A completed, consented, exact Bolna provider execution is required')
    if body.assistant_config_sha256!=config.get('sandbox_bolna_agent_config_sha256'):
        raise HTTPException(409,'Captured audio uses a different reviewed assistant')
    saved='\n'.join(turn['text'] for turn in call['transcript'] if turn.get('speaker')=='provider_transcript')
    if not saved or hashlib.sha256(saved.encode()).hexdigest()!=body.provider_transcript_sha256:
        raise HTTPException(409,'The original finalized provider transcript must match the captured session')
    if not fetch:return None
    base=config.get('sandbox_bolna_broker_url','');target=urlsplit(base)
    if target.scheme!='http' or target.hostname!='127.0.0.1' or target.port!=8127 or target.path not in {'','/'} or target.username or target.password or target.query or target.fragment:
        raise HTTPException(503,'The trusted local provider-evidence broker is unavailable')
    try:
        with httpx.Client(timeout=10,follow_redirects=False) as client:
            response=client.post(base.rstrip('/')+'/execution',headers={'Authorization':'Bearer '+config['sandbox_bolna_broker_token']},
                json={'execution_id':call['execution_id'],'call_id':str(call['id']),'incident_id':str(call['incident_id'])})
        response.raise_for_status();value=response.json()
        if (value.get('execution_id')!=call['execution_id'] or value.get('status')!='completed'
            or value.get('transcript')!=saved):raise ValueError('Provider evidence differs')
        return value
    except Exception:raise HTTPException(409,'The independent provider execution could not confirm this archive') from None


def archive_record(conn,call,body,evidence,event):
    if call['state']!='COMPLETED' or call['execution_id']!=str(body.execution_id) or evidence['execution_id']!=call['execution_id']:
        raise HTTPException(409,'Provider execution changed during archive verification')
    actual=provider_turns(evidence['transcript'])
    normalize=lambda text:re.sub(r'\s+',' ',text).strip()
    if len(actual)!=len(body.turns) or any(t.speaker!=p['speaker'] or normalize(t.text)!=normalize(p['text']) for t,p in zip(body.turns,actual)):
        raise HTTPException(409,'Captured turn labels and text must preserve the actual provider transcript')
    transcript=[];decoded=[];total=0
    for turn in body.turns:
        try:pcm=base64.b64decode(turn.pcm_base64,validate=True)
        except ValueError:raise HTTPException(422,'Every captured turn requires valid PCM') from None
        total+=len(pcm)
        if not 0<len(pcm)<=(3200000 if turn.speaker=='participant' else 1280000) or len(pcm)%2 or total>16000000:raise HTTPException(413,'Captured conversation exceeds its audio bound')
        decoded.append(pcm);transcript.append({'speaker':turn.speaker,'text':turn.text,'audio_sha256':hashlib.sha256(pcm).hexdigest()})
    if {turn['speaker'] for turn in transcript}!={'assistant','participant'}:raise HTTPException(422,'Both captured conversation sides are required')
    prior=conn.execute('SELECT * FROM coordinator.sandbox_browser_archives WHERE call_id=%s',(call['id'],)).fetchone()
    if prior:
        if (prior['turns']!=transcript or prior['execution_id']!=call['execution_id']
            or prior['assistant_config_sha256']!=body.assistant_config_sha256
            or prior['provider_transcript_sha256']!=body.provider_transcript_sha256):
            raise HTTPException(409,'Completed browser audio evidence is immutable')
    else:
        conn.execute('''INSERT INTO coordinator.sandbox_browser_archives(call_id,execution_id,assistant_config_sha256,provider_transcript_sha256,turns)
            VALUES(%s,%s,%s,%s,%s)''',(call['id'],call['execution_id'],body.assistant_config_sha256,body.provider_transcript_sha256,Jsonb(transcript)))
        for index,(turn,pcm) in enumerate(zip(transcript,decoded)):
            conn.execute('''INSERT INTO coordinator.sandbox_audio_artifacts(id,incident_id,call_id,turn_index,speaker,content_hash,pcm)
                VALUES(%s,%s,%s,%s,%s,%s,%s)''',(uuid4(),call['incident_id'],call['id'],index,turn['speaker'],turn['audio_sha256'],pcm))
        event(conn,call['incident_id'],'BOLNA_BROWSER_AUDIO_ARCHIVED',{'call_id':str(call['id']),
            'execution_id':call['execution_id'],'provider_transcript_sha256':body.provider_transcript_sha256,
            'assistant_config_sha256':body.assistant_config_sha256,'turn_count':len(transcript),'verified_institution_outcome':False})
    return {'archived':True,'call_id':str(call['id']),'execution_id':call['execution_id'],
        'transport':'BOLNA_WEBRTC','provider_transcript_preserved':True,'verified_institution_outcome':False}
