import json

import pytest

from sandbox.dialogue_quality import evaluate_dialogue


def answer_all(probability=0.99):
    return {'answers': {name: {'probability': probability} for name in [
        'answers_latest_question', 'stays_within_role_facts', 'preserves_identifiers',
        'does_not_claim_unverified_outcomes', 'natural_turn_taking']}}


def test_quality_evaluation_keeps_provider_provenance_and_never_verifies_state():
    observed = {}

    def invoke(messages, tools, **kwargs):
        observed['tools'] = tools
        observed['request'] = json.loads(messages[-1]['content'])
        return {'text': json.dumps(answer_all())}

    result = evaluate_dialogue(
        transcript=[
            {'speaker': 'assistant', 'text': 'What is holding up discharge? Please tell me what the hospital said.'},
            {'speaker': 'participant', 'text': 'We are ready to leave, but final insurance clearance is pending.'},
            {'speaker': 'assistant', 'text': 'I will check what document is missing.'},
            {'speaker': 'participant', 'text': 'The signed summary is still waiting for the doctor.'},
        ],
        participant_role='caregiver',
        known_facts={'discharge_ready': True, 'clearance': 'pending'},
        assistant_provider='BOLNA_WEBRTC',
        invoke=invoke,
    )

    assert observed['tools'] == []
    assert observed['request']['state']['participant_role'] == 'caregiver'
    assert result['assistant_provider'] == 'BOLNA_WEBRTC'
    assert result['conversation_quality_passed'] is True
    assert result['institution_state_verified'] is False
    assert result['checkpoint_eligible'] is False


def test_known_language_and_consent_mismatch_fails_even_if_judge_is_overconfident():
    def invoke(messages, tools, **kwargs):
        assert tools == []
        return {'text': json.dumps(answer_all())}

    result = evaluate_dialogue(
        transcript=[
            {'speaker': 'assistant', 'text': 'Which language would you prefer for updates?'},
            {'speaker': 'participant', 'text': 'Yes, you have my permission to investigate and share documents.'},
        ],
        participant_role='caregiver',
        known_facts={'preferred_language': 'English'},
        assistant_provider='BOLNA_WEBRTC',
        invoke=invoke,
    )

    assert not result['conversation_quality_passed']
    assert 'answers_latest_question' in result['critical_failures']
    assert result['deterministic_topic_mismatches'] == [
        {'turn': 1, 'kind': 'language_question_answered_with_consent'}
    ]


@pytest.mark.parametrize('turns', [[], [{'speaker': 'assistant', 'text': 'Hello'}],
                                    [{'speaker': 'assistant', 'text': 'Hello'},
                                     {'speaker': 'operator', 'text': 'I am staff'}]])
def test_quality_evaluation_rejects_incomplete_or_unscoped_turns(turns):
    with pytest.raises(ValueError):
        evaluate_dialogue(transcript=turns, participant_role='caregiver',
                          known_facts={}, invoke=lambda *_: pytest.fail('No model call expected'))


def test_quality_evaluation_rejects_unsafe_provider_provenance():
    with pytest.raises(ValueError):
        evaluate_dialogue(transcript=[{'speaker': 'assistant', 'text': 'Hi'},
                                     {'speaker': 'participant', 'text': 'Hello'}],
                          participant_role='caregiver', known_facts={}, assistant_provider='OTHER',
                          invoke=lambda *_: pytest.fail('No model call expected'))


def test_recognition_alignment_is_scored_separately_and_fails_closed():
    observed = {}
    def invoke(messages, tools, **kwargs):
        request = json.loads(messages[-1]['content'])
        observed.update(request)
        scores = {name: {'probability': 0.99} for name in request['questions']}
        scores['recognized_meaning_matches_injected_audio']['probability'] = 0.1
        return {'text': json.dumps({'answers': scores})}
    result = evaluate_dialogue(
        transcript=[{'speaker': 'assistant', 'text': 'Has it been received?'},
                    {'speaker': 'participant', 'text': 'It has been received.'}],
        participant_role='tpa',known_facts={'received': False},invoke=invoke,
        expected_exchanges=[{'assistant_text': 'Has it been received?',
                             'participant_text': 'It has not been received.'}])
    assert not result['conversation_quality_passed']
    assert result['critical_failures'] == ['recognized_meaning_matches_injected_audio']
    assert result['checkpoint_eligible'] is False
    assert observed['state']['conversation'][1]['text'] == 'It has been received.'


def test_unnatural_conversation_is_a_release_failure():
    def invoke(messages, tools, **kwargs):
        scores=answer_all()
        scores['answers']['natural_turn_taking']['probability']=0.2
        return {'text':json.dumps(scores)}
    result=evaluate_dialogue(transcript=[{'speaker':'assistant','text':'What is pending?'},
        {'speaker':'participant','text':'Insurance.'}],participant_role='caregiver',known_facts={},invoke=invoke)
    assert not result['conversation_quality_passed']
    assert 'natural_turn_taking' in result['critical_failures']


def test_known_disconnect_does_not_spend_on_a_semantic_judge():
    result=evaluate_dialogue(transcript=[
        {'speaker':'assistant','text':'Which language would you prefer?'},
        {'speaker':'participant','text':'Yes, permission to investigate is given.'}],
        participant_role='caregiver',known_facts={},
        invoke=lambda *a,**kw:pytest.fail('Known failure must not invoke judge'))
    assert result['semantic_judge_invoked'] is False
    assert result['checks']=={} and result['unassessed_checks']
    assert result['conversation_quality_passed'] is False


def test_multi_topic_question_is_not_rejected_by_exclusive_topic_rule():
    from sandbox.dialogue_quality import known_topic_mismatches
    assert known_topic_mismatches([
        {'speaker':'assistant','text':'Which language do you prefer, and may we investigate with your permission?'},
        {'speaker':'participant','text':'English, please.'}])==[]
