import base64
import pytest
from sandbox.participant_dialogue import ParticipantDialogue
from sandbox.participant_model import DeskParticipant,ReadOnlyRoleRecord
from sandbox.bolna_browser_transport import BolnaBrowserConversation


def test_same_question_has_one_generation_and_history_is_not_mutable():
    seen=[]
    session=ParticipantDialogue(lambda h:seen.append(h) or 'English, please.')
    turn=session.prepare(1,'Which language would you prefer?')
    assert session.prepare(1,turn.question) is turn and len(seen)==1
    assert session.history==[]
    history=session.accept_output(turn);history[0]['content']='changed'
    assert session.history[0]['content']==turn.question
    assert session.accept_output(turn)==session.history
    assert session.completed==1
    with pytest.raises(ValueError):session.prepare(1,'May we investigate?')


def test_pending_output_does_not_allow_next_question_or_repeat_institution_action():
    operations=[]
    def reply(history):operations.append('synthetic release');return 'The treating team released it.'
    session=ParticipantDialogue(reply)
    turn=session.prepare(1,'Please follow up with the treating team.')
    with pytest.raises(RuntimeError):session.prepare(2,'Is it uploaded?')
    assert session.prepare(1,turn.question) is turn
    assert operations==['synthetic release']


def test_uncertain_generation_never_automatically_retries_a_write():
    operations=[]
    def reply(history):operations.append('synthetic release');raise TimeoutError('reply lost after operation')
    session=ParticipantDialogue(reply)
    with pytest.raises(TimeoutError):session.prepare(1,'Please release it.')
    with pytest.raises(RuntimeError):session.prepare(1,'Please release it.')
    assert operations==['synthetic release']


def test_same_adaptive_participant_can_be_tested_without_speech_or_judge():
    calls=[]
    record={'synthetic':True,'role':'caregiver','preferred_language':'English','investigation_permission':True}
    def invoke(messages,tools):
        calls.append((messages,tools));return {'text':'English, please.'}
    participant=DeskParticipant(ReadOnlyRoleRecord('caregiver',record),invoke,authorized=lambda:True,brief='Synthetic caregiver')
    session=ParticipantDialogue(participant.reply)
    turn=session.prepare(1,'Which language would you prefer?')
    assert turn.answer=='English, please.'
    assert calls[0][0][-1]=={'role':'user','content':turn.question}
    assert calls[0][1]==[]


def test_speech_failure_does_not_regenerate_participant_reply():
    transport=object.__new__(BolnaBrowserConversation)
    requests=[];generations=[]
    class Actor:
        def reply(self,history):generations.append(history);return 'English, please.'
    def budgeted(operation,body):
        requests.append(operation)
        assert operation=='synthesize'
        if len(requests)==1:raise TimeoutError('speech unavailable')
        return {'pcm_base64':base64.b64encode(b'\0\0'*100).decode()}
    transport._budgeted=budgeted;actor=Actor()
    with pytest.raises(TimeoutError):transport._turn('caregiver',{},[],actor,'AAA=',question='Which language would you prefer?')
    assert transport._text_dialogue.state=='REPLY_READY'
    result=transport._turn('caregiver',{},[],actor,'AAA=',question='Which language would you prefer?')
    assert result[1]=='English, please.' and len(generations)==1
    assert requests==['synthesize','synthesize']
    # This is output preparation only, not a verified audio delivery or case gate.
    assert transport._text_dialogue.completed==1


@pytest.mark.parametrize('history',[[{'role':'assistant','content':'Wrong perspective'}], [{'role':'user','content':'x'},{'role':'assistant','content':''}]])
def test_invalid_history_rejected_before_generation(history):
    with pytest.raises(ValueError):ParticipantDialogue(lambda h:pytest.fail('must not generate'),history=history)


def test_known_topic_disconnect_stops_before_speech_without_a_judge():
    transport=object.__new__(BolnaBrowserConversation)
    transport._budgeted=lambda *a:pytest.fail('No speech, recognition or judge request allowed')
    class Actor:
        def reply(self,history):return 'Yes, you have permission to investigate.'
    with pytest.raises(ValueError,match='different question'):
        transport._turn('caregiver',{},[],Actor(),'AAA=',question='Which language would you prefer?')
    assert transport._text_dialogue.state=='FAILED'


def test_local_generation_session_cannot_be_reused_for_another_role():
    transport=object.__new__(BolnaBrowserConversation)
    transport._budgeted=lambda *a:{'pcm_base64':base64.b64encode(b'\0\0'*100).decode()}
    class Actor:
        def reply(self,history):return 'English, please.'
    actor=Actor()
    transport._turn('caregiver',{},[],actor,'AAA=',question='Which language would you prefer?')
    with pytest.raises(ValueError,match='change roles'):
        transport._turn('tpa',{},[],actor,'AAA=',question='Which language would you prefer?')


def test_failed_later_turn_cannot_replay_a_previous_prepared_answer():
    replies=iter(['English, please.',TimeoutError('lost after possible operation')])
    def reply(history):
        value=next(replies)
        if isinstance(value,Exception):raise value
        return value
    session=ParticipantDialogue(reply)
    session.accept_output(session.prepare(1,'Which language would you prefer?'))
    with pytest.raises(TimeoutError):session.prepare(2,'Please follow up with the hospital.')
    with pytest.raises(RuntimeError):session.prepare(1,'Which language would you prefer?')
    diagnostic=session.diagnostic()
    assert diagnostic['failure_type']=='TimeoutError' and diagnostic['generated_answer'] is None
    assert diagnostic['question']=='Please follow up with the hospital.'
    assert diagnostic['workflow_state_verified'] is False


def test_rejected_reply_remains_inspectable_without_role_facts():
    session=ParticipantDialogue(lambda history:'Yes, permission to investigate is given.')
    with pytest.raises(ValueError):session.prepare(1,'Which language would you prefer?')
    diagnostic=session.diagnostic()
    assert diagnostic['state']=='FAILED' and diagnostic['completed_outputs']==0
    assert diagnostic['generated_answer']=='Yes, permission to investigate is given.'
    assert set(diagnostic)=={'scope','state','completed_outputs','question','generated_answer','failure_type','audio_delivery_verified','workflow_state_verified'}
