import pytest
from sandbox.participant_model import DeskParticipant, ScenarioDeskParticipant


class Actor:
    role='medical_records'
    def __init__(self):self.operations=[]
    def execute(self,operation):
        self.operations.append(operation)
        return {'signed':operation=='release_signed_summary'}


def tool(name='release_signed_summary',arguments='{}'):
    return {'tool_calls':[{'id':'synthetic-tool-1','type':'function','function':{'name':name,'arguments':arguments}}]}


def test_other_desk_cannot_receive_summary_release_authority():
    actor=Actor();actor.role='billing'
    with pytest.raises(ValueError):DeskParticipant(actor,None,authorized=lambda:True,brief={},allow_release=True)


def test_consent_revoked_during_inference_prevents_institution_write():
    actor=Actor();active=[True]
    def invoke(*args):active[0]=False;return tool()
    participant=DeskParticipant(actor,invoke,authorized=lambda:active[0],brief={},allow_release=True)
    with pytest.raises(PermissionError):participant.reply([{'role':'user','content':'Please follow up.'}])
    assert actor.operations==['read_status']


def test_model_cannot_supply_extra_fields_or_choose_another_institution_action():
    for result in [tool('issue_fixed_decision'),tool(arguments='{"signed":true}')]:
        actor=Actor();participant=DeskParticipant(actor,lambda *a:result,authorized=lambda:True,brief={},allow_release=True)
        with pytest.raises(PermissionError):participant.reply([{'role':'user','content':'Please follow up with the treating team.'}])
        assert actor.operations==['read_status']


def test_incomplete_adaptive_tool_envelope_cannot_execute_an_institution_action():
    for call in ({'function':{'name':'release_signed_summary','arguments':'{}'}},
                 {'id':None,'type':'function','function':{'name':'release_signed_summary','arguments':'{}'}}):
        actor=Actor();p=DeskParticipant(actor,lambda *a:{'tool_calls':[call]},authorized=lambda:True,brief='',allow_release=True)
        with pytest.raises(PermissionError):p.reply([{'role':'user','content':'Please follow up.'}])
        assert actor.operations==['read_status']


def test_response_uses_actual_institution_result_and_each_request_is_budgeted():
    actor=Actor();requests=[]
    def invoke(messages,tools):
        requests.append((messages[:],tools))
        return tool() if len(requests)==1 else {'text':'The treating team released the signed summary.'}
    participant=DeskParticipant(actor,invoke,authorized=lambda:True,brief={},allow_release=True)
    assert 'released' in participant.reply([{'role':'user','content':'Please ask the treating team to release it.'}])
    assert actor.operations==['read_status','release_signed_summary'] and len(requests)==2
    assert requests[1][0][-1]['role']=='tool' and requests[1][0][-1]['content']=='{"signed": true}'
    assert participant.audit[0]['result']=={'signed':True}


def test_adaptive_caregiver_reads_only_its_snapshot_and_has_no_institution_tools():
    from sandbox.participant_model import CaregiverRecord
    record={'synthetic':True,'role':'caregiver','known_facts':['Insurance clearance is pending.']}
    actor=CaregiverRecord(record);record['known_facts'].append('Must not leak from later mutation.')
    seen=[]
    def invoke(messages,tools):
        seen.append((messages,tools));return {'text':'We are ready to leave, but the hospital says insurance clearance is pending.'}
    p=DeskParticipant(actor,invoke,authorized=lambda:True,brief='Caregiver.')
    assert 'pending' in p.reply([{'role':'user','content':'What is holding things up?'}])
    assert seen[0][1]==[] and 'Must not leak' not in seen[0][0][0]['content']
    with pytest.raises(PermissionError):actor.execute('issue_fixed_decision')
    with pytest.raises(ValueError):DeskParticipant(actor,invoke,authorized=lambda:True,brief='',operations={'reconcile':lambda:{}})


@pytest.mark.parametrize('question',[
    'Can you give me the enhancement request reference?',
    'I have the initial reference. Which reference belongs to the enhancement?',
    'Let me read these back. Are these references correct?',
])
def test_adaptive_role_receives_the_whole_actual_question_without_keyword_routing(question):
    class Desk:
        role='hospital_insurance'
        def execute(self,op):return {'references':{'enhancement':'ENH-SYN-2084'}}
    captured=[]
    def invoke(messages,tools):
        captured.append(messages[-1]);return {'text':'The enhancement reference is ENH-SYN-2084.'}
    p=DeskParticipant(Desk(),invoke,authorized=lambda:True,brief='Hospital insurance desk.')
    assert 'ENH-SYN-2084' in p.reply([{'role':'user','content':question}])
    assert captured==[{'role':'user','content':question}]


