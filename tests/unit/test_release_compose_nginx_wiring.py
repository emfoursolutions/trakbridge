# ABOUTME: Regression tests for T4.2 — the release docker-compose.yml
# ABOUTME: must ship an nginx reverse proxy so operators aren't left on plain HTTP.
"""T4.2 — release docker-compose.yml must terminate TLS via nginx.

Background: contamination from dev/staging compose files removed
the nginx reverse-proxy service from the release
``docker-compose.yml`` and left a placeholder comment saying
"Traefik handles reverse proxy". That reasoning applies to the
dev/staging stacks (which sit behind external Traefik) but broke
the release stack — operators standing up a shipped compose got
plain HTTP on port 5000 with no TLS terminator.

The fix wires the existing ``init/nginx/nginx.conf`` back in as
a first-class service in the release compose. Dev/staging compose
files are intentionally not touched.
"""

from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - test dep, should be installed
    yaml = None


RELEASE_COMPOSE = Path("docker-compose.yml")
NGINX_CONF = Path("init/nginx/nginx.conf")


@pytest.fixture(scope="module")
def release_compose():
    if yaml is None:
        pytest.skip("pyyaml not available")
    return yaml.safe_load(RELEASE_COMPOSE.read_text())


class TestReleaseComposeHasNginxService:
    """Release docker-compose.yml ships nginx as the reverse proxy."""

    def test_nginx_service_defined(self, release_compose):
        services = release_compose.get("services", {})
        assert "nginx" in services, (
            "docker-compose.yml is missing an nginx service. T4.2 "
            "requires nginx to be re-wired as the shipped reverse "
            "proxy so operators aren't left on plain HTTP."
        )

    def test_nginx_publishes_https_and_http_ports(self, release_compose):
        nginx = release_compose["services"]["nginx"]
        ports = nginx.get("ports", [])
        port_specs = [str(p) for p in ports]
        # Accept either "80:80" or "0.0.0.0:80:80" style.
        assert any("443:443" in p for p in port_specs), (
            f"nginx must publish 443 for HTTPS; got ports={ports}"
        )
        assert any("80:80" in p for p in port_specs), (
            f"nginx must publish 80 for HTTP->HTTPS redirect; "
            f"got ports={ports}"
        )

    def test_nginx_mounts_configured_conf_file(self, release_compose):
        nginx = release_compose["services"]["nginx"]
        volumes = nginx.get("volumes", []) or []
        assert any("init/nginx/nginx.conf" in str(v) for v in volumes), (
            f"nginx must mount init/nginx/nginx.conf; got volumes={volumes}"
        )
        assert any("init/nginx/ssl" in str(v) for v in volumes), (
            f"nginx must mount init/nginx/ssl for cert material; "
            f"got volumes={volumes}"
        )

    def test_nginx_depends_on_trakbridge(self, release_compose):
        """Order matters — nginx starting before trakbridge is ready
        wastes deploy time on 502s."""
        nginx = release_compose["services"]["nginx"]
        depends = nginx.get("depends_on", {})
        # Accept either short-form list or long-form dict.
        if isinstance(depends, list):
            assert "trakbridge" in depends
        else:
            assert "trakbridge" in depends, (
                f"nginx should depend on trakbridge; got depends_on={depends}"
            )


class TestTrakBridgeIsInternalOnly:
    """The application service must not publish port 5000 to the host
    anymore; nginx is the only ingress."""

    def test_trakbridge_does_not_publish_port_5000(self, release_compose):
        trakbridge = release_compose["services"]["trakbridge"]
        ports = trakbridge.get("ports", []) or []
        port_specs = [str(p) for p in ports]
        for spec in port_specs:
            assert "5000:5000" not in spec, (
                f"trakbridge must not publish 5000 to the host — "
                f"nginx is the only ingress. Got ports={ports}"
            )

    def test_trakbridge_no_longer_on_traefik_frontend_network(
        self, release_compose
    ):
        trakbridge = release_compose["services"]["trakbridge"]
        networks = trakbridge.get("networks", []) or []
        # Networks can be a list or a dict of names → config.
        network_names = (
            list(networks.keys()) if isinstance(networks, dict) else list(networks)
        )
        assert "frontend" not in network_names, (
            f"trakbridge should not attach to the external Traefik "
            f"`frontend` network — nginx is the shipped proxy. "
            f"Got networks={networks}"
        )


class TestNginxUpstreamMatchesServiceName:
    """The nginx.conf upstream must resolve to the actual compose
    service name; otherwise nginx logs 502 forever."""

    def test_upstream_points_at_trakbridge_service(self):
        conf = NGINX_CONF.read_text()
        # Upstream block references `server <name>:5000;`
        # Accept the compose service name "trakbridge".
        assert "server trakbridge:5000" in conf, (
            "init/nginx/nginx.conf upstream must reference "
            "`trakbridge:5000` — that is the release compose "
            "service name."
        )
