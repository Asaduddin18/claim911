from datetime import datetime,timedelta,timezone
from uuid import uuid4
import pytest
from fastapi import HTTPException
from sandbox.bolna_workflow import voice_purpose
from sandbox.actors import scenario_manifest

NOW=datetime.now(timezone.utc)
PIN='a'*64


def run(checkpoint=0):
    return {'checkpoint':checkpoint,'manifest':scenario_manifest(),'state':'RUNNING','lease_token':uuid4(),
        'lease_until':NOW+timedelta(minutes=2),'origin':'USER_PREPARED',
        'provider_configuration':{'transport':'BOLNA_WEBRTC','assistant_config_sha256':PIN}}


def test_purpose_is_derived_from_checkpoint_and_not_chosen_by_browser():
    assert voice_purpose(run(1),PIN,now=NOW)=='HOSPITAL_REFERENCE_DISCOVERY'
    assert voice_purpose(run(4),PIN,now=NOW)=='RECORDS_DOCUMENT'
    assert voice_purpose(run(10),PIN,now=NOW)=='INSURER_FOLLOWUP'


@pytest.mark.parametrize('change',[{'state':'PAUSED'},{'state':'UNCERTAIN'},{'state':'READY'},
    {'lease_until':NOW-timedelta(seconds=1)},{'lease_token':None},{'origin':'VERIFICATION_FIXTURE'},
    {'provider_configuration':{'transport':'PIPECAT_STDIO'}},
    {'provider_configuration':{'transport':'BOLNA_WEBRTC','assistant_config_sha256':'b'*64}}])
def test_stale_lease_changed_assistant_or_prior_transport_prevents_session(change):
    with pytest.raises(HTTPException):voice_purpose(run(1)|change,PIN,now=NOW)


@pytest.mark.parametrize('checkpoint',[6,8,13])
def test_disclosure_receipt_and_completed_case_cannot_become_a_voice_action(checkpoint):
    with pytest.raises(HTTPException):voice_purpose(run(checkpoint),PIN,now=NOW)


def test_fresh_compatibility_check_is_permitted_without_claiming_worker_execution():
    fresh=run()|{'state':'READY','lease_token':None,'lease_until':None,'provider_configuration':{'transport':'PIPECAT_STDIO'}}
    assert voice_purpose(fresh,PIN,now=NOW)=='CAREGIVER_INTAKE'