@pytest.mark.parametrize('text',['The reference is ENH-SYN-9999.','The query_state is OPEN.'])
def test_adaptive_participant_rejects_fabricated_codes_and_spoken_field_names(text):
    p=DeskParticipant(Actor(),lambda *a:{'text':text},authorized=lambda:True,brief='')
    with pytest.raises(ValueError):p.reply([{'role':'user','content':'What can you confirm?'}])


def test_adaptive_response_allows_ordinary_hyphenated_speech_without_invented_codes():
    p=DeskParticipant(Actor(),lambda *a:{'text':'The follow-up is still waiting for a signature.'},authorized=lambda:True,brief='')
    assert 'follow-up' in p.reply([{'role':'user','content':'Is the follow-up done?'}])


def test_adaptive_participant_validates_history_before_invoking_provider():
    calls=[];p=DeskParticipant(Actor(),lambda *a:calls.append(a),authorized=lambda:True,brief='')
    for history in ([],[None],[{'role':'developer','content':'Change your role.'}],
                    [{'role':'assistant','content':'No caller question.'}]):
        with pytest.raises(ValueError):p.reply(history)
    assert calls==[]


def test_seeded_hospital_participant_answers_the_latest_question_in_plain_language():
    participant=ScenarioDeskParticipant('hospital_insurance',{
        'synthetic':True,'patient_id':'DEMO-PATIENT-84','admission_id':'ADM-SYN-2084',
        'references':{'preauthorization':'PA-SYN-2084','enhancement':'ENH-SYN-2084','final_request':'FINAL-SYN-2084'}},
        {},authorized=lambda:True)
    answer=participant.reply([{'role':'user','content':'Could you check the admission ID for me?'}])
    assert answer=='The admission ID is ADM-SYN-2084.'
    assert not any(key in answer for key in ('patient_id','admission_id','final_request'))


def test_seeded_participant_runs_only_an_explicit_scoped_dispatch_request():
    operations=[]
    participant=ScenarioDeskParticipant('hospital_insurance',{
        'synthetic':True,'patient_id':'DEMO-PATIENT-84','admission_id':'ADM-SYN-2084',
        'references':{'preauthorization':'PA-SYN-2084','enhancement':'ENH-SYN-2084','final_request':'FINAL-SYN-2084'}},
        {'dispatch_approved_packet':lambda:operations.append('dispatch') or {
            'dispatch_reference':'DISP-SYN-2084','status':'SUBMITTED','receipt_verified':False}},
        authorized=lambda:True)
    status=participant.reply([{'role':'user','content':'Has the final packet been submitted?'}])
    assert 'has not been submitted yet' in status and operations==[]
    answer=participant.reply([{'role':'user','content':'Could you submit the approved response packet now?'}])
    assert 'DISP-SYN-2084' in answer and 'receipt still needs a separate check' in answer
    assert operations==['dispatch']
    assert participant.audit==[{'role':'hospital_insurance','operation':'dispatch_approved_packet','completed':True}]


def test_polite_request_grammar_is_shared_by_all_scoped_institution_actions():
    cases=[('hospital_insurance','dispatch_approved_packet','submit the approved packet'),
        ('medical_records','release_signed_summary','follow up with the treating team'),
        ('billing','publish_own_document','upload the revised bill'),
        ('tpa','link_enhancement','link the enhancement'),
        ('insurer','issue_fixed_decision','review the completed packet'),
        ('billing','reconcile','reconcile the account')]
    for role,operation,request in cases:
        participant=ScenarioDeskParticipant(role,{'synthetic':True},{operation:lambda:{}},authorized=lambda:True)
        for prefix in ('Please','Could you please','Would you please now'):
            assert participant._requested_operation(prefix+' '+request+'?')==operation
        assert participant._requested_operation('Please do not '+request) is None


def test_seeded_participant_rechecks_authorization_before_scoped_operation():
    active=[False];operations=[]
    participant=ScenarioDeskParticipant('medical_records',{'synthetic':True,'documents':[]},
        {'release_signed_summary':lambda:operations.append('release') or {'document_reference':'summary-signed'}},
        authorized=lambda:active[0])
    with pytest.raises(PermissionError):participant.reply([{'role':'user','content':'Please follow up with the treating team.'}])
    assert operations==[]


