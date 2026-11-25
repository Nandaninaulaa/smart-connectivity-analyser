"""Independent IPv4 and IPv6 connectivity diagnostics."""

import errno
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError


CHECK_HOST = "one.one.one.one"
CHECK_PORT = 443
CONNECT_TIMEOUT_SECONDS = 1.5
RESOLVER_TIMEOUT_SECONDS = 1.5
_RESOLVER_POOL = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="protocol-dns",
)


def _unavailable(reason):
    return {"status": "unavailable", "reason": reason}


def _check_family(family):
    if family == socket.AF_INET6 and not socket.has_ipv6:
        return {"status": "unsupported", "reason": "not_supported"}

    try:
        resolution = _RESOLVER_POOL.submit(
            socket.getaddrinfo,
            CHECK_HOST,
            CHECK_PORT,
            family=family,
            type=socket.SOCK_STREAM,
        )
        addresses = resolution.result(timeout=RESOLVER_TIMEOUT_SECONDS)
    except TimeoutError:
        return _unavailable("timeout")
    except socket.gaierror:
        return _unavailable("dns_failure")

    if not addresses:
        return _unavailable("dns_failure")

    saw_timeout = False
    saw_supported_socket = False
    for address in addresses:
        address_family, socket_type, protocol, _, sockaddr = address
        try:
            connection = socket.socket(
                address_family,
                socket_type,
                protocol,
            )
        except OSError as error:
            if (
                address_family == socket.AF_INET6
                and error.errno in (errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT)
            ):
                return {"status": "unsupported", "reason": "not_supported"}
            continue

        saw_supported_socket = True
        try:
            connection.settimeout(CONNECT_TIMEOUT_SECONDS)
            connection.connect(sockaddr)
            return {"status": "available", "reason": None}
        except (socket.timeout, TimeoutError):
            saw_timeout = True
        except OSError as error:
            if error.errno in (errno.ETIMEDOUT,):
                saw_timeout = True
        finally:
            connection.close()

    if saw_timeout:
        return _unavailable("timeout")
    if not saw_supported_socket:
        return _unavailable("connection_failure")
    return _unavailable("connection_failure")


def detect_network_protocols():
    """Check outbound IPv4 and IPv6 independently with bounded connects.

    The hostname and port are fixed to prevent this diagnostic from being
    used as an arbitrary network probe. Only safe result categories are
    returned; system resolver and socket details are not exposed.
    """
    ipv4 = _check_family(socket.AF_INET)
    ipv6 = _check_family(socket.AF_INET6)
    return {
        "connected": (
            ipv4["status"] == "available"
            or ipv6["status"] == "available"
        ),
        "ipv4": ipv4,
        "ipv6": ipv6,
    }

