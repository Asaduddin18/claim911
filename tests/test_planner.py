from coordinator.planner import next_step


def test_investigation_advances_only_on_comparable_evidence():
    incident = dict(consent_active=True, consent_version=1, state='INVESTIGATING', reference='FINAL-42', request_type='FINAL_AUTHORIZATION')
    facts, calls, actions, docs = [], [], [], []
    def plan():
        return next_step(incident, calls, facts, actions, docs, [])
    def fact(role, predicate, **extra):
        return dict(id=str(len(facts)), source_role=role, predicate=predicate, support_status='REPORTED',
                    reference=incident['reference'], request_type=incident['request_type'], value={'SUBMITTED':{'submitted':True},'NOT_RECEIVED':{'found':False},'DESTINATION':{'destination':'old-tpa.example.invalid'},'RECEIVED':{'found':True}}[predicate], **extra)
    assert plan()['purpose'] == 'HOSPITAL_INITIAL'
    facts.append(fact('hospital', 'SUBMITTED'))
    assert plan()['purpose'] == 'CLAIMS_LOOKUP'
    wrong = fact('claims', 'NOT_RECEIVED'); wrong['request_type'] = 'PREAUTHORIZATION'; facts.append(wrong)
    assert plan()['purpose'] == 'CLAIMS_LOOKUP'
    facts.append(fact('claims', 'NOT_RECEIVED'))
    assert plan()['kind'] == 'COLLECT_DISPATCH'
    facts.append(fact('hospital', 'DESTINATION', document_id='dispatch-1'))
    assert plan()['kind'] == 'COLLECT_DISPATCH'
    docs.append(dict(id='dispatch-1', kind='dispatch'))
    assert plan()['kind'] == 'PROPOSE_CORRECTION'
    actions.append(dict(id='current-action', consent_version=1, state='PROPOSED'))
    assert plan()['kind'] == 'APPROVAL_REQUIRED'
    actions[-1]['state'] = 'AUTHORIZED'
    assert plan()['purpose'] == 'CORRECTION_REQUEST'
    calls.append(dict(purpose='CORRECTION_REQUEST', state='COMPLETED', consent_version=1, action_id='old-action'))
    assert plan()['purpose'] == 'CORRECTION_REQUEST'
    calls[-1]['action_id'] = 'current-action'
    assert plan()['kind'] == 'VERIFY_RECEIPT'
    assert plan()['automatic_dispatch'] is False
    facts.append(fact('claims', 'RECEIVED'))
    assert plan()['kind'] == 'HUMAN_REVIEW'


def test_consent_uncertainty_and_signed_receipt_gates():
    incident = dict(consent_active=False, consent_version=2, state='INVESTIGATING', reference='F', request_type='FINAL_AUTHORIZATION')
    def plan(calls=(), receipts=()):
        return next_step(incident, calls, [], [], [], receipts)
    assert plan()['kind'] == 'CONSENT_REQUIRED'
    incident['consent_active'] = True
    assert plan([dict(state='DISPATCH_UNKNOWN')])['kind'] == 'WAIT_FOR_CALL'
    incident['state'] = 'BLOCKER_RESOLVED'
    assert plan()['kind'] != 'RESOLVED'
    assert plan(receipts=[{'id':'verified'}])['kind'] == 'RESOLVED'
