"""Native sandbox audio conversations. No phone participant or outbound job exists."""
import base64,hashlib,io,secrets,wave
from datetime import datetime,timezone
from typing import Literal
from uuid import UUID,uuid4
from fastapi import Depends,Header,HTTPException,Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel,ConfigDict,Field
from coordinator.workflow_calls import WORKFLOW_ROLES,prepare_context,packet_hash


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')


class OpenAudio(Strict):
    purpose:Literal['CAREGIVER_INTAKE','HOSPITAL_REFERENCE_DISCOVERY','QUERY_DISCOVERY','BILLING_DOCUMENT','RECORDS_DOCUMENT','IMPLANT_DOCUMENT',
      'PACKET_SUBMISSION','TPA_QUERY_FOLLOWUP','INSURER_FOLLOWUP','DISCHARGE_FOLLOWUP','CAREGIVER_COMPLEX_UPDATE']
    audio_provenance:Literal['AUDIO_FIXTURE','PIPECAT_STDIO','BOLNA_WEBRTC']='AUDIO_FIXTURE'


class AudioTurn(Strict):
    speaker:Literal['assistant','participant']
    text:str=Field(min_length=1,max_length=4000)
    pcm_base64:str=Field(min_length=4,max_length=4266668)


class FinishAudio(Strict):
    outcome:Literal['COMPLETED','INTERRUPTED']='COMPLETED'
    turns:list[AudioTurn]=Field(min_length=1,max_length=40)


class BindProviderExecution(Strict):
    execution_id:UUID


class BrowserArchive(Strict):
    execution_id:UUID
    assistant_config_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    provider_transcript_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    turns:list[AudioTurn]=Field(min_length=2,max_length=40)


def require_current_context(conn,call):
    if call['mode']!='SANDBOX_AUDIO':return
    latest=conn.execute("SELECT coalesce(max(sequence),0) AS n FROM coordinator.events WHERE incident_id=%s AND type NOT IN ('VOICE_TOOL_USED','SANDBOX_PROVIDER_EXECUTION_BOUND')",(call['incident_id'],)).fetchone()['n']
    refreshed=conn.execute("SELECT payload FROM coordinator.events WHERE incident_id=%s AND type='VOICE_TOOL_USED' AND payload->>'call_id'=%s AND payload->>'tool'='claim911_context' ORDER BY sequence DESC LIMIT 1",(call['incident_id'],str(call['id']))).fetchone()
    if not refreshed or refreshed['payload'].get('material_sequence')!=latest:
        raise HTTPException(409,'Refresh current call context before reporting; the case evidence may have changed')


