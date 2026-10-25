import pytest
from sandbox.runs import execution_manifest, full_case_completed


def test_component_preserves_scenario_without_claiming_full_case():
    manifest=execution_manifest('hospital_references_reported')
    assert manifest['checkpoints']==['hospital_references_reported']
    assert manifest['execution_scope']=='COMPONENT'
    assert not full_case_completed({'state':'COMPLETED','manifest':manifest})
    assert len(execution_manifest()['checkpoints'])==13


def test_full_completion_requires_every_original_checkpoint():
    assert full_case_completed({'state':'COMPLETED','manifest':execution_manifest()})
    assert not full_case_completed({'state':'RUNNING','manifest':execution_manifest()})
    manifest=execution_manifest();manifest['checkpoints']=manifest['checkpoints'][:2]
    assert not full_case_completed({'state':'COMPLETED','manifest':manifest})


def test_later_stage_cannot_bypass_prerequisites():
    with pytest.raises(ValueError):execution_manifest('caregiver_handoff_verified')


def test_query_component_declares_fixture_without_prior_voice_checkpoints():
    manifest=execution_manifest('claims_query_discovered')
    assert manifest['checkpoints']==['claims_query_discovered']
    assert manifest['starting_state']=='EXPLICIT_SYNTHETIC_FINAL_REFERENCE_FIXTURE'
    assert not full_case_completed({'state':'COMPLETED','manifest':manifest})
