"""Model input checks do not require a database or external provider."""
import json
import pytest
from paa_server.modules.model_services.schemas import ServiceInput, parameters



def test_parameter_limit_uses_compact_utf8():
    value = {f'k{i}': 'a' * 503 for i in range(8)}
    assert len(json.dumps(value, separators=(',', ':')).encode()) == 4089
    assert parameters(value) == value
    value['k0'] += 'a' * 8
    with pytest.raises(ValueError, match='4 KiB'):
        parameters(value)


@pytest.mark.parametrize('key', ['测试key', 'key\t', 'key\x7f'])
def test_non_header_safe_keys_fail_before_persistence(key):
    with pytest.raises(ValueError, match='可打印 ASCII'):
        ServiceInput(name='test', baseUrl='https://example.com/v1', apiKey=key)