def install(app,db,operator,incident,require_consent,event,config):
    if config.get('environment')!='sandbox':return
    if not config.get('test_mode') or config.get('live_calls_enabled') or config.get('bolna_api_key'):
        raise ValueError('Native sandbox conversations require an isolated non-phone profile')
    with db() as conn:
        conn.execute('ALTER TABLE coordinator.calls ADD COLUMN IF NOT EXISTS sandbox_audio_provenance text')
        conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.sandbox_audio_artifacts(
          id uuid PRIMARY KEY,incident_id uuid NOT NULL REFERENCES coordinator.incidents(id),
          call_id uuid NOT NULL REFERENCES coordinator.calls(id),turn_index integer NOT NULL,
          speaker text NOT NULL,content_hash text NOT NULL,pcm bytea NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),UNIQUE(call_id,turn_index))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS coordinator.sandbox_browser_archives(
          call_id uuid PRIMARY KEY REFERENCES coordinator.calls(id),
          execution_id text UNIQUE NOT NULL,assistant_config_sha256 text NOT NULL,
          provider_transcript_sha256 text NOT NULL,turns jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now())''')

    @app.post('/v1/sandbox/incidents/{id}/audio-calls',dependencies=[Depends(operator)],status_code=201)
    def open_audio(id:UUID,body:OpenAudio):
        with db() as conn:
            row=incident(conn,id,True);require_consent(row)
            if row['state'] in {'HUMAN_REVIEW','PAUSED_REVOKED'}:raise HTTPException(409,'Case is held for review')
            workflow=conn.execute('SELECT data FROM coordinator.complex_workflows WHERE incident_id=%s',(id,)).fetchone()
            try:context=prepare_context(row,workflow['data'] if workflow else None,body.purpose)
            except ValueError as exc:raise HTTPException(409,str(exc)) from None
            active=conn.execute("SELECT id FROM coordinator.calls WHERE incident_id=%s AND mode='SANDBOX_AUDIO' AND state='IN_PROGRESS'",(id,)).fetchone()
            if active:raise HTTPException(409,'Finish or reconcile the active sandbox conversation first')
            count=conn.execute("SELECT count(*) AS n FROM coordinator.calls WHERE incident_id=%s AND mode='SANDBOX_AUDIO' AND (execution_id IS NOT NULL OR state!='FAILED')",(id,)).fetchone()['n']
            if count>=20:raise HTTPException(409,'Sandbox conversation limit reached; review required')
            call_id=uuid4();token='sbx_'+secrets.token_urlsafe(40)
            conn.execute('''INSERT INTO coordinator.calls(id,incident_id,participant_role,purpose,mode,state,tool_token_hash,
               consent_version,tool_expires_at,recording_consent,workflow_packet_hash,sandbox_audio_provenance)
               VALUES(%s,%s,%s,%s,'SANDBOX_AUDIO','IN_PROGRESS',%s,%s,now()+interval '15 minutes',true,%s,%s)''',
               (call_id,id,WORKFLOW_ROLES[body.purpose],body.purpose,hashlib.sha256(token.encode()).hexdigest(),row['consent_version'],
                packet_hash(row,workflow['data']) if body.purpose=='PACKET_SUBMISSION' else None,body.audio_provenance))
            event(conn,id,'SANDBOX_AUDIO_CALL_OPENED',{'call_id':str(call_id),'purpose':body.purpose,'transport':'SANDBOX_AUDIO','audio_provenance':body.audio_provenance,'phone_dispatch':False})
            return {'call_id':str(call_id),'call_token':token,'mode':'SANDBOX_AUDIO','phone_dispatch':False,
                    'requires_context_refresh':True,'objective':context['objective']}

    @app.post('/v1/sandbox/incidents/{id}/audio-calls/{call_id}/bind-provider-execution',dependencies=[Depends(operator)])
    def bind_provider_execution(id:UUID,call_id:UUID,body:BindProviderExecution):
        execution_id=str(body.execution_id)
        with db() as conn:
            row=incident(conn,id,True);require_consent(row)
            call=conn.execute('''SELECT * FROM coordinator.calls
                WHERE id=%s AND incident_id=%s AND mode='SANDBOX_AUDIO' FOR UPDATE''',(call_id,id)).fetchone()
            if not call:raise HTTPException(404,'Sandbox conversation not found')
            if call['sandbox_audio_provenance']!='BOLNA_WEBRTC' or call['state']!='IN_PROGRESS':
                raise HTTPException(409,'Only a current Bolna sandbox conversation can bind a provider execution')
            if call['consent_version']!=row['consent_version']:
                raise HTTPException(409,'Investigation permission changed before the provider session was bound')
            if call['execution_id']:
                if call['execution_id']!=execution_id:
                    raise HTTPException(409,'Conversation is already bound to another provider execution')
                return {'bound':True,'transport':'BOLNA_WEBRTC','phone_dispatch':False}
            duplicate=conn.execute('SELECT id FROM coordinator.calls WHERE execution_id=%s AND id<>%s',(execution_id,call_id)).fetchone()
            if duplicate:raise HTTPException(409,'Provider execution is already bound to another conversation')
            conn.execute('UPDATE coordinator.calls SET execution_id=%s WHERE id=%s',(execution_id,call_id))
            event(conn,id,'SANDBOX_PROVIDER_EXECUTION_BOUND',{'call_id':str(call_id),'transport':'BOLNA_WEBRTC',
                'phone_dispatch':False,'execution_id':execution_id})
            return {'bound':True,'transport':'BOLNA_WEBRTC','phone_dispatch':False}

    @app.post('/v1/sandbox/incidents/{id}/audio-calls/{call_id}/abort',dependencies=[Depends(operator)])
    def abort_audio(id:UUID,call_id:UUID):
        # Recovery is permitted after consent withdrawal, but cannot rewrite
        # completed evidence or assert that the institution operation failed.
        with db() as conn:
            incident(conn,id,True)
            call=conn.execute("SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s AND mode='SANDBOX_AUDIO' FOR UPDATE",(call_id,id)).fetchone()
            if not call:raise HTTPException(404,'Sandbox conversation not found')
            if call['state']=='COMPLETED':raise HTTPException(409,'Completed conversation evidence is immutable')
            if call['state'] not in {'IN_PROGRESS','FAILED'}:raise HTTPException(409,'Conversation requires explicit review')
            if call['state']=='IN_PROGRESS':
                conn.execute("UPDATE coordinator.calls SET state='FAILED',tool_expires_at=now() WHERE id=%s",(call_id,))
                event(conn,id,'SANDBOX_AUDIO_CALL_ABORTED',{'call_id':str(call_id),'reason':'EXECUTION_INTERRUPTED',
                    'automatic_retry':False,'verified_institution_outcome':False})
            return {'call_id':str(call_id),'state':'FAILED','verified_institution_outcome':False,'requires_reconciliation':True}

    @app.post('/v1/sandbox/incidents/{id}/audio-calls/{call_id}/finish',dependencies=[Depends(operator)])
    def finish_audio(id:UUID,call_id:UUID,body:FinishAudio):
        decoded=[];total=0;target_state='COMPLETED' if body.outcome=='COMPLETED' else 'FAILED'
        for turn in body.turns:
            try:pcm=base64.b64decode(turn.pcm_base64,validate=True)
            except (ValueError,TypeError):raise HTTPException(422,'Valid PCM audio required for every stored turn') from None
            total+=len(pcm)
            if not 0<len(pcm)<=(3200000 if turn.speaker=='participant' else 1280000) or len(pcm)%2 or total>16000000:
                raise HTTPException(413,'Conversation audio exceeds its bounded synthetic archive')
            decoded.append(pcm)
        with db() as conn:
            row=incident(conn,id,True);require_consent(row)
            call=conn.execute("SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s AND mode='SANDBOX_AUDIO' FOR UPDATE",(call_id,id)).fetchone()
            if not call:raise HTTPException(404,'Sandbox conversation not found')
            if call['sandbox_audio_provenance']=='BOLNA_WEBRTC':
                raise HTTPException(409,'Bolna completion requires its provider callback and a separately bound browser archive')
            transcript=[{'speaker':t.speaker,'text':t.text,'audio_sha256':hashlib.sha256(pcm).hexdigest()} for t,pcm in zip(body.turns,decoded)]
            if call['state'] in {'COMPLETED','FAILED'} and call['transcript']:
                if call['state']!=target_state or call['transcript']!=transcript:raise HTTPException(409,'Completed conversation evidence is immutable')
            elif call['state']!='IN_PROGRESS' or call['consent_version']!=row['consent_version']:
                raise HTTPException(409,'Conversation authorization is no longer current')
            else:
                for index,(turn,pcm) in enumerate(zip(body.turns,decoded)):
                    conn.execute('''INSERT INTO coordinator.sandbox_audio_artifacts(id,incident_id,call_id,turn_index,speaker,content_hash,pcm)
                        VALUES(%s,%s,%s,%s,%s,%s,%s)''',(uuid4(),id,call_id,index,turn.speaker,transcript[index]['audio_sha256'],pcm))
                conn.execute("UPDATE coordinator.calls SET state=%s,transcript=%s,tool_expires_at=now() WHERE id=%s",(target_state,Jsonb(transcript),call_id))
                event(conn,id,'SANDBOX_AUDIO_CONVERSATION_ARCHIVED' if target_state=='COMPLETED' else 'SANDBOX_AUDIO_CONVERSATION_INTERRUPTED',{'call_id':str(call_id),'turn_count':len(transcript),'source':'SANDBOX_AUDIO','verified_institution_outcome':False})
            artifacts=conn.execute('SELECT id,turn_index,speaker,content_hash FROM coordinator.sandbox_audio_artifacts WHERE call_id=%s ORDER BY turn_index',(call_id,)).fetchall()
            return {'call_id':str(call_id),'state':target_state,'mode':'SANDBOX_AUDIO','artifacts':artifacts,'verified_institution_outcome':False}

    @app.post('/v1/sandbox/incidents/{id}/audio-calls/{call_id}/browser-archive',dependencies=[Depends(operator)])
    def archive_browser(id:UUID,call_id:UUID,body:BrowserArchive):
        from coordinator.browser_archive import provider_evidence,archive_record
        with db() as conn:
            row=incident(conn,id);require_consent(row)
            call=conn.execute('SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s',(call_id,id)).fetchone()
            if not call:raise HTTPException(404,'Sandbox conversation not found')
            provider_evidence(config,call,body,fetch=False)
        evidence=provider_evidence(config,call,body,fetch=True)
        with db() as conn:
            row=incident(conn,id,True);require_consent(row)
            current=conn.execute('SELECT * FROM coordinator.calls WHERE id=%s AND incident_id=%s FOR UPDATE',(call_id,id)).fetchone()
            if current['consent_version']!=row['consent_version']:raise HTTPException(409,'Permission changed before audio archival')
            provider_evidence(config,current,body,fetch=False)
            return archive_record(conn,current,body,evidence,event)

    @app.get('/v1/sandbox/incidents/{id}/audio-calls/{call_id}/browser-archive',dependencies=[Depends(operator)])
    def browser_archive(id:UUID,call_id:UUID):
        with db() as conn:
            record=conn.execute('''SELECT a.* FROM coordinator.sandbox_browser_archives a
              JOIN coordinator.calls c ON c.id=a.call_id WHERE c.id=%s AND c.incident_id=%s
              AND c.mode='SANDBOX_AUDIO' AND c.sandbox_audio_provenance='BOLNA_WEBRTC' ''',(call_id,id)).fetchone()
        if not record:raise HTTPException(404,'Case-bound browser audio archive is not available')
        return dict(record)|{'transport':'BOLNA_WEBRTC','synthetic':True,'verified_institution_outcome':False}

    @app.get('/v1/sandbox/incidents/{id}/audio/{artifact_id}',dependencies=[Depends(operator)])
    def audio(id:UUID,artifact_id:UUID):
        with db() as conn:
            record=conn.execute('SELECT pcm FROM coordinator.sandbox_audio_artifacts WHERE id=%s AND incident_id=%s',(artifact_id,id)).fetchone()
        if not record:raise HTTPException(404,'Case-bound audio artifact not found')
        output=io.BytesIO()
        with wave.open(output,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(bytes(record['pcm']))
        return Response(output.getvalue(),media_type='audio/wav',headers={'X-Content-Type-Options':'nosniff'})

    @app.get('/v1/sandbox/incidents/{id}/audio-calls/{call_id}/artifacts',dependencies=[Depends(operator)])
    def audio_artifacts(id:UUID,call_id:UUID):
        with db() as conn:
            if not conn.execute("SELECT id FROM coordinator.calls WHERE id=%s AND incident_id=%s AND mode='SANDBOX_AUDIO'",(call_id,id)).fetchone():
                raise HTTPException(404,'Case-bound sandbox conversation not found')
            return conn.execute('SELECT id,turn_index,speaker,content_hash FROM coordinator.sandbox_audio_artifacts WHERE incident_id=%s AND call_id=%s ORDER BY turn_index',(id,call_id)).fetchall()
