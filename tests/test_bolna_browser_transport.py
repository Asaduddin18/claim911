import base64
import json
import subprocess
import sys
import array

from sandbox.bolna_browser_transport import (
    BolnaBrowserConversation,
    caregiver_handoff_explains_next_step,
    caregiver_handoff_closing_note_seen,
    common_call_closing_note_seen,
    caregiver_tool_preamble,
    stop_participant_harness,
    assistant_turn_kind,
    assistant_pcm_has_speech,
)


def test_near_silent_fragment_does_not_trigger_recognition_or_a_scripted_answer():
 import math
 samples=array.array('h',[0]*16000)
 for i in range(1600):samples[i]=int(400*math.sin(i*.1))
 assert not assistant_pcm_has_speech(base64.b64encode(samples.tobytes()).decode())
 for i in range(16000):samples[i]=int(800*math.sin(i*.1))
 assert assistant_pcm_has_speech(base64.b64encode(samples.tobytes()).decode())


def test_natural_twenty_one_second_reply_fits_the_shared_forty_second_audio_contract():
 transport=object.__new__(BolnaBrowserConversation)
 raw=b'\x01\x00'*(16000*21)
 transport._budgeted=lambda operation,body:{'pcm_base64':base64.b64encode(raw).decode()}
 question='Has the signed discharge summary been released?'
 _,_,audio,history=transport._turn('medical_records',{'synthetic':True},[],FakeActor(),'AAA=',question=question)
 assert base64.b64decode(audio)==raw and len(history)==2


class FakeActor:
    def __init__(self):self.history=None
    def reply(self,history):
        self.history=history
        return 'I checked the current record and the signed summary is still waiting for a signature.'


def test_common_hold_announcements_wait_without_answering_for_any_role():
    for text in ('Thank you. I will verify that admission ID now. Please hold on.',
                 'One moment, I am checking the record.', 'Let me verify that.'):
        assert assistant_turn_kind(text)=='wait'
    assert assistant_turn_kind('Let me check. What is the initial reference?')=='participant'
    assert assistant_turn_kind("Please hold on. Thanks, that's all I need for this call.")=='close'


def test_desk_participant_receives_latest_question_as_its_user_turn():
    transport=object.__new__(BolnaBrowserConversation)
    calls=[]
    def budgeted(operation,body):
        calls.append((operation,body))
        if operation=='transcribe':return {'text':'Has the signed discharge summary been released?'}
        return {'pcm_base64':base64.b64encode(b'\x01\x00'*160).decode()}
    transport._budgeted=budgeted
    actor=FakeActor()
    question,answer,audio,history=transport._turn('medical_records',{'synthetic':True,'role':'medical_records'},[],actor,'AAA=')
    assert question=='Has the signed discharge summary been released?'
    assert actor.history==[{'role':'user','content':question}]
    assert history==[{'role':'user','content':question},{'role':'assistant','content':answer}]
    assert audio==base64.b64encode(b'\x01\x00'*160).decode()
    assert [operation for operation,_ in calls]==['transcribe','synthesize']


def test_caregiver_model_history_is_inverted_for_participant_perspective():
    transport=object.__new__(BolnaBrowserConversation)
    transport._budgeted=lambda operation,body: (
        {'text':'Would you like me to explain the final patient share?'} if operation=='transcribe'
        else {'text':'Please explain what is verified and what remains due.'} if operation=='reply'
        else {'pcm_base64':base64.b64encode(b'\x02\x00'*160).decode()})
    question,answer,_,history=transport._turn('caregiver',{'synthetic':True,'role':'caregiver'},[],None,'AAA=')
    assert question.startswith('Would you like')
    assert history==[{'role':'assistant','content':question},{'role':'user','content':answer}]


def test_provider_transcript_supplies_the_real_question_without_an_extra_recognition_request():
    transport=object.__new__(BolnaBrowserConversation)
    calls=[]
    def budgeted(operation,body):
        calls.append(operation)
        assert operation=='synthesize'
        return {'pcm_base64':base64.b64encode(b'\x01\x00'*160).decode()}
    transport._budgeted=budgeted
    actor=FakeActor()
    question='Has the signed discharge summary been released?'
    actual,_,_,_=transport._turn('medical_records',{'synthetic':True},[],actor,'AAA=',question=question)
    assert actual==question and actor.history[-1]['content']==question
    assert calls==['synthesize']


