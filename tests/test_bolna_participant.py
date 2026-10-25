import pytest

from sandbox.bolna_participant import BolnaParticipant,natural_response_messages
from sandbox.scripted_desks import ScriptedDesk


class Speech:
    def __init__(self):
        self.speakers = []

    def transcribe(self, pcm, language):
        assert pcm == b'\x01\x00' * 80
        assert language == 'en'
        return {'text': 'Can you confirm what is holding up discharge?'}

    def synthesize(self, text, language, *, speaker):
        self.speakers.append(speaker)
        assert text == 'The family is ready to leave, but the hospital says final insurance clearance is pending and we need help finding out why.'
        assert language == 'en'
        return b'\x02\x00' * 80


def test_participant_answers_the_latest_bolna_turn_in_its_own_voice():
    speech = Speech()
    record = {'synthetic': True, 'deposit_inr': 30000}
    actor = ScriptedDesk('caregiver', record)
    participant = BolnaParticipant(role='caregiver', record=record, speech=speech, actor=actor)

    result = participant.answer_audio(b'\x01\x00' * 80)

    assert result['assistant_text'] == 'Can you confirm what is holding up discharge?'
    assert 'hospital says final insurance clearance is pending' in result['participant_text']
    assert result['participant_role'] == 'caregiver'
    assert result['participant_audio_pcm'] == b'\x02\x00' * 80
    assert result['workflow_write'] is False
    assert result['checkpoint_eligible'] is False
    assert speech.speakers == ['caregiver']
    assert participant.history == [
        {'role': 'assistant', 'content': result['assistant_text']},
        {'role': 'user', 'content': result['participant_text']},
    ]


@pytest.mark.parametrize('role', ['unknown', 'operator', 'sandbox'])
def test_participant_rejects_non_scenario_roles(role):
    with pytest.raises(ValueError):
        BolnaParticipant(role=role, record={}, speech=Speech(), actor=object())


def test_participant_rejects_records_without_synthetic_attestation():
    with pytest.raises(ValueError, match='synthetic role record'):
        BolnaParticipant(role='caregiver', record={'deposit_inr': 30000}, speech=Speech(), actor=object())


def test_participant_rejects_unbounded_or_non_pcm_audio():
    record = {'synthetic': True}
    participant = BolnaParticipant(role='caregiver', record=record, speech=Speech(), actor=ScriptedDesk('caregiver', record))
    with pytest.raises(ValueError):
        participant.answer_audio(b'')
    with pytest.raises(ValueError):
        participant.answer_audio(b'\x00')


def test_participant_fails_closed_when_transcription_is_not_a_turn():
    class UnclearSpeech(Speech):
        def transcribe(self, pcm, language):
            return {'text': ''}

    record = {'synthetic': True}
    participant = BolnaParticipant(role='caregiver', record=record, speech=UnclearSpeech(), actor=ScriptedDesk('caregiver', record))
    with pytest.raises(ValueError, match='did not produce'):
        participant.answer_audio(b'\x01\x00' * 80)


def test_natural_participant_sees_role_facts_and_conversation_from_its_own_perspective():
    record={'synthetic':True,'role':'medical_records','documents':[{'kind':'signed_discharge_summary','ready':False}]}
    history=[
        {'role':'assistant','content':'The summary is still awaiting a signature. Can you check with the treating team?'},
        {'role':'user','content':'I can follow up with them.'},
    ]

    messages=natural_response_messages('medical_records',record,history)

    assert messages[0]['role']=='developer'
    assert 'medical_records' in messages[0]['content']
    assert 'ready' in messages[0]['content']
    assert messages[1:]==[
        {'role':'user','content':history[0]['content']},
        {'role':'assistant','content':history[1]['content']},
    ]


def test_natural_participant_rejects_unknown_roles_and_unbounded_history():
    with pytest.raises(ValueError,match='Known synthetic role'):
        natural_response_messages('operator',{'synthetic':True},[])
    with pytest.raises(ValueError,match='Known synthetic role'):
        natural_response_messages('tpa',{'synthetic':True,'role':'billing'},[])
    with pytest.raises(ValueError,match='history'):
        natural_response_messages('caregiver',{'synthetic':True,'role':'caregiver'},[
            {'role':'assistant','content':'x'*2_001},
        ])



def test_text_only_path_never_calls_speech_adapters():
    class NoSpeech:
        def transcribe(self,*args):pytest.fail('Text regression must not recognize audio')
        def synthesize(self,*args,**kwargs):pytest.fail('Text regression must not synthesize audio')
    record={'synthetic':True,'role':'caregiver'}
    participant=BolnaParticipant(role='caregiver',record=record,speech=NoSpeech(),actor=ScriptedDesk('caregiver',record))
    result=participant.answer_text('Which language would you prefer?')
    assert result['participant_text']=='English, please.'
    assert result['audio_tested'] is False and result['checkpoint_eligible'] is False
    result=participant.answer_text('May we investigate this case with your permission?')
    assert 'agree to investigate' in result['participant_text']
    assert participant.turns==2


def test_restored_bounded_history_continues_at_the_next_turn_without_replaying():
    record={'synthetic':True,'role':'caregiver'}
    participant=BolnaParticipant(role='caregiver',record=record,speech=Speech(),actor=ScriptedDesk('caregiver',record))
    participant.history=[{'role':'assistant','content':'Which language would you prefer?'},
                         {'role':'user','content':'English, please.'}]
    result=participant.answer_text('May we investigate with your permission?')
    assert result['turn']==2 and len(participant.history)==4
