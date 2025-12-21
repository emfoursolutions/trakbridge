"""
ABOUTME: TrakBridge identity CoT generation tests
ABOUTME: Tests self-identification messages sent to TAK servers

Unit tests for TrakBridge identity CoT message generation.

Tests the _generate_trakbridge_identity_cot static method that creates
self-identification messages for TrakBridge to appear in TAK rosters
and optionally on maps.
"""

import uuid
from datetime import datetime
from lxml import etree
import pytest

from models.tak_server import TakServer
from services.cot_service_integration import QueuedCOTService


class TestTrakBridgeIdentityCOT:
    """Test TrakBridge identity CoT generation"""

    def test_identity_cot_with_location(self, app, db_session):
        """Test identity CoT with MGRS location generates team member format"""
        with app.app_context():
            unique_name = f"test-server-{uuid.uuid4().hex[:8]}"
            server = TakServer(
                name=unique_name,
                host="127.0.0.1",
                port=8089,
                protocol="tls",
                identity_enabled=True,
                identity_callsign="TrakBridge-Test",
                identity_role="HQ",
                identity_team_color="Blue",
                identity_location_mgrs="38SMB4484",
                identity_uid_suffix="123456",
            )
            db_session.add(server)
            db_session.commit()

            cot_xml = QueuedCOTService._generate_trakbridge_identity_cot(server)

            assert cot_xml is not None
            root = etree.fromstring(cot_xml)

            # Verify UID format
            assert root.get("uid") == f"trakbridge-{unique_name}-123456"

            # Verify team member type
            assert root.get("type") == "a-f-G-U-C"

            # Verify point element exists
            assert root.find("point") is not None

            # Verify takv has real version (not hardcoded "TrakBridge")
            takv = root.find(".//takv")
            assert takv is not None
            assert takv.get("version") != "TrakBridge"
            assert len(takv.get("version")) > 0

            # Verify team member elements
            contact = root.find(".//contact")
            assert contact is not None
            assert contact.get("callsign") == "TrakBridge-Test"

            group = root.find(".//__group")
            assert group is not None
            assert group.get("role") == "HQ"
            assert group.get("name") == "Blue"

    def test_identity_cot_without_location(self, app, db_session):
        """Test identity CoT without location generates status-only format"""
        with app.app_context():
            unique_name = f"test-server-{uuid.uuid4().hex[:8]}"
            server = TakServer(
                name=unique_name,
                host="127.0.0.1",
                port=8089,
                protocol="tls",
                identity_enabled=True,
                identity_callsign="TrakBridge-Test",
                identity_uid_suffix="123456",
            )
            db_session.add(server)
            db_session.commit()

            cot_xml = QueuedCOTService._generate_trakbridge_identity_cot(server)

            assert cot_xml is not None
            root = etree.fromstring(cot_xml)

            # Verify status type
            assert root.get("type") == "b-t-c-v"

            # Verify NO point element
            assert root.find("point") is None

    def test_identity_disabled_without_callsign(self, app, db_session):
        """Test identity CoT is disabled when no callsign configured"""
        with app.app_context():
            unique_name = f"test-server-{uuid.uuid4().hex[:8]}"
            server = TakServer(
                name=unique_name, host="127.0.0.1", port=8089, protocol="tls"
            )
            db_session.add(server)
            db_session.commit()

            cot_xml = QueuedCOTService._generate_trakbridge_identity_cot(server)
            assert cot_xml is None

    def test_uid_suffix_generation(self, app, db_session):
        """Test UID suffix is generated and persisted"""
        with app.app_context():
            unique_name = f"test-server-{uuid.uuid4().hex[:8]}"
            server = TakServer(
                name=unique_name,
                host="127.0.0.1",
                port=8089,
                protocol="tls",
                identity_enabled=True,
                identity_callsign="TrakBridge-Test",
            )
            db_session.add(server)
            db_session.commit()

            # First call generates suffix
            cot_xml = QueuedCOTService._generate_trakbridge_identity_cot(server)
            suffix1 = server.identity_uid_suffix

            assert suffix1 is not None
            assert len(suffix1) == 6
            assert suffix1.isdigit()

            # Second call reuses same suffix
            cot_xml2 = QueuedCOTService._generate_trakbridge_identity_cot(server)
            assert server.identity_uid_suffix == suffix1

    def test_identity_cot_xml_structure(self, app, db_session):
        """Test that identity CoT has required XML structure"""
        with app.app_context():
            unique_name = f"test-server-{uuid.uuid4().hex[:8]}"
            server = TakServer(
                name=unique_name,
                host="127.0.0.1",
                port=8089,
                protocol="tls",
                identity_enabled=True,
                identity_callsign="TrakBridge-Test",
                identity_location_mgrs="38SMB4484",
                identity_uid_suffix="123456",
            )
            db_session.add(server)
            db_session.commit()

            cot_xml = QueuedCOTService._generate_trakbridge_identity_cot(server)

            assert cot_xml is not None
            root = etree.fromstring(cot_xml)

            # Verify event attributes
            assert root.get("version") == "2.0"
            assert root.get("how") == "m-g"
            assert root.get("time") is not None
            assert root.get("start") is not None
            assert root.get("stale") is not None

            # Verify detail structure
            detail = root.find("detail")
            assert detail is not None

            # Verify required elements
            assert detail.find("takv") is not None
            assert detail.find("contact") is not None
            assert detail.find("uid") is not None
            assert detail.find("status") is not None
            assert detail.find("track") is not None  # Since we have location

    def test_invalid_mgrs_fallback(self, app, db_session):
        """Test that invalid MGRS location falls back to status-only"""
        with app.app_context():
            unique_name = f"test-server-{uuid.uuid4().hex[:8]}"
            server = TakServer(
                name=unique_name,
                host="127.0.0.1",
                port=8089,
                protocol="tls",
                identity_enabled=True,
                identity_callsign="TrakBridge-Test",
                identity_location_mgrs="INVALID_MGRS",
                identity_uid_suffix="123456",
            )
            db_session.add(server)
            db_session.commit()

            cot_xml = QueuedCOTService._generate_trakbridge_identity_cot(server)

            assert cot_xml is not None
            root = etree.fromstring(cot_xml)

            # Should fall back to status-only type
            assert root.get("type") == "b-t-c-v"

            # Should NOT have point element
            assert root.find("point") is None
