"""Bolna browser workflow transport with trusted role-bounded participants.

Bolna owns every assistant turn and its scoped Claim911 tools. This host-side
controller supplies synthetic caller audio and role-specific institution
participants, then submits captured audio to the existing provider-evidence
archive for independent verification.
"""
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
import array
from pathlib import Path
from uuid import uuid4

from experience.presentation import financials
from sandbox.actors import initial_knowledge
from sandbox.participant_model import DeskParticipant, ScenarioDeskParticipant, CaregiverRecord
from sandbox.participant_dialogue import ParticipantDialogue
from sandbox.scripted_desks import ScriptedDesk
from sandbox.bolna_participant import natural_response_messages, MAX_PCM_BYTES, MAX_TURN_TEXT
from sandbox.spend import reserve, settle
from sandbox.speech_costs import current_speech_proof
from sandbox.dialogue_quality import evaluate_dialogue
from coordinator.voice_contracts import COMMON_CALL_CLOSING_NOTE,normalize_spoken_text


def assistant_pcm_has_speech(raw):
    """Ignore isolated near-silent media fragments, never infer spoken content.

    At least 160 ms of 20 ms frames must contain audible signal. A held
    fragment stays in the audio archive and cannot satisfy a checkpoint.
    """
    pcm=base64.b64decode(raw,validate=True)
    if not pcm or len(pcm)%2 or len(pcm)>1_280_000:
        raise ValueError('Bounded assistant PCM required')
    samples=array.array('h');samples.frombytes(pcm)
    if __import__('sys').byteorder!='little':samples.byteswap()
    active=0
    for at in range(0,len(samples),320):
        frame=samples[at:at+320]
        if len(frame)==320 and sum(v*v for v in frame)/320>=(32768*.002)**2:
            active+=1
    return active>=8


def stop_participant_harness(process,role,*,timeout=30):
    """Let the browser end its session and save diagnostics before hard cleanup."""
    if process.poll() is not None:return
    try:
        process.stdin.write(json.dumps({'type':'abort','role':role})+'\n')
        process.stdin.flush();process.stdin.close()
    except (OSError,ValueError):pass
    try:process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill();process.wait(timeout=10)



def caregiver_tool_preamble(text):
    normalized=normalize_spoken_text(text)
    return normalized=='let me check the case record'


def caregiver_handoff_explains_next_step(text):
    normalized=normalize_spoken_text(text)
    return bool(
        re.search(r'claim\s*911.{0,60}(continue|check|coordinate|contact)',normalized)
        and re.search(r'\b(hospital|insurer|insurance)\b',normalized)
    )


def caregiver_handoff_closing_note_seen(text):
    normalized=normalize_spoken_text(text)
    return 'claim911 will check with the hospital and insurer then show you what they confirm' in normalized


def common_call_closing_note_seen(text):
    normalized=normalize_spoken_text(text)
    expected=normalize_spoken_text(COMMON_CALL_CLOSING_NOTE)
    return expected in normalized


def assistant_turn_kind(text):
    if common_call_closing_note_seen(text):return 'close'
    if caregiver_tool_preamble(text):return 'wait'
    # A hold announcement is a continuation of the assistant's turn, not a
    # request for institution facts. A real question still takes precedence.
    normalized=normalize_spoken_text(text)
    if '?' not in str(text) and re.search(r'\b(?:please hold(?: on)?|one moment|give me a moment|let me (?:check|verify|look))\b',normalized):
        return 'wait'
    return 'participant'


