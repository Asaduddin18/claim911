"""Create the exact-host egress path for the trusted Azure provider adapter.

The audio package worker is not attached to this network. Provider operations
can leave the isolated Colima VM only through the allowlisted CONNECT proxy.
"""
import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit


CONTEXT = 'colima-claim911-sandbox'
NETWORK = 'claim911-provider-internal'
PROXY = 'claim911-egress-proxy'
IMAGE = 'claim911-egress-proxy:local'
SPEECH_HOSTS = {'eastus.stt.speech.microsoft.com', 'eastus.tts.speech.microsoft.com'}


def docker(*args, check=True):
    result = subprocess.run(['docker', '--context', CONTEXT, *args], capture_output=True, text=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError('Dedicated sandbox Docker operation failed: ' + ' '.join(args[:2]))
    return result


def provider_hosts(runtime):
    path = Path(runtime) / 'azure' / 'provider.json'
    config = json.loads(path.read_text())
    if config.get('environment') != 'sandbox' or config.get('paid_fallback') not in (False, None):
        raise ValueError('Sandbox provider configuration without paid fallback is required')
    speech = config.get('speech', {})
    if speech.get('region') != 'eastus' or speech.get('sku') != 'F0':
        raise ValueError('Only the reviewed free-tier eastus speech resource is allowed')
    model = config.get('model', {})
    endpoint = urlsplit(model.get('endpoint', ''))
    host = endpoint.hostname or ''
    if (endpoint.scheme != 'https' or endpoint.path not in {'', '/'} or endpoint.query or endpoint.fragment
            or not re.fullmatch(r'[a-z0-9-]+\.openai\.azure\.com', host)
            or model.get('model') != 'gpt-5-mini' or model.get('deployment') != 'gpt-5-mini'):
        raise ValueError('Only the reviewed Azure GPT-5 mini endpoint can be allowlisted')
    return sorted(SPEECH_HOSTS | {host})


def proxy_matches(runtime, allowed_hosts):
    inspected = docker('inspect', '--format', '{{json .}}', PROXY, check=False)
    if inspected.returncode:
        return False
    try:
        container = json.loads(inspected.stdout)
        if isinstance(container, list):
            container = container[0]
        env = dict(item.split('=', 1) for item in container['Config']['Env'] if '=' in item)
        networks = set(container['NetworkSettings']['Networks'])
        host = container['HostConfig']
        mounts = container.get('Mounts', [])
        image = container['Image']
        image_id = docker('image', 'inspect', '--format', '{{.Id}}', IMAGE).stdout.strip()
        configured = set(env.get('CLAIM911_ALLOWED_HOSTS', '').split(','))
        return all([
            container['State']['Running'] is True,
            configured == set(allowed_hosts),
            NETWORK in networks,
            'bridge' in networks,
            host.get('NetworkMode') == 'bridge',
            host.get('ReadonlyRootfs') is True,
            host.get('Privileged') is False,
            host.get('Binds') in (None, []),
            not mounts,
            host.get('CapDrop') == ['ALL'],
            any('no-new-privileges' in value for value in host.get('SecurityOpt', [])),
            container['Config'].get('User') == '65532:65532',
            image == image_id,
        ])
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True, help='Private Claim911 runtime directory')
    args = parser.parse_args()
    runtime = Path(args.runtime).resolve()
    allowed = provider_hosts(runtime)
    proxy_dir = Path(__file__).resolve().parents[1] / 'sandbox' / 'provider_worker' / 'egress_proxy'
    docker('build', '--network', 'none', '-f', str(proxy_dir / 'Dockerfile'), '-t', IMAGE, str(proxy_dir))
    provider_dir = proxy_dir.parent
    docker('build', '--network', 'none', '-f', str(provider_dir / 'Dockerfile'),
           '-t', 'claim911-speech-provider:local', str(provider_dir))

    network = docker('network', 'inspect', '--format', '{{.Internal}}', NETWORK, check=False)
    if network.returncode:
        docker('network', 'create', '--driver', 'bridge', '--internal', NETWORK)
    else:
        if network.stdout.strip().lower() != 'true':
            raise RuntimeError('Existing provider network is not internal; it was left unchanged')

    existing = docker('inspect', '--format', '{{.State.Running}}', PROXY, check=False)
    if existing.returncode:
        env_hosts = ','.join(allowed)
        docker('run', '--detach', '--name', PROXY, '--network', 'bridge',
               '--restart', 'unless-stopped', '--read-only', '--user', '65532:65532',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
               '--pids-limit', '16', '--memory', '64m', '--cpus', '0.25',
               '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=4m,mode=1777',
               '-e', 'CLAIM911_ALLOWED_HOSTS=' + env_hosts, IMAGE)
        docker('network', 'connect', '--alias', PROXY, NETWORK, PROXY)
    elif not proxy_matches(runtime, allowed):
        raise RuntimeError('Existing egress proxy does not match the restricted profile; no container was replaced')

    if not proxy_matches(runtime, allowed):
        raise RuntimeError('Egress proxy failed its read-only topology verification')
    evidence = {'environment': 'sandbox', 'proxy': PROXY, 'image': IMAGE,
                'allowed_hosts': allowed, 'provider_network': NETWORK,
                'provider_network_internal': True, 'proxy_has_mounts': False,
                'package_worker_network': 'none', 'configured_at': int(time.time())}
    target = runtime / 'sandbox' / 'provider-egress-status.json'
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(evidence, indent=2) + '\n')
    os.chmod(temporary, 0o600)
    temporary.replace(target)
    os.chmod(target, 0o600)
    print(json.dumps({k: v for k, v in evidence.items() if k not in {'configured_at'}}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'configured': False, 'error': type(exc).__name__, 'message': str(exc)}))
        raise SystemExit(1)
