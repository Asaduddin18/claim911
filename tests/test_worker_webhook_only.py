import pytest

from coordinator.worker import validate_webhook_only_profile


def test_webhook_only_worker_requires_key_free_phone_paused_sandbox():
    validate_webhook_only_profile({
        'environment':'sandbox','bolna_api_key':None,
        'live_calls_enabled':False,'outbound_paused':True,
    })


@pytest.mark.parametrize('changes', [
    {'environment':'operational'},
    {'bolna_api_key':'provider-key'},
    {'live_calls_enabled':True},
    {'outbound_paused':False},
])
def test_webhook_only_worker_refuses_any_profile_that_can_reach_provider_or_phone(changes):
    config={'environment':'sandbox','bolna_api_key':None,
        'live_calls_enabled':False,'outbound_paused':True}|changes
    with pytest.raises(PermissionError):
        validate_webhook_only_profile(config)
