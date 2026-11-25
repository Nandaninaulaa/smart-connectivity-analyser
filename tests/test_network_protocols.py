import errno
import socket
import time

from backend import protocol_diagnostics as diagnostics


class FakeConnection:
    def __init__(self, should_timeout=False):
        self.should_timeout = should_timeout

    def settimeout(self, timeout):
        assert timeout == diagnostics.CONNECT_TIMEOUT_SECONDS

    def connect(self, _address):
        if self.should_timeout:
            raise socket.timeout()

    def close(self):
        pass


def fake_address(family):
    sockaddr = (
        ("127.0.0.1", 443)
        if family == socket.AF_INET
        else ("::1", 443, 0, 0)
    )
    return (family, socket.SOCK_STREAM, 0, "", sockaddr)


def test_detects_dual_stack_connectivity(monkeypatch):
    monkeypatch.setattr(socket, "has_ipv6", True)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, family, type: [fake_address(family)],
    )
    monkeypatch.setattr(socket, "socket", lambda *args: FakeConnection())

    assert diagnostics.detect_network_protocols() == {
        "connected": True,
        "ipv4": {"status": "available", "reason": None},
        "ipv6": {"status": "available", "reason": None},
    }


def test_ipv4_only_remains_connected_when_ipv6_dns_has_no_address(monkeypatch):
    monkeypatch.setattr(socket, "has_ipv6", True)

    def resolve(host, port, family, type):
        if family == socket.AF_INET6:
            raise socket.gaierror(socket.EAI_NONAME, "no IPv6 record")
        return [fake_address(family)]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "socket", lambda *args: FakeConnection())

    result = diagnostics.detect_network_protocols()
    assert result["connected"] is True
    assert result["ipv4"]["status"] == "available"
    assert result["ipv6"] == {
        "status": "unavailable",
        "reason": "dns_failure",
    }


def test_marks_ipv6_unsupported_when_runtime_does_not_support_it(monkeypatch):
    monkeypatch.setattr(socket, "has_ipv6", False)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, family, type: [fake_address(family)],
    )
    monkeypatch.setattr(socket, "socket", lambda *args: FakeConnection())

    result = diagnostics.detect_network_protocols()
    assert result["connected"] is True
    assert result["ipv6"] == {
        "status": "unsupported",
        "reason": "not_supported",
    }


def test_distinguishes_timeout_from_dns_failure(monkeypatch):
    monkeypatch.setattr(socket, "has_ipv6", True)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, family, type: [fake_address(family)],
    )
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args: FakeConnection(should_timeout=True),
    )

    result = diagnostics.detect_network_protocols()
    assert result["connected"] is False
    assert result["ipv4"]["reason"] == "timeout"
    assert result["ipv6"]["reason"] == "timeout"


def test_dns_timeout_is_bounded_and_reported_as_timeout(monkeypatch):
    monkeypatch.setattr(diagnostics, "RESOLVER_TIMEOUT_SECONDS", 0.01)

    def slow_resolve(*args, **kwargs):
        time.sleep(0.05)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", slow_resolve)
    result = diagnostics.detect_network_protocols()

    assert result["connected"] is False
    assert result["ipv4"]["reason"] == "timeout"
    assert result["ipv6"]["reason"] == "timeout"


def test_reports_socket_family_unsupported(monkeypatch):
    monkeypatch.setattr(socket, "has_ipv6", True)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, family, type: [fake_address(family)],
    )

    def create_socket(family, *args):
        if family == socket.AF_INET6:
            raise OSError(errno.EAFNOSUPPORT, "family unsupported")
        return FakeConnection()

    monkeypatch.setattr(socket, "socket", create_socket)
    result = diagnostics.detect_network_protocols()
    assert result["connected"] is True
    assert result["ipv6"]["status"] == "unsupported"


def test_socket_permission_failure_is_not_mislabeled_unsupported(monkeypatch):
    monkeypatch.setattr(socket, "has_ipv6", True)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, family, type: [fake_address(family)],
    )

    def create_socket(family, *args):
        if family == socket.AF_INET6:
            raise OSError(errno.EPERM, "permission denied")
        return FakeConnection()

    monkeypatch.setattr(socket, "socket", create_socket)
    result = diagnostics.detect_network_protocols()
    assert result["ipv6"] == {
        "status": "unavailable",
        "reason": "connection_failure",
    }

