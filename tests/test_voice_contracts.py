from coordinator.objectives import call_objective
from coordinator.voice_contracts import COMMON_CALL_CLOSING_NOTE
from coordinator.workflow_calls import prepare_context
from scripts.configure_bolna import PROMPT,tool_config


def test_every_legacy_role_objective_has_the_shared_closing_instruction():
    for purpose in ('HOSPITAL_INITIAL','CLAIMS_LOOKUP','HOSPITAL_FOLLOWUP',
                    'CORRECTION_REQUEST','CAREGIVER_UPDATE'):
        assert COMMON_CALL_CLOSING_NOTE in call_objective(purpose,'HOSP-FINAL-1042')


def test_each_initial_complex_workflow_role_has_the_shared_closing_instruction():
    cases=(('CAREGIVER_INTAKE','UNCONFIRMED_FINAL_REFERENCE'),
           ('HOSPITAL_REFERENCE_DISCOVERY','UNCONFIRMED_FINAL_REFERENCE'),
           ('QUERY_DISCOVERY','HOSP-FINAL-1042'))
    for purpose,reference in cases:
        context=prepare_context({'reference':reference,'patient_id':'DEMO-PATIENT-42'},None,purpose)
        assert COMMON_CALL_CLOSING_NOTE in context['objective']


def test_caregiver_handoff_keeps_its_case_specific_message_before_common_close():
    objective=prepare_context({'reference':'UNCONFIRMED_FINAL_REFERENCE',
        'patient_id':'DEMO-PATIENT-42'},None,'CAREGIVER_INTAKE')['objective']
    assert 'Claim911 will check with the hospital and insurer' in objective
    assert objective.index('then show you what they confirm') < objective.index(COMMON_CALL_CLOSING_NOTE)


def test_agent_prompt_does_not_override_the_shared_closing_with_a_shorter_handoff():
    assert COMMON_CALL_CLOSING_NOTE in PROMPT
    assert 'including the final common closing sentence' in PROMPT
    assert 'confirm." Then end intake' not in PROMPT
    tools=tool_config('https://synthetic.example.invalid','synthetic-token')
    report=next(t for t in tools['tools'] if t['name']=='claim911_report_update')
    assert {'dispatch_reference','callback_at'}<=set(report['parameters']['properties'])


def test_all_roles_refresh_context_before_reporting_newly_uploaded_evidence():
    assert 'refresh it immediately before each report-tool write' in PROMPT
    assert 'Do not restart answered questions after refreshing context' in PROMPT
    assert 'Fetch claim911_context once at the start' not in PROMPT


def test_terminal_tool_speech_is_short_and_contains_only_one_closing_note():
 import pytest
 from coordinator.voice_contracts import report_speech
 result=report_speech('The query is recorded. Document collection is next.')
 assert result['call_complete'] is True
 assert result['spoken_outcome'].count(COMMON_CALL_CLOSING_NOTE)==1
 assert 'COMMON END-OF-CALL RULE' not in result['spoken_outcome']
 assert report_speech(result['spoken_outcome'])['spoken_outcome']==result['spoken_outcome']
 with pytest.raises(ValueError):report_speech('word '*56)


def test_intermediate_tool_speech_does_not_end_an_unfinished_task():
 from coordinator.voice_contracts import report_speech
 result=report_speech('Please upload the released document.',complete=False)
 assert result['call_complete'] is False
 assert COMMON_CALL_CLOSING_NOTE not in result['spoken_outcome']
