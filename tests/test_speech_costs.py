import hashlib
from datetime import datetime,timezone,timedelta
from uuid import uuid4
import pytest
from sandbox.speech_costs import reconcile_speech,validate_proof
from sandbox.spend import reserve,settle
from tests.test_sandbox_spend import ledger


def evidence():
    now=datetime.now(timezone.utc);speech={'sku':'F0','region':'eastus','api_key':'synthetic-test-key'}
    return speech,{'sku':'F0','kind':'SpeechServices','region':'eastus',
        'credential_sha256':hashlib.sha256(speech['api_key'].encode()).hexdigest(),
        'verified_at':now.isoformat(),'resource_created_at':(now-timedelta(hours=2)).isoformat(),
        'profile_saved_at':(now-timedelta(hours=1)).isoformat(),
        'last_resource_write_at':(now-timedelta(hours=2)).isoformat(),'no_updates_since_resource_write':True}


def test_reconcile_only_verified_free_speech_and_preserve_model_holds(ledger):
    conn,now=ledger;speech,proof=evidence();speech_id=uuid4();model_id=uuid4()
    for id,op in ((speech_id,'bolna-participant-transcribe'),(model_id,'bolna-participant-reply')):
        reserve(conn,request_id=id,run_id=uuid4(),phase='development',operation=op,maximum_micro=100000,now=now)
        settle(conn,id)
    result=reconcile_speech(conn,proof,speech)
    assert result['reconciled_requests']==1 and result['released_reserved_micro']==100000
    assert conn.execute('SELECT state,charged_micro FROM coordinator.sandbox_spend WHERE request_id=%s',(speech_id,)).fetchone()=={'state':'CONFIRMED','charged_micro':0}
    assert conn.execute('SELECT state FROM coordinator.sandbox_spend WHERE request_id=%s',(model_id,)).fetchone()['state']=='UNCERTAIN'
    assert reconcile_speech(conn,proof,speech)['reconciled_requests']==0


@pytest.mark.parametrize('change',[{'sku':'S0'},{'credential_sha256':'wrong'},
    {'no_updates_since_resource_write':False},{'verified_at':'2020-01-01T00:00:00+00:00'}])
def test_no_free_settlement_without_current_exact_resource_proof(change):
    speech,proof=evidence()
    with pytest.raises(ValueError):validate_proof(proof|change,speech)


def test_older_unbound_speech_holds_are_retained(ledger):
    conn,now=ledger;speech,proof=evidence();id=uuid4()
    reserve(conn,request_id=id,run_id=uuid4(),phase='development',operation='bolna-participant-synthesize',maximum_micro=100000)
    settle(conn,id)
    conn.execute('UPDATE coordinator.sandbox_spend SET created_at=%s WHERE request_id=%s',(now-timedelta(days=1),id))
    assert reconcile_speech(conn,proof,speech)['reconciled_requests']==0
