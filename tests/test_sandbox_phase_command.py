from pathlib import Path
from uuid import uuid4
import pytest
from coordinator.worker import sandbox_phase_command,SANDBOX_PHASE_TIMEOUT_SECONDS,SANDBOX_JOB_LEASE_SECONDS

NODE='/path/to/user/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'


def test_worker_pins_transport_budget_and_runtime_without_shell():
 if not Path(NODE).exists():pytest.skip('Bundled runtime unavailable')
 command=sandbox_phase_command({'environment':'sandbox','sandbox_node_binary':NODE},str(uuid4()),'BOLNA_WEBRTC')
 assert command[command.index('--transport')+1]=='bolna-browser'
 assert command[command.index('--phase')+1]=='rehearsal'
 assert command[command.index('--node')+1]==NODE
 assert command[command.index('--participant-mode')+1]=='adaptive'
 assert '--single-step' in command
 assert SANDBOX_PHASE_TIMEOUT_SECONDS>300+120
 assert SANDBOX_JOB_LEASE_SECONDS>SANDBOX_PHASE_TIMEOUT_SECONDS+60


@pytest.mark.parametrize('patch,transport',[
 ({'environment':'operational'},'BOLNA_WEBRTC'),
 ({'live_calls_enabled':True},'BOLNA_WEBRTC'),
 ({'sandbox_spend_phase':'unlimited'},'BOLNA_WEBRTC'),
 ({'sandbox_node_binary':'node'},'BOLNA_WEBRTC'),
 ({},None)])
def test_invalid_worker_settings_fail_before_provider(patch,transport):
 with pytest.raises((ValueError,PermissionError)):
  sandbox_phase_command({'environment':'sandbox',**patch},str(uuid4()),transport)


def test_worker_passes_its_explicit_profile_runtime_instead_of_a_default(tmp_path):
 if not Path(NODE).exists():pytest.skip('Bundled runtime unavailable')
 (tmp_path/'sandbox').mkdir();(tmp_path/'sandbox/coordinator.json').write_text('{}')
 command=sandbox_phase_command({'environment':'sandbox','sandbox_node_binary':NODE},str(uuid4()),'BOLNA_WEBRTC',runtime=tmp_path)
 assert command[command.index('--runtime')+1]==str(tmp_path.resolve())
 with pytest.raises(ValueError,match='runtime'):
  sandbox_phase_command({'environment':'sandbox','sandbox_node_binary':NODE},str(uuid4()),'BOLNA_WEBRTC',runtime=tmp_path/'missing')