def test_intake_hangup_requires_the_report_saved_by_the_current_call():
    class Connection:
        def __init__(self,payload):self.payload=payload;self.queries=[]
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def execute(self,sql,params):
            self.queries.append((sql,params))
            row={'id':'call-1'} if 'SELECT id FROM coordinator.calls' in sql else self.payload
            return type('Rows',(),{'fetchone':lambda _:row})()
    transport=object.__new__(BolnaBrowserConversation)
    conn=Connection({'payload':{'purpose':'CAREGIVER_INTAKE','operation':'REPORT_UPDATE','support_status':'REPORTED_FROM_CALL'}})
    transport.db=lambda:conn
    assert transport._caregiver_update_saved('incident-1') is True
    assert "sandbox_audio_provenance='BOLNA_WEBRTC'" in conn.queries[0][0]
    assert conn.queries[1][1]==('incident-1','call-1')
    transport.db=lambda:Connection({'payload':{'purpose':'CAREGIVER_INTAKE','operation':'REPORT_QUERY','support_status':'REPORTED_FROM_CALL'}})
    assert transport._caregiver_update_saved('incident-1') is False


def test_caregiver_tool_preamble_is_not_mistaken_for_the_final_handoff():
    assert caregiver_tool_preamble('Let me check the case record.') is True
    assert caregiver_tool_preamble('Thanks, I understand.') is False
    assert caregiver_handoff_explains_next_step('Let me check the case record.') is False


def test_caregiver_handoff_requires_the_next_step_and_responsible_parties():
    assert caregiver_handoff_explains_next_step(
        'Claim911 will check with the hospital and insurer, then show you what they confirm.'
    ) is True
    assert caregiver_handoff_explains_next_step('Thanks, I understand. Claim911 has recorded this.') is False


def test_intake_closes_only_after_bolnas_explicit_closing_note():
    assert caregiver_handoff_closing_note_seen(
        'Thanks, I understand. Claim911 will check with the hospital and insurer, then show you what they confirm.'
    ) is True
    assert caregiver_handoff_closing_note_seen('Let me check the case record.') is False
    assert caregiver_handoff_closing_note_seen(
        'Claim911 will check with the hospital and insurer.'
    ) is False


def test_common_call_closing_note_is_shared_by_every_participant_role():
    assert common_call_closing_note_seen("Thanks, that's all I need for this call.") is True
    assert common_call_closing_note_seen('Let me check the case record.') is False


def test_spoken_closing_accepts_transcription_spacing_and_contraction_expansion():
    assert caregiver_handoff_closing_note_seen('Claim 911 will check with the hospital and insurer, then show you what they confirm.')
    assert caregiver_handoff_closing_note_seen('Claim 9 1 1 will check with the hospital and insurer, then show you what they confirm.')
    for text in ["Thanks, that's all I need for this call.",'Thanks, that is all I need for this call.','Thanks, that’s all I need for this call.']:
        assert common_call_closing_note_seen(text)
    assert not common_call_closing_note_seen('Thanks, that is all I need to check first.')


def test_media_control_is_shared_and_does_not_require_a_caregiver_specific_sentence():
    assert assistant_turn_kind('Let me check the case record.')=='wait'
    assert assistant_turn_kind('The uploaded document has been checked. Thanks, that is all I need for this call.')=='close'
    assert assistant_turn_kind('The tool failed and the update is not saved. Thanks, that is all I need for this call.')=='close'
    assert assistant_turn_kind('Could you confirm the document revision?')=='participant'


def test_failed_participant_allows_browser_cleanup_before_forced_kill():
    child=subprocess.Popen([sys.executable,'-u','-c',
        'import sys,json; request=json.loads(sys.stdin.readline()); print(json.dumps(request),flush=True)'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    stop_participant_harness(child,'medical_records',timeout=2)
    assert child.returncode==0
    assert json.loads(child.stdout.read())=={'type':'abort','role':'medical_records'}


def test_unresponsive_participant_is_still_bounded():
    child=subprocess.Popen([sys.executable,'-u','-c','import time; time.sleep(60)'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    stop_participant_harness(child,'billing',timeout=0.05)
    assert child.poll() is not None