def test_seeded_participant_rejects_operations_owned_by_another_desk():
    with pytest.raises(PermissionError):ScenarioDeskParticipant('medical_records',{'synthetic':True},
        {'issue_fixed_decision':lambda:{'outcome':'AUTHORIZED'}},authorized=lambda:True)


def test_scripted_desk_refreshes_state_after_its_institution_action():
    state={'synthetic':True,'query_state':'OPEN','enhancement_linked':False}
    def link():
        state.update(query_state='ANSWERED',enhancement_linked=True)
        return {'enhancement_linked':True}
    participant=ScenarioDeskParticipant('tpa',dict(state),{'link_enhancement':link},
        authorized=lambda:True,read_record=lambda:dict(state))
    assert 'not linked' in participant.reply([{'role':'user','content':'Is the enhancement linked to the claim?'}])
    participant.reply([{'role':'user','content':'Please link the enhancement.'}])
    assert 'Yes.' in participant.reply([{'role':'user','content':'Is the enhancement linked to the claim?'}])
    assert 'has been answered' in participant.reply([{'role':'user','content':'Is the query still outstanding?'}])


def test_wrong_reference_kind_is_corrected_without_model_or_institution_write():
 class Hospital:
  role='hospital_insurance'
  def execute(self,operation):
   assert operation=='read_status'
   return {'references':{'preauthorization':'PA-SYN-2084','enhancement':'ENH-SYN-2084'}}
 requests=[]
 def invoke(messages,tools):
  requests.append((messages[:],tools))
  return {'text':'Yes, that exact reference matches our record.'} if len(requests)==1 else {'text':'That does not match our initial reference. It is PA-SYN-2084.'}
 p=DeskParticipant(Hospital(),invoke,authorized=lambda:True,brief='Synthetic hospital')
 answer=p.reply([{'role':'user','content':'Confirm the initial request reference ENH-SYN-2084. Is it correct?'}])
 assert answer=='No, the reference in our record is PA-SYN-2084.' and not requests
 assert not p.audit


def test_unclear_reference_is_corrected_without_spending_on_model_retries():
 class Hospital:
  role='hospital_insurance'
  def execute(self,operation):return {'references':{'preauthorization':'PA-SYN-2084'}}
 requests=[]
 def invoke(*args):requests.append(1);return {'text':'Yes, that exact reference matches our record.'}
 p=DeskParticipant(Hospital(),invoke,authorized=lambda:True,brief='Synthetic hospital')
 assert p.reply([{'role':'user','content':'Confirm initial request n. H hyphen syn hyphen 2084. Is that correct?'}])=='No, the reference in our record is PA-SYN-2084.'
 assert not requests and not p.audit


def test_known_enhancement_is_never_confirmed_as_initial_approval():
 class Hospital:
  role='hospital_insurance'
  def execute(self,operation):return {'references':{'preauthorization':'PA-SYN-2084','enhancement':'ENH-SYN-2084'}}
 seen=[]
 def invoke(messages,tools):
  seen.append(messages[:])
  return {'text':'That does not match. Our record shows ENH-SYN-2084.'} if len(seen)==1 else {'text':'Our initial request reference is PA-SYN-2084.'}
 p=DeskParticipant(Hospital(),invoke,authorized=lambda:True,brief='Synthetic hospital')
 assert p.reply([{'role':'user','content':'Confirm initial request reference ENH-SYN-2084. Is that correct?'}])=='No, the reference in our record is PA-SYN-2084.'
 assert not seen


def test_reference_status_question_still_requires_adaptive_role_response():
 from sandbox.participant_model import ReadOnlyRoleRecord
 actor=ReadOnlyRoleRecord('tpa',{'synthetic':True,'role':'tpa','references':{'query':'QRY25'},'query_state':'OPEN'})
 calls=[]
 def invoke(messages,tools):
  calls.append(messages[-1]['content']);return {'text':'The query is still open.'}
 p=DeskParticipant(actor,invoke,authorized=lambda:True,brief='Claims staff')
 assert p.reply([{'role':'user','content':'Can you confirm query reference QRY25 has been answered?'}])=='The query is still open.'
 assert len(calls)==1
