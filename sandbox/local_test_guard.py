"""pytest-only network guard. No provider network is allowed in local checks."""
import ipaddress
import os
import socket
import pytest


def loopback_host(host):
    if isinstance(host,bytes):host=host.decode('ascii',errors='replace')
    if host=='localhost':return True
    try:return ipaddress.ip_address(host).is_loopback
    except (ValueError,TypeError):return False


@pytest.fixture(autouse=True,scope='session')
def deny_network_for_local_preflight():
    patch=pytest.MonkeyPatch()
    mode=os.environ.get('CLAIM911_TEST_NETWORK','deny')
    if mode not in {'deny','loopback'}:raise ValueError('Explicit local test network policy required')
    original_connect=socket.socket.connect
    original_connect_ex=socket.socket.connect_ex
    original_resolve=socket.getaddrinfo
    def check(address):
        if mode!='loopback' or not isinstance(address,tuple) or not loopback_host(address[0]):
            raise AssertionError('Provider and non-loopback network access is forbidden in local tests')
    def connect(sock,address):check(address);return original_connect(sock,address)
    def connect_ex(sock,address):check(address);return original_connect_ex(sock,address)
    def resolve(host,*args,**kwargs):
        if mode!='loopback' or not loopback_host(host):raise AssertionError('External DNS resolution is forbidden in local tests')
        return original_resolve(host,*args,**kwargs)
    def create_connection(address,*args,**kwargs):
        check(address)
        return original_create(address,*args,**kwargs)
    original_create=socket.create_connection
    patch.setattr(socket.socket,'connect',connect)
    patch.setattr(socket.socket,'connect_ex',connect_ex)
    patch.setattr(socket,'create_connection',create_connection)
    patch.setattr(socket,'getaddrinfo',resolve)
    yield
    patch.undo()
