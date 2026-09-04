# ABOUTME: Regression tests for T7.8 — the TAK server delete guard must
# ABOUTME: check the many-to-many stream_tak_servers table, not just the legacy FK.
"""T7.8 — TAK server delete guard must cover the M2M table.

The legacy Stream.tak_server_id foreign key and the newer
``stream_tak_servers`` M2M table are two independent ways a
stream can be linked to a TAK server. The delete guard at
``routes/tak_servers.py:522`` originally checked only the
legacy ``server.streams`` collection, so a stream linked only
via the M2M association was silently orphaned when the server
was deleted — the M2M row cascaded away and the stream kept
reporting success while delivering to one fewer destination.
"""

from models.stream import Stream
from models.tak_server import TakServer
from tests.conftest import get_csrf_token


def _create_server(session, **overrides):
    kwargs = dict(
        name="Test Server", host="localhost", port=8089, protocol="tcp"
    )
    kwargs.update(overrides)
    server = TakServer(**kwargs)
    session.add(server)
    session.commit()
    return server


def _create_stream(session, name="Test Stream", plugin_type="garmin"):
    stream = Stream(name=name, plugin_type=plugin_type, is_active=False)
    stream.set_plugin_config({})
    session.add(stream)
    session.commit()
    return stream


class TestDeleteGuardCoversManyToMany:
    """A stream linked only via the M2M table must block deletion too."""

    def test_delete_refused_when_only_m2m_association_exists(
        self, authenticated_client, app, db_session
    ):
        """Server with an M2M-only stream must not be deletable."""
        client = authenticated_client("admin")
        csrf = get_csrf_token(client, app)
        with app.app_context():
            server = _create_server(db_session)
            stream = _create_stream(db_session)
            # Associate only via the M2M table — leave the legacy FK None.
            stream.tak_servers.append(server)
            db_session.commit()
            server_id = server.id

        response = client.delete(
            f"/tak-servers/{server_id}/delete",
            headers={"X-CSRFToken": csrf},
        )
        assert response.status_code == 400, (
            f"Delete of M2M-linked server should have been refused; "
            f"got {response.status_code}: {response.get_data(as_text=True)}"
        )

        # And the server must still exist.
        with app.app_context():
            assert TakServer.query.get(server_id) is not None, (
                "Server was deleted despite an active M2M stream link — "
                "T7.8 guard is missing the M2M check."
            )

    def test_delete_refused_when_only_legacy_fk_association_exists(
        self, authenticated_client, app, db_session
    ):
        """Regression guard: legacy-FK-only path must remain blocked."""
        client = authenticated_client("admin")
        csrf = get_csrf_token(client, app)
        with app.app_context():
            server = _create_server(db_session, name="Legacy Server")
            stream = _create_stream(db_session, name="Legacy Stream")
            stream.tak_server_id = server.id
            db_session.commit()
            server_id = server.id

        response = client.delete(
            f"/tak-servers/{server_id}/delete",
            headers={"X-CSRFToken": csrf},
        )
        assert response.status_code == 400

        with app.app_context():
            assert TakServer.query.get(server_id) is not None

    def test_delete_allowed_when_no_associations(
        self, authenticated_client, app, db_session
    ):
        """A server with zero streams (either path) must still be deletable."""
        client = authenticated_client("admin")
        csrf = get_csrf_token(client, app)
        with app.app_context():
            server = _create_server(db_session, name="Lonely Server")
            server_id = server.id

        response = client.delete(
            f"/tak-servers/{server_id}/delete",
            headers={"X-CSRFToken": csrf},
        )
        assert response.status_code == 200, (
            f"Server with no stream associations should be deletable; "
            f"got {response.status_code}: {response.get_data(as_text=True)}"
        )

        with app.app_context():
            assert TakServer.query.get(server_id) is None
