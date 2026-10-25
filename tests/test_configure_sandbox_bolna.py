import json
import stat

import pytest

from scripts.configure_sandbox_bolna import build_configs, configure


def _runtime(tmp_path):
    runtime = tmp_path
    (runtime / 'operational').mkdir()
    (runtime / 'sandbox').mkdir()
    (runtime / 'operational' / 'coordinator.json').write_text(json.dumps({
        'environment': 'operational', 'browser_voice_enabled': True,
        'bolna_api_key': 'provider-secret', 'bolna_agent_id': '4392053e-ad9a-4bde-900d-1ae28886846b',
        'bolna_agent_config_sha256': 'a' * 64,
        'gateway_token': 'shared-gateway-secret', 'webhook_token': 'operational-hook-secret',
        'gateway_url': 'https://claim911-demo.trycloudflare.com',
    }))
    (runtime / 'sandbox' / 'coordinator.json').write_text(json.dumps({
        'environment': 'sandbox', 'sandbox_execution_enabled': True,
        'live_calls_enabled': False, 'bolna_api_key': None,
        'gateway_token': 'previous-sandbox-token', 'webhook_token': 'sandbox-hook-secret',
        'simulator_agent_token': 'sandbox-simulator-secret',
    }))
    # This legacy file may be stale after the temporary tunnel is renewed.
    (runtime / 'gateway-url.txt').write_text('https://old-tunnel.trycloudflare.com\n')
    return runtime


def test_build_configs_places_only_broker_allowlist_with_provider_key(tmp_path):
    runtime = _runtime(tmp_path)
    configs = build_configs(runtime, token_factory=lambda _: 't' * 48)
    broker = configs[runtime / 'sandbox' / 'bolna-session-broker.json']
    gateway = configs[runtime / 'voice-gateway.json']
    sandbox = configs[runtime / 'sandbox' / 'coordinator.json']

    assert set(broker) == {
        'environment', 'bolna_api_key', 'bolna_agent_id', 'bolna_agent_config_sha256',
        'broker_token', 'gateway_registry_token', 'gateway_url', 'broker_registry_db',
    }
    assert broker['bolna_api_key'] == 'provider-secret'
    assert broker['broker_registry_db'].endswith('/sandbox/bolna-recording-allowlist.sqlite3')
    assert gateway['sandbox_route_registry_token'] == broker['gateway_registry_token']
    assert sandbox['sandbox_bolna_broker_token'] == broker['broker_token']
    assert sandbox['sandbox_bolna_agent_config_sha256'] == 'a' * 64
    assert sandbox['bolna_api_key'] is None
    assert sandbox['sandbox_bolna_broker_url'] == 'http://127.0.0.1:8127'
    assert sandbox['gateway_url'] == broker['gateway_url'] == 'https://claim911-demo.trycloudflare.com'
    assert sandbox['gateway_token'] == gateway['gateway_token']
    assert 'dsn' not in broker and 'simulator_agent_token' not in broker


def test_configure_writes_private_files_and_keeps_key_out_of_sandbox_profile(tmp_path):
    runtime = _runtime(tmp_path)
    paths = configure(runtime)
    for path in paths:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((runtime / 'sandbox').stat().st_mode) == 0o700
    sandbox = json.loads((runtime / 'sandbox' / 'coordinator.json').read_text())
    broker = json.loads((runtime / 'sandbox' / 'bolna-session-broker.json').read_text())
    assert not sandbox['bolna_api_key']
    assert broker['bolna_api_key'] == 'provider-secret'


@pytest.mark.parametrize('change', [
    {'live_calls_enabled': True}, {'bolna_api_key': 'must-not-leak'},
])
def test_configure_refuses_unsafe_sandbox_profile(tmp_path, change):
    runtime = _runtime(tmp_path)
    path = runtime / 'sandbox' / 'coordinator.json'
    profile = json.loads(path.read_text()) | change
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match='sandbox profile'):
        build_configs(runtime)


def test_configure_requires_reviewed_https_gateway(tmp_path):
    runtime = _runtime(tmp_path)
    path = runtime / 'operational' / 'coordinator.json'
    profile = json.loads(path.read_text())
    profile['gateway_url'] = 'https://other.example/path'
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match='HTTPS voice gateway'):
        build_configs(runtime)