class BolnaBrowserConversation:
    PURPOSE_TURN_LIMITS={
        'CAREGIVER_INTAKE':4,'HOSPITAL_REFERENCE_DISCOVERY':8,'QUERY_DISCOVERY':12,
        'BILLING_DOCUMENT':6,'RECORDS_DOCUMENT':6,'IMPLANT_DOCUMENT':6,
        'PACKET_SUBMISSION':6,'TPA_QUERY_FOLLOWUP':6,'INSURER_FOLLOWUP':6,
        'DISCHARGE_FOLLOWUP':6,'CAREGIVER_COMPLEX_UPDATE':6,
    }
    def __init__(self, *, core, services, provider, db, run_id, sandbox_profile,
                 provider_profile, browser_url, node, harness_path, runtime_root,
                 max_turns=12, participant_mode='adaptive',spend_phase='development'):
        self.core=core;self.services=services;self.provider=provider;self.db=db
        self.run_id=str(run_id);self.sandbox_profile=Path(sandbox_profile)
        self.provider_profile=Path(provider_profile);self.browser_url=browser_url
        self.node=node;self.harness_path=Path(harness_path);self.runtime_root=Path(runtime_root)
        if participant_mode not in {'scripted','adaptive'}:raise ValueError('Known synthetic participant mode required')
        self.participant_mode=participant_mode
        if spend_phase not in {'development','rehearsal','reserve'}:raise ValueError('Known voice evaluation cost phase required')
        self.spend_phase=spend_phase
        self.max_turns=max_turns;self.reports=[];self._counter=0
        self._active_authorized=None
        if not 1<=max_turns<=12:raise ValueError('Bounded Bolna participant turns required')

    def _budgeted(self,operation,body):
        if self._active_authorized and not self._active_authorized():
            raise PermissionError('Current synthetic run permission is no longer active')
        self._counter+=1;request_id=str(uuid4())
        with self.db() as conn:
            hold=reserve(conn,request_id=request_id,run_id=self.run_id,phase=getattr(self,'spend_phase','development'),
                         operation='bolna-participant-'+operation,maximum_micro=20_000 if operation=='reply' else 100_000)
        if not hold['new_reservation']:
            raise RuntimeError('Participant provider operation requires reconciliation before retry')
        successful=False;result=None
        try:
            result=self.provider.request(operation,body,
                reservation_id=request_id if operation=='reply' else None)
            successful=True
        finally:
            proof=None
            if successful and operation in {'transcribe','synthesize'}:
                try:proof=current_speech_proof(self.provider_profile,self.runtime_root/'azure/free-speech-evidence.json')
                except (OSError,ValueError,KeyError):pass
            with self.db() as conn:
                settle(conn,request_id,confirmed_charge_micro=0 if proof else None)
                if successful and operation=='reply':
                    from sandbox.model_usage import store_usage
                    store_usage(conn,request_id,result)
                if proof:
                    from psycopg.types.json import Jsonb
                    conn.execute('UPDATE coordinator.sandbox_spend SET cost_evidence=%s WHERE request_id=%s',(Jsonb(proof),request_id))
        if self._active_authorized and not self._active_authorized():
            raise PermissionError('Synthetic run permission changed during participant provider work')
        return result

    def _reply(self,role,record,history,actor=None):
        if actor is not None:
            return actor.reply(history)
        messages=natural_response_messages(role,record,history)
        response=self._budgeted('reply',{'messages':messages,'tools':[]})
        text=response.get('text')
        if not isinstance(text,str) or not text.strip() or len(text)>MAX_TURN_TEXT:
            raise ValueError('Synthetic participant response is outside its limit')
        return text.strip()

    def _transcribe_assistant(self,raw):
        self._last_turn_stage='recognition'
        audio=base64.b64decode(raw,validate=True)
        if not 0<len(audio)<=1_280_000 or len(audio)%2:
            raise ValueError('Bolna assistant audio exceeds the bounded PCM contract')
        recognized=self._budgeted('transcribe',{'pcm_base64':base64.b64encode(audio).decode(),
                                                  'language':'en'})
        question=recognized.get('text') if isinstance(recognized,dict) else None
        if not isinstance(question,str) or not question.strip() or len(question)>MAX_TURN_TEXT:
            raise ValueError('Bolna assistant speech could not be understood clearly')
        confidence=recognized.get('confidence') if isinstance(recognized,dict) else None
        self._last_asr_evidence={'provider':recognized.get('provider','unknown'),
            'confidence':confidence,'alternatives':recognized.get('alternatives',[])}
        return question.strip()

    def _turn(self,role,record,history,actor,raw,*,question=None):
        self._last_participant_evidence=None
        audio=base64.b64decode(raw,validate=True)
        if not 0<len(audio)<=1_280_000 or len(audio)%2:
            raise ValueError('Bolna assistant audio exceeds the bounded PCM contract')
        question=question or self._transcribe_assistant(raw)
        # Keep text generation independent of recognition and synthesis. A failed
        # speech operation can reuse this prepared reply without repeating a
        # participant model request or its institution operation.
        session=getattr(self,'_text_dialogue',None)
        if session is not None and self._text_dialogue_identity!=(role,id(actor)):
            raise ValueError('Participant session cannot change roles or actors')
        if session is None:
            self._text_dialogue_identity=(role,id(actor))
            canonical_history=history if actor is not None else [
                {'role':'user' if m['role']=='assistant' else 'assistant','content':m['content']} for m in history]
            def reply(messages):
                actual=messages if actor is not None else [
                    {'role':'assistant' if m['role']=='user' else 'user','content':m['content']} for m in messages]
                return self._reply(role,record,actual,actor)
            session=ParticipantDialogue(reply,history=canonical_history)
            self._text_dialogue=session
        self._last_turn_stage='participant_generation'
        prepared=session.prepare(len(history)//2+1,question)
        answer=prepared.answer
        self._last_participant_evidence={'scope':'GENERATED_REPLY_ONLY','role':role,'text':answer,'speech_state':'requested'}
        self._last_turn_stage='participant_synthesis'
        from sandbox.spoken_identifiers import pronounce_role_identifiers
        spoken_answer=pronounce_role_identifiers(answer,record)
        speech=self._budgeted('synthesize',{'text':spoken_answer,'language':'en','speaker':role})
        self._last_turn_stage='participant_audio_validation'
        pcm=base64.b64decode(speech['pcm_base64'],validate=True)
        self._last_participant_evidence.update(speech_state='returned',duration_ms=len(pcm)/32)
        if not 0<len(pcm)<=MAX_PCM_BYTES or len(pcm)%2:
            raise ValueError('Synthetic participant audio exceeds the bounded PCM contract')
        final_history=session.accept_output(prepared)
        if actor is None:final_history=[{'role':'assistant' if m['role']=='user' else 'user','content':m['content']} for m in final_history]
        return question,answer,base64.b64encode(pcm).decode(),final_history

    def _wait_for_provider_finalization(self,call_id,execution_id,transcript_hash):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if self._active_authorized and not self._active_authorized():
                raise PermissionError('Run permission changed before provider evidence was finalized')
            with self.db() as conn:
                call=conn.execute('''SELECT state,execution_id,transcript,recording_consent
                    FROM coordinator.calls WHERE id=%s''',(call_id,)).fetchone()
            if not call:raise RuntimeError('Bolna conversation disappeared before archive verification')
            if str(call['execution_id'])!=str(execution_id):
                raise PermissionError('Bolna execution identity changed before archive verification')
            if call['state'] in {'FAILED','NO_ANSWER','BUSY','CANCELLED'}:
                raise RuntimeError('Bolna provider execution ended without a completed conversation')
            if call['state']=='COMPLETED':
                saved='\n'.join(turn['text'] for turn in call['transcript']
                    if turn.get('speaker')=='provider_transcript')
                if saved and hashlib.sha256(saved.encode()).hexdigest()==transcript_hash:
                    if not call['recording_consent']:
                        raise PermissionError('Recording permission is missing for the provider archive')
                    return
                if saved:raise PermissionError('Coordinator transcript differs from the provider transcript')
            time.sleep(0.5)
        raise TimeoutError('The finalized Bolna callback did not reach the sandbox coordinator')

    def _caregiver_update_saved(self,incident_id):
        """End intake only after the exact Bolna call saved its caregiver report."""
        with self.db() as conn:
            call=conn.execute("""SELECT id FROM coordinator.calls
                WHERE incident_id=%s AND purpose='CAREGIVER_INTAKE' AND mode='SANDBOX_AUDIO'
                  AND sandbox_audio_provenance='BOLNA_WEBRTC'
                ORDER BY created_at DESC LIMIT 1""",(incident_id,)).fetchone()
            if not call:return False
            report=conn.execute("""SELECT payload FROM coordinator.events
                WHERE incident_id=%s AND type='CAREGIVER_INTAKE_REPORTED'
                  AND payload->>'call_id'=%s ORDER BY sequence DESC LIMIT 1""",
                (incident_id,str(call['id']))).fetchone()
        payload=report.get('payload') if report else None
        return bool(payload and payload.get('purpose')=='CAREGIVER_INTAKE'
                    and payload.get('operation')=='REPORT_UPDATE'
                    and payload.get('support_status')=='REPORTED_FROM_CALL')

    def __call__(self,*,purpose,role,operations,followup,authorized):
        if not authorized():raise PermissionError('Current synthetic run permission required')
        self._active_authorized=authorized
        turn_limit=min(self.max_turns,self.PURPOSE_TURN_LIMITS.get(purpose,4))
        snapshot=self.services.snapshot();incident=snapshot['incident'];incident_id=str(incident['id'])
        if role=='caregiver':
            record={'synthetic':True,'role':'caregiver',
                    'known_facts':['This is a synthetic discharge coordination rehearsal.',
                                   'The family is ready to leave but was told final insurance clearance is pending.',
                                   'The family does not know which document or approval is missing.',
                                   'The caregiver wants Claim911 to check with the hospital and insurer.'],
                    'verified_update':(snapshot.get('complex_workflow') or {}).get('caregiver_summary'),
                    'verified_financials':financials(snapshot.get('complex_workflow'))}
            actor=(DeskParticipant(CaregiverRecord(record),self._invoke,authorized=authorized,
                    brief='A synthetic caregiver seeking help with a delayed discharge.')
                   if self.participant_mode=='adaptive' else ScriptedDesk(role,record))
        else:
            actor=self.services.actor(role)
            desk=actor.execute('read_status')
            record={'synthetic':True,'role':role,'desk_record':desk}
            if purpose=='HOSPITAL_REFERENCE_DISCOVERY':
                self.services._upload('hospital-reference-slip.json',{
                    'kind':'hospital_reference_slip','case_id':self.services.case_id,
                    'patient_id':desk['patient_id'],'admission_id':desk['admission_id'],
                    'references':desk['references'],'synthetic':True})
            elif purpose=='QUERY_DISCOVERY':
                q=desk['references']
                self.services._upload('claims-query-slip.json',{
                    'kind':'claims_query_slip','case_id':self.services.case_id,
                    'patient_id':desk['patient_id'],'final_reference':q['final_request'],
                    'details':{'query_reference':q['query'],'claim_reference':q['claim'],
                      'admission_id':desk['admission_id'],'enhancement_reference':q['enhancement'],
                      'received_at':desk['received_at'],'required_documents':desk['required_documents'],
                      'enhancement_linked':desk['enhancement_linked']}})
            tracked={}
            for name,operation in operations.items():
                def wrap(operation=operation):
                    if not authorized():raise PermissionError('Run permission changed during participant turn')
                    return operation()
                tracked[name]=wrap
            if self.participant_mode=='adaptive':
                actor=DeskParticipant(actor,self._invoke,authorized=authorized,
                    brief=initial_knowledge(role)['knowledge'],operations=tracked)
            else:
                actor=ScenarioDeskParticipant(role,desk,tracked,authorized=authorized,
                    read_record=lambda desk_actor=actor:desk_actor.execute('read_status'))

        archive_dir=self.runtime_root/'sandbox'/'bolna-archives'
        archive_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        archive_path=archive_dir/(self.run_id+'-'+uuid4().hex+'.json')
        report_path=archive_path.with_suffix('.report.json')
        stderr_path=archive_path.with_suffix('.stderr')
        recognition_path=archive_path.with_suffix('.recognition.jsonl')
        harness_profile_path=archive_path.with_suffix('.harness-profile.json')
        harness_profile_path.write_text(json.dumps({'environment':'sandbox','live_calls_enabled':False}))
        os.chmod(harness_profile_path,0o600)
        harness_token='sbxh_'+secrets.token_urlsafe(32)
        with self.db() as conn:
            conn.execute('INSERT INTO coordinator.sandbox_harness_tokens(token_hash,run_id) VALUES(%s,%s)',
                (hashlib.sha256(harness_token.encode()).hexdigest(),self.run_id))
        # The browser harness gets only the runtime paths it needs. In
        # particular, do not expose provider, Bolna, cloud, broker or operator credentials.
        environment={key:os.environ[key] for key in ('PATH','HOME','TMPDIR','LANG') if key in os.environ}
        environment.update({
            'CLAIM911_SANDBOX_BROWSER_URL':self.browser_url,
            'CLAIM911_SANDBOX_PROFILE':str(harness_profile_path),
            'CLAIM911_SANDBOX_HARNESS_TOKEN':harness_token,
            'CLAIM911_REPORT_PATH':str(report_path),
            'CLAIM911_RUN_ID':self.run_id,
            'CLAIM911_PARTICIPANT_ROLE':role,
            'CLAIM911_PARTICIPANT_MODE':'scenario-scripted' if self.participant_mode=='scripted' else 'adaptive',
            'CLAIM911_WORKFLOW_PURPOSE':purpose,
            'CLAIM911_PARTICIPANT_RPC':'1',
            'CLAIM911_ARCHIVE_PATH':str(archive_path),
            'CLAIM911_MAX_PARTICIPANT_TURNS':str(turn_limit),
            'PLAYWRIGHT_BROWSERS_PATH':str(self.runtime_root/'sandbox'/'playwright'),
        })
        self._last_turn_stage='session_setup'
        self._last_participant_evidence=None
        self._text_dialogue=None  # A fresh role-bound session for every call.
        history=[];dialogue=[];terminal_assistant_closing=None
        assistant_audio_turn=0
        assistant_parts=[]
        consecutive_waits=0
        media_fragments=0
        with open(stderr_path,'w',encoding='utf-8') as stderr:
            os.fchmod(stderr.fileno(),0o600)
            process=subprocess.Popen([self.node,str(self.harness_path)],stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=stderr,text=True,encoding='utf-8',bufsize=1,
                env=environment)
            try:
                for line in process.stdout:
                    if len(line)>1_800_000:raise RuntimeError('Bolna browser participant message exceeded its bound')
                    message=json.loads(line)
                    if message.get('type')=='assistant_audio':
                        assistant_audio_turn+=1
                        if message.get('turn')!=assistant_audio_turn or message.get('role')!=role:
                            raise RuntimeError('Bolna participant turn identity changed')
                        raw=message.get('pcm_base64','')
                        if not assistant_pcm_has_speech(raw):
                            media_fragments+=1
                            if media_fragments>2:
                                raise RuntimeError('Assistant audio remained inaudible; no participant answer was inferred')
                            process.stdin.write(json.dumps({'type':'continue_audio','turn':message['turn'],
                                'role':role},separators=(',',':'))+'\n');process.stdin.flush()
                            continue
                        media_fragments=0
                        question_source=message.get('assistant_text_source')
                        provider_text=message.get('assistant_text')
                        if (question_source=='bolna_provider_transcript' and isinstance(provider_text,str)
                                and provider_text.strip() and len(provider_text)<=MAX_TURN_TEXT):
                            question=provider_text.strip()
                        else:
                            question=self._transcribe_assistant(raw)
                            question_source='live_audio_transcription'
                        with recognition_path.open('a',encoding='utf-8') as journal:
                            os.fchmod(journal.fileno(),0o600)
                            journal.write(json.dumps({'turn':message['turn'],'role':role,'purpose':purpose,
                                'text':question,'source':question_source,
                                'recognition':getattr(self,'_last_asr_evidence',None) if question_source=='live_audio_transcription' else None})+'\n')
                        self._last_turn_stage='assistant_media_control'
                        caregiver_intake=purpose=='CAREGIVER_INTAKE'
                        assistant_parts.append(question)
                        closing=' '.join(assistant_parts)
                        if assistant_turn_kind(closing)=='close':
                            # Ending the media session does not complete the case.
                            # Archive, report and checkpoint checks remain independent.
                            terminal_assistant_closing=closing
                            saved=caregiver_intake and self._caregiver_update_saved(incident_id)
                            process.stdin.write(json.dumps({'type':'end_call','turn':message['turn'],
                                'role':role,'assistant_text':closing,'report_saved':saved,
                                'close_confirmed':True},separators=(',',':'))+'\n');process.stdin.flush()
                            break
                        waiting=assistant_turn_kind(question)=='wait'
                        if waiting or (caregiver_intake and self._caregiver_update_saved(incident_id)):
                            consecutive_waits+=1
                            if consecutive_waits>3:
                                raise RuntimeError('Assistant did not progress beyond bounded hold announcements; human review required')
                            process.stdin.write(json.dumps({'type':'continue_audio','turn':message['turn'],
                                'role':role},separators=(',',':'))+'\n');process.stdin.flush()
                            continue
                        if len(dialogue)>=turn_limit:
                            raise RuntimeError('The bounded participant reply limit was reached before an explicit close')
                        assistant_parts=[]
                        consecutive_waits=0
                        question,answer,pcm,history=self._turn(role,record,history,actor,raw,question=question)
                        self._last_turn_stage='participant_audio_handoff'
                        process.stdin.write(json.dumps({'type':'participant_audio','turn':message['turn'],
                            'role':role,'assistant_text':question,'participant_text':answer,
                            'question_source':question_source,
                            'pcm_base64':pcm},separators=(',',':'))+'\n');process.stdin.flush()
                        dialogue.append({'assistant_text':question,'expected_assistant_question':question,
                            'question_source':question_source or 'live_audio_transcription','participant_text':answer,'role':role,
                            'recognition':getattr(self,'_last_asr_evidence',None) if question_source=='live_audio_transcription' else None})
                    elif message.get('type')=='completed':
                        summary=message.get('summary') or {}
                        if summary.get('errors') or not summary.get('connected') or not summary.get('ended'):
                            raise RuntimeError('Bolna browser conversation did not complete its required checks')
                        break
                    else:raise RuntimeError('Bolna browser harness returned an unknown protocol message')
                process.stdin.close()
                # The child allows 30 seconds for provider finalization, then
                # flushes the screen recording. Media is already disconnected.
                code=process.wait(timeout=75)
                if code!=0:raise RuntimeError('Bolna browser conversation failed its provider or dialogue checks')
            except Exception as exc:
                stop_participant_harness(process,role)
                failed={}
                if report_path.exists():
                    try:
                        parsed=json.loads(report_path.read_text())
                        if isinstance(parsed,dict):failed=parsed
                    except (OSError,ValueError):pass
                session=getattr(self,'_text_dialogue',None)
                diagnostic={'scope':'FAILED_SYNTHETIC_VOICE_ATTEMPT','archived':False,'run_id':self.run_id,
                    'role':role,'purpose':purpose,'stage':getattr(self,'_last_turn_stage','unknown'),
                    'failure_type':type(exc).__name__,
                    'call_id':failed.get('call_id'),'execution_id':failed.get('provider_execution_id'),
                    'errors':failed.get('errors',[]),'captured_assistant_audio':failed.get('captured_assistant_audio',[]),
                    'failed_audio':failed.get('failed_audio'),'sandbox_report':str(report_path),
                    'participant_reply_diagnostic':getattr(self,'_last_participant_evidence',None),
                    'text_session':session.diagnostic() if session else None,
                    'assistant':'Bolna','phone_dispatch':False,'checkpoint_eligible':False}
                self.reports.append(diagnostic)
                # Preserve the original failure even if browser cleanup produced
                # no report. This diagnostic cannot advance a workflow gate.
                try:
                    with archive_path.with_suffix('.failure.json').open('x',encoding='utf-8') as journal:
                        os.fchmod(journal.fileno(),0o600)
                        json.dump(diagnostic,journal,indent=2)
                except OSError:pass
                raise
        if not dialogue or not archive_path.exists():
            raise RuntimeError('Bolna browser conversation did not produce a verified audio archive')
        if purpose=='CAREGIVER_INTAKE' and len(dialogue)!=2:
            raise RuntimeError('Caregiver concern requires one explicit confirmation before intake evidence can pass')
        archived=json.loads(archive_path.read_text())
        report=json.loads(report_path.read_text())
        if report.get('run_id')!=self.run_id or report.get('participant_role')!=role:
            raise PermissionError('Bolna audio archive is bound to another run or role')
        call_id=report.get('call_id');execution_id=report.get('provider_execution_id')
        if not call_id or not execution_id:raise RuntimeError('Bolna provider execution is not bound to its case')
        # The archive retains actual provider text. The judge checks recognition
        # meaning and conversation quality, and has no institution tools.
        from sandbox.dialogue_evidence import dialogue_facts
        quality_facts=dialogue_facts(record,self.services.snapshot(),getattr(actor,'audit',()))
        quality=evaluate_dialogue(
            transcript=[{'speaker':t['speaker'],'text':t['text']} for t in archived['turns']],
            participant_role=role,known_facts=quality_facts,invoke=self._invoke,
            assistant_provider='BOLNA_WEBRTC',
            expected_exchanges=[{k:t[k] for k in ('assistant_text','participant_text')} for t in dialogue])
        report['semantic_dialogue_evaluation']=quality
        report_path.write_text(json.dumps(report,indent=2)+'\n')
        os.chmod(report_path,0o600)
        if not quality['conversation_quality_passed']:
            self.reports.append({'archived':False,'role':role,'purpose':purpose,
                'call_id':call_id,'semantic_dialogue_evaluation':quality,'sandbox_report':str(report_path)})
            raise RuntimeError('Bolna conversation failed semantic quality or recognition alignment; review required')
        self._wait_for_provider_finalization(call_id,execution_id,archived['provider_transcript_sha256'])
        response=self.core.post(f'/v1/sandbox/incidents/{incident_id}/audio-calls/{call_id}/browser-archive',json=archived)
        response.raise_for_status()
        if response.json().get('archived') is not True:
            raise RuntimeError('Independent Bolna audio archive verification failed')
        result={'archived':True,'call_id':call_id,'execution_id':execution_id,
                'provenance':'BOLNA_WEBRTC','assistant':'Bolna','role':role,
                'purpose':purpose,'followup':bool(followup),'participant_mode':'SEEDED_SCENARIO_ROLE_ACTOR' if self.participant_mode=='scripted' else 'ADAPTIVE_ROLE_ACTOR',
                'dialogue':dialogue,'terminal_assistant_closing':terminal_assistant_closing,
                'caregiver_update_saved':(purpose=='CAREGIVER_INTAKE' and bool(
                    terminal_assistant_closing and self._caregiver_update_saved(incident_id))),
                'assistant_config_sha256':archived['assistant_config_sha256'],
                'tool_audit':getattr(actor,'audit',[]),'phone_dispatch':False,
                'provider_archive':response.json(),'sandbox_report':str(report_path)}
        result['semantic_dialogue_evaluation']=quality
        self.reports.append(result)
        self._active_authorized=None
        return result

    def _invoke(self,messages,tools,*,output_schema=None):
        if self._active_authorized and not self._active_authorized():
            raise PermissionError('Current synthetic run permission is no longer active')
        request_id=str(uuid4())
        with self.db() as conn:
            hold=reserve(conn,request_id=request_id,run_id=self.run_id,phase=getattr(self,'spend_phase','development'),
                         operation='bolna-institution-participant',maximum_micro=20_000)
        if not hold['new_reservation']:
            raise RuntimeError('Institution participant model request requires reconciliation')
        body={'messages':messages,'tools':tools}
        if output_schema is not None:body['output_schema']=output_schema
        try:result=self.provider.request('reply',body,reservation_id=request_id)
        finally:
            with self.db() as conn:settle(conn,request_id)
        # The provider enforces <=24 KB input and 2,048 output tokens. USD .02
        # is a conservative hold for the pinned GPT-5-mini deployment, not a
        # claimed invoice. Retain actual usage without releasing uncertain cost.
        from sandbox.model_usage import store_usage
        with self.db() as conn:store_usage(conn,request_id,result)
        if self._active_authorized and not self._active_authorized():
            raise PermissionError('Synthetic run permission changed during desk reasoning')
        return result
