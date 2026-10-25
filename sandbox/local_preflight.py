"""Run deterministic simulator contracts with pytest and network access denied.

This cannot certify model response quality, Bolna, audio or complete workflow
state. It prevents spending on known broken dialogue/control contracts.
"""
import os
from pathlib import Path
import subprocess
import sys

TESTS=(
 'tests/test_participant_dialogue.py','tests/test_participant_model.py',
 'tests/test_readback_confirmation.py','tests/test_identifier_readbacks.py',
 'tests/test_bolna_browser_transport.py','tests/test_bolna_participant.py',
 'tests/test_dialogue_quality.py','tests/test_participant_evaluation.py',
 'tests/test_reasoning_policy.py','tests/test_release_evidence.py','tests/test_caregiver_progress.py',
)


def run_local_preflight(project=None):
    root=Path(project or Path(__file__).resolve().parents[1]).resolve()
    env={**os.environ,'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONPATH':str(root),'PYTEST_ADDOPTS':'','CLAIM911_TEST_NETWORK':'deny'}
    result=subprocess.run([sys.executable,'-m','pytest','-q','-p','sandbox.local_test_guard',*TESTS,'--tb=short'],
                          cwd=root,env=env,text=True,capture_output=True,timeout=90)
    report={'scope':'LOCAL_SIMULATOR_CONTRACTS_ONLY','network_denied':True,
            'bolna_tested':False,'model_quality_verified':False,'audio_tested':False,
            'workflow_state_verified':False,'passed':result.returncode==0,
            'test_files':list(TESTS),'output':result.stdout+result.stderr}
    if result.returncode:raise RuntimeError('Local simulator contracts failed before provider use:\n'+report['output'])
    return report
