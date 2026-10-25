"""Small CONNECT-only proxy for the trusted one-operation Azure adapter."""
import ipaddress
import os
import re
import select
import socket
import socketserver
import time
from urllib.parse import urlsplit


MAX_HEADER = 8192
MAX_RELAY_BYTES = 4_000_000
RELAY_SECONDS = 100
ALLOWED_HOST_RE = re.compile(r'^[a-z0-9.-]{1,253}$')


def parse_connect_target(header, allowed_hosts):
    lines = header.decode('ascii', errors='strict').split('\r\n')
    parts = lines[0].split(' ')
    if len(parts) != 3 or parts[0] != 'CONNECT' or parts[2] not in {'HTTP/1.0', 'HTTP/1.1'}:
        raise ValueError('CONNECT only')
    authority = parts[1]
    parsed = urlsplit('https://' + authority)
    host = (parsed.hostname or '').rstrip('.').lower()
    if (not ALLOWED_HOST_RE.fullmatch(host) or parsed.port != 443 or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('Malformed target')
    if host not in allowed_hosts:
        raise PermissionError('Target not allowlisted')
    for line in lines[1:]:
        if not line:
            continue
        key, separator, value = line.partition(':')
        if not separator:
            raise ValueError('Malformed header')
        if key.strip().lower() == 'host' and value.strip().lower() not in {host, host + ':443'}:
            raise ValueError('Host header mismatch')
        if key.strip().lower() in {'proxy-authorization', 'proxy-connection'}:
            raise ValueError('Proxy credentials and chained proxies are forbidden')
    return host


def public_addresses(host, lookup=socket.getaddrinfo):
    results = lookup(host, 443, type=socket.SOCK_STREAM)
    addresses = []
    for family, socktype, proto, _, sockaddr in results:
        address = ipaddress.ip_address(sockaddr[0])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if not address.is_global:
            raise PermissionError('Target resolved to a non-public address')
        addresses.append((family, socktype, proto, sockaddr))
    if not addresses:
        raise OSError('Target did not resolve')
    return addresses


class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(5)
        data = bytearray()
        while b'\r\n\r\n' not in data and len(data) <= MAX_HEADER:
            chunk = client.recv(min(1024, MAX_HEADER + 1 - len(data)))
            if not chunk:
                return
            data.extend(chunk)
        boundary = data.find(b'\r\n\r\n')
        if boundary < 0 or boundary > MAX_HEADER:
            self.reject(431, 'Request header too large')
            return
        header = bytes(data[:boundary])
        remainder = bytes(data[boundary + 4:])
        try:
            host = parse_connect_target(header, self.server.allowed_hosts)
            addresses = public_addresses(host)
        except PermissionError:
            self.reject(403, 'Egress target denied')
            return
        except (UnicodeError, ValueError, OSError):
            self.reject(400, 'Invalid egress request')
            return
        upstream = None
        for family, socktype, proto, sockaddr in addresses:
            try:
                upstream = socket.socket(family, socktype, proto)
                upstream.settimeout(8)
                upstream.connect(sockaddr)
                break
            except OSError:
                if upstream:
                    upstream.close()
                upstream = None
        if upstream is None:
            self.reject(502, 'Approved provider endpoint unavailable')
            return
        try:
            client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            if remainder:
                upstream.sendall(remainder)
            self.relay(client, upstream)
        except OSError:
            pass
        finally:
            upstream.close()

    def reject(self, status, reason):
        self.request.sendall(f'HTTP/1.1 {status} {reason}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n'.encode())

    @staticmethod
    def relay(client, upstream):
        client.settimeout(None)
        upstream.settimeout(None)
        deadline = time.monotonic() + RELAY_SECONDS
        relayed = 0
        while time.monotonic() < deadline and relayed <= MAX_RELAY_BYTES:
            readable, _, exceptional = select.select([client, upstream], [], [client, upstream], 1)
            if exceptional or not readable:
                continue
            for source in readable:
                payload = source.recv(65536)
                if not payload:
                    return
                destination = upstream if source is client else client
                destination.sendall(payload)
                relayed += len(payload)
                if relayed > MAX_RELAY_BYTES:
                    return


class ProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, address, allowed_hosts):
        self.allowed_hosts = allowed_hosts
        self.capacity = __import__('threading').BoundedSemaphore(8)
        super().__init__(address, ProxyHandler)

    def process_request(self, request, client_address):
        if not self.capacity.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.capacity.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.capacity.release()


def main():
    hosts = {host.strip().lower().rstrip('.') for host in os.environ.get('CLAIM911_ALLOWED_HOSTS', '').split(',') if host.strip()}
    if not hosts or any(not ALLOWED_HOST_RE.fullmatch(host) for host in hosts):
        raise SystemExit('Exact provider host allowlist required')
    server = ProxyServer(('0.0.0.0', 3128), hosts)
    server.serve_forever(poll_interval=0.5)


if __name__ == '__main__':
    main()
