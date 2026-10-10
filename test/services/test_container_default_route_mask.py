import pytest

from app.config import config


HEADER = "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
SPLIT_ROUTE = "tun0 00000000 0100080A 0003 0 0 0 00000080 0 0 0\n"
DEFAULT_ROUTE = "eth0 00000000 010011AC 0003 0 0 100 00000000 0 0 0\n"


@pytest.mark.parametrize("routes,expected", [
    (SPLIT_ROUTE + DEFAULT_ROUTE, "172.17.0.1"),
    (SPLIT_ROUTE, ""),
])
def test_zero_destination_network_route_is_not_a_default_gateway(tmp_path, routes, expected):
    route_path = tmp_path / "route"
    route_path.write_text(HEADER + routes)
    assert config.get_container_default_gateway_ip(str(route_path)) == expected
