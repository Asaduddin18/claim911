"""Configure the trusted Bolna broker and sandbox-only routing boundary.

The sandbox package worker never receives any values written by this script.
Only the trusted broker receives the provider key, and its config contains no
database, institution, operational API, or phone-dispatch credentials.
"""
import json
import os
import secrets
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


BROKER_FIELDS = {
    'environment', 'bolna_api_key', 'bolna_agent_id',
    'bolna_agent_config_sha256', 'broker_token',
    'gateway_registry_token', 'gateway_url', 'broker_registry_db',
}


def _read(path):
    return json.loads(Path(path).read_text())


def _write_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_configs(runtime, *, token_factory=secrets.token_urlsafe):
    runtime = Path(runtime).resolve()
    operational_path = runtime / 'operational' / 'coordinator.json'
    sandbox_path = runtime / 'sandbox' / 'coordinator.json'
    broker_path = runtime / 'sandbox' / 'bolna-session-broker.json'
    gateway_path = runtime / 'voice-gateway.json'
    route_db = runtime / 'sandbox' / 'voice-routes.sqlite3'
    broker_registry_db = runtime / 'sandbox' / 'bolna-recording-allowlist.sqlite3'

    operational = _read(operational_path)
    sandbox = _read(sandbox_path)
    if operational.get('environment') != 'operational' or not operational.get('browser_voice_enabled'):
        raise ValueError('An enabled operational Bolna profile is required')
    if not operational.get('bolna_api_key') or not operational.get('bolna_agent_id'):
        raise ValueError('The reviewed Bolna account and assistant are required')
    fingerprint = operational.get('bolna_agent_config_sha256', '')
    if len(fingerprint) != 64 or any(c not in '0123456789abcdef' for c in fingerprint):
        raise ValueError('A reviewed Bolna assistant fingerprint is required')
    if (sandbox.get('environment') != 'sandbox' or sandbox.get('live_calls_enabled')
            or sandbox.get('bolna_api_key')):
        raise ValueError('The sandbox profile must remain synthetic and provider-key-free')
    if not sandbox.get('sandbox_execution_enabled'):
        raise ValueError('Enable the isolated synthetic sandbox before configuring Bolna')
    if not all(operational.get(k) for k in ('gateway_token', 'webhook_token')):
        raise ValueError('The existing scoped voice gateway credentials are required')
    if not all(sandbox.get(k) for k in ('gateway_token', 'webhook_token', 'simulator_agent_token')):
        raise ValueError('The isolated sandbox callback and simulator credentials are required')

    # The operational profile is authoritative. The older standalone URL file
    # may refer to a previous temporary tunnel after it has been renewed.
    gateway_url = operational.get('gateway_url', '').strip().rstrip('/')
    parsed = urlsplit(gateway_url)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not parsed.hostname.endswith('.trycloudflare.com')
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('A reviewed HTTPS voice gateway root is required')

    previous_broker = _read(broker_path) if broker_path.exists() else {}
    previous_gateway = _read(gateway_path) if gateway_path.exists() else {}
    broker_token = previous_broker.get('broker_token') or token_factory(32)
    route_token = previous_broker.get('gateway_registry_token') or token_factory(32)
    if previous_gateway.get('gateway_token') not in (None, operational['gateway_token']):
        raise ValueError('Existing gateway configuration has a different authentication token')

    broker = {
        'environment': 'sandbox_bolna_broker',
        'bolna_api_key': operational['bolna_api_key'],
        'bolna_agent_id': operational['bolna_agent_id'],
        'bolna_agent_config_sha256': fingerprint,
        'broker_token': broker_token,
        'gateway_registry_token': route_token,
        'gateway_url': gateway_url,
        'broker_registry_db': str(broker_registry_db),
    }
    gateway = {
        'environment': 'operational',
        'core_url': 'http://127.0.0.1:8124',
        'sandbox_core_url': 'http://127.0.0.1:8126',
        'gateway_token': operational['gateway_token'],
        'webhook_token': operational['webhook_token'],
        'sandbox_webhook_token': sandbox['webhook_token'],
        'sandbox_route_db': str(route_db),
        'sandbox_route_registry_token': route_token,
    }
    sandbox = sandbox | {
        # The shared static gateway credential is only used with per-call tokens.
        # The sandbox API is trusted; the isolated package worker never receives it.
        'gateway_token': operational['gateway_token'],
        'gateway_url': gateway_url,
        'sandbox_bolna_broker_url': 'http://127.0.0.1:8127',
        'sandbox_bolna_broker_token': broker_token,
        'sandbox_bolna_agent_config_sha256': fingerprint,
    }
    if set(broker) != BROKER_FIELDS:
        raise AssertionError('Broker configuration must remain an explicit allowlist')
    forbidden = {'dsn', 'core_url', 'simulator_url', 'legacy_read_dsn', 'operator_token',
                 'simulator_agent_token', 'hospital_token', 'claims_token', 'insurer_token'}
    if forbidden.intersection(broker):
        raise AssertionError('Forbidden credentials reached the trusted provider broker')
    profiles = {
        broker_path: broker,
        gateway_path: gateway,
        sandbox_path: sandbox,
    }
    product_path=runtime/'sandbox'/'product-profile.json'
    if product_path.exists():
        product=_read(product_path)
        if product.get('environment')!='sandbox' or product.get('bolna_api_key') or product.get('live_calls_enabled'):
            raise ValueError('The sandbox product profile must remain provider-key-free and phone-disabled')
        for key in ('gateway_token','gateway_url','sandbox_bolna_broker_url',
                    'sandbox_bolna_broker_token','sandbox_bolna_agent_config_sha256'):
            product[key]=sandbox[key]
        profiles[product_path]=product
    return profiles


def configure(runtime):
    configs = build_configs(runtime)
    for path, value in configs.items():
        _write_private(path, value)
    # Make sure the directory containing the broker key cannot be traversed by
    # other local users. Keep the worker's configuration outside its mount set.
    os.chmod(Path(runtime) / 'sandbox', 0o700)
    return tuple(configs)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    args = parser.parse_args()
    paths = configure(args.runtime)
    print('Configured the trusted Bolna broker, voice gateway, and sandbox API profiles.')
    print('Private configuration files: ' + ', '.join(str(p) for p in paths))
    print('The sandbox package worker received no credentials and remains phone-disabled.')
