"""Runtime boundary checks. Does not read or print credential values."""
import json
import os
import socket
from pathlib import Path

checks = {"non_root": os.getuid() != 0}
status = Path('/proc/self/status').read_text()
checks['no_capabilities'] = 'CapEff:\t0000000000000000' in status
checks['no_new_privileges'] = 'NoNewPrivs:\t1' in status
def inaccessible(path):
    try:
        return not Path(path).exists()
    except PermissionError:
        return True

checks['no_host_paths'] = all(inaccessible(p) for p in (
    '/Users', '/host', '/var/run/docker.sock', '/run/secrets',
    '/root/.aws', '/root/.azure', '/root/.ssh',
))
checks['no_credential_environment'] = not any(
    any(word in key.upper() for word in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY', 'DSN'))
    for key in os.environ
)
try:
    Path('/app/write-probe').write_text('must fail')
    checks['read_only_root'] = False
except OSError:
    checks['read_only_root'] = True
interfaces = {p.name for p in Path('/sys/class/net').iterdir()}
checks['loopback_only'] = interfaces == {'lo'}
for label, address in [('internet_blocked', ('1.1.1.1', 443)),
                       ('host_gateway_blocked', ('192.168.5.2', 8120)),
                       ('metadata_blocked', ('169.254.169.254', 80))]:
    try:
        with socket.create_connection(address, timeout=1):
            checks[label] = False
    except OSError:
        checks[label] = True
print(json.dumps({'passed': all(checks.values()), 'checks': checks}, indent=2))
raise SystemExit(0 if all(checks.values()) else 1)
