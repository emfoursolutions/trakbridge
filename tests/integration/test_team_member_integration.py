"""
ABOUTME: End-to-end integration tests for team member functionality (Phase 5)
ABOUTME: Tests complete workflow from configuration through COT generation and transmission
"""

import pytest
import asyncio
import uuid
from unittest.mock import patch, MagicMock, Mock
from lxml import etree
from datetime import datetime, timedelta

from app import create_app
from database import db
from models.stream import Stream
from models.callsign_mapping import CallsignMapping
from models.tak_server import TakServer
from models.user import User, UserRole, AuthProvider, UserSession
from plugins.garmin_plugin import GarminPlugin
from services.cot_service_integration import QueuedCOTService
from services.auth.auth_manager import AuthenticationManager


@pytest.fixture
def integration_app():
    """Create test application for integration tests"""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def admin_user(integration_app):
    """Create test admin user"""
    with integration_app.app_context():
        admin_user = User(
            username="integration_admin",
            email="integration_admin@test.com",
            role=UserRole.ADMIN,
            auth_provider=AuthProvider.LOCAL,
            is_active=True
        )
        admin_user.set_password("testpass123")
        db.session.add(admin_user)
        db.session.commit()
        return admin_user


@pytest.fixture
def integration_client(integration_app, admin_user):
    """Create authenticated test client for integration tests"""
    client = integration_app.test_client()

    # Create session for admin user
    with integration_app.app_context():
        auth_manager = AuthenticationManager()
        session = auth_manager.create_session(admin_user)

        # Set session cookies
        with client.session_transaction() as sess:
            sess["session_id"] = session.session_id
            sess["user_id"] = admin_user.id

    return client


@pytest.fixture
def tak_server(integration_app):
    """Create a test TAK server"""
    with integration_app.app_context():
        unique_id = uuid.uuid4().hex[:8]
        server = TakServer(
            name=f"Integration Test TAK Server {unique_id}",
            host="test.example.com",
            port=8087,
            protocol="tls",
            verify_ssl=True,
        )
        db.session.add(server)
        db.session.commit()
        return server


@pytest.fixture
def team_member_stream(integration_app, tak_server):
    """Create a test stream with team member configuration enabled"""
    with integration_app.app_context():
        unique_id = uuid.uuid4().hex[:8]
        stream = Stream(
            name=f"Team Member Test Stream {unique_id}",
            plugin_type="garmin_plugin",
            enable_callsign_mapping=True,
            callsign_identifier_field="imei",
            callsign_error_handling="fallback",
            enable_per_callsign_cot_types=True,
        )
        stream.tak_servers = [tak_server]
        db.session.add(stream)
        db.session.commit()
        return stream


class TestTeamMemberEndToEndWorkflow:
    """Test complete team member workflow from configuration to transmission"""

    def test_complete_single_team_member_workflow(self, integration_client, integration_app, team_member_stream):
        """Test complete workflow: API configuration → plugin processing → COT generation"""

        with integration_app.app_context():
            # Step 1: Configure team member via API
            payload = {
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "mappings": [
                    {
                        "identifier_value": "123456789012345",
                        "custom_callsign": "Alpha1",
                        "cot_type_override": "team_member",
                        "team_role": "Team Lead",
                        "team_color": "Blue",
                        "enabled": True
                    }
                ]
            }

            response = integration_client.post(
                f"/api/streams/{team_member_stream.id}/callsign-mappings",
                json=payload
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True

            # Verify mapping was saved to database
            mapping = CallsignMapping.query.filter_by(
                stream_id=team_member_stream.id,
                identifier_value="123456789012345"
            ).first()

            assert mapping is not None
            assert mapping.custom_callsign == "Alpha1"
            assert mapping.cot_type_override == "team_member"
            assert mapping.team_role == "Team Lead"
            assert mapping.team_color == "Blue"

            # Step 2: Simulate plugin processing with callsign mapping
            plugin_config = {
                "url": "https://test.example.com/feed.kml",
                "username": "test",
                "password": "test"
            }
            plugin = GarminPlugin(plugin_config)

            tracker_data = [
                {
                    "name": "OriginalDeviceName",
                    "lat": 27.9637327,
                    "lon": 43.571495,
                    "altitude": 608.938,
                    "accuracy": 10.0,
                    "additional_data": {
                        "raw_placemark": {
                            "extended_data": {
                                "IMEI": "123456789012345"
                            }
                        }
                    }
                }
            ]

            # Build callsign map from database mapping
            callsign_map = {
                "123456789012345": {
                    "custom_callsign": mapping.custom_callsign,
                    "team_member_enabled": True,
                    "team_role": mapping.team_role,
                    "team_color": mapping.team_color
                }
            }

            # Apply callsign mapping through plugin
            plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

            # Verify plugin added team member metadata
            assert tracker_data[0]["name"] == "Alpha1"
            assert tracker_data[0]["additional_data"]["team_member_enabled"] is True
            assert tracker_data[0]["additional_data"]["team_role"] == "Team Lead"
            assert tracker_data[0]["additional_data"]["team_color"] == "Blue"

            # Step 3: Generate COT XML from processed location data
            locations = [
                {
                    "uid": "ANDROID-test123",
                    "name": tracker_data[0]["name"],
                    "lat": tracker_data[0]["lat"],
                    "lon": tracker_data[0]["lon"],
                    "altitude": tracker_data[0]["altitude"],
                    "accuracy": tracker_data[0]["accuracy"],
                    "additional_data": tracker_data[0]["additional_data"]
                }
            ]

            # Generate COT events
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                events = loop.run_until_complete(
                    QueuedCOTService._create_pytak_events(
                        locations, "a-f-G-E-V-C", 300
                    )
                )
            finally:
                loop.close()

            assert len(events) == 1

            # Step 4: Verify COT XML structure
            event_xml = events[0]
            root = etree.fromstring(event_xml)

            # Verify team member COT type
            assert root.get("type") == "a-f-G-U-C"
            assert root.get("how") == "h-e"

            # Verify detail elements
            detail = root.find("detail")
            assert detail is not None

            # Verify contact element
            contact = detail.find("contact")
            assert contact is not None
            assert contact.get("callsign") == "Alpha1"
            assert contact.get("endpoint") == "*:-1:stcp"

            # Verify uid element
            uid = detail.find("uid")
            assert uid is not None
            assert uid.get("Droid") == "Alpha1"

            # Verify __group element
            group = detail.find("__group")
            assert group is not None
            assert group.get("role") == "Team Lead"
            assert group.get("name") == "Blue"

    def test_multiple_team_members_workflow(self, integration_client, integration_app, team_member_stream):
        """Test workflow with multiple team members configured"""

        with integration_app.app_context():
            # Configure multiple team members
            payload = {
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "mappings": [
                    {
                        "identifier_value": "111111111111111",
                        "custom_callsign": "TeamLead1",
                        "cot_type_override": "team_member",
                        "team_role": "Team Lead",
                        "team_color": "Blue",
                        "enabled": True
                    },
                    {
                        "identifier_value": "222222222222222",
                        "custom_callsign": "Sniper1",
                        "cot_type_override": "team_member",
                        "team_role": "Sniper",
                        "team_color": "Green",
                        "enabled": True
                    },
                    {
                        "identifier_value": "333333333333333",
                        "custom_callsign": "Medic1",
                        "cot_type_override": "team_member",
                        "team_role": "Medic",
                        "team_color": "Red",
                        "enabled": True
                    }
                ]
            }

            response = integration_client.post(
                f"/api/streams/{team_member_stream.id}/callsign-mappings",
                json=payload
            )

            assert response.status_code == 200

            # Verify all mappings were created
            mappings = CallsignMapping.query.filter_by(
                stream_id=team_member_stream.id
            ).all()

            assert len(mappings) == 3

            # Process multiple trackers through plugin
            plugin_config = {
                "url": "https://test.example.com/feed.kml",
                "username": "test",
                "password": "test"
            }
            plugin = GarminPlugin(plugin_config)

            tracker_data = [
                {
                    "name": "Device1",
                    "lat": 27.0,
                    "lon": 43.0,
                    "altitude": 100.0,
                    "accuracy": 10.0,
                    "additional_data": {
                        "raw_placemark": {
                            "extended_data": {"IMEI": "111111111111111"}
                        }
                    }
                },
                {
                    "name": "Device2",
                    "lat": 28.0,
                    "lon": 44.0,
                    "altitude": 200.0,
                    "accuracy": 10.0,
                    "additional_data": {
                        "raw_placemark": {
                            "extended_data": {"IMEI": "222222222222222"}
                        }
                    }
                },
                {
                    "name": "Device3",
                    "lat": 29.0,
                    "lon": 45.0,
                    "altitude": 300.0,
                    "accuracy": 10.0,
                    "additional_data": {
                        "raw_placemark": {
                            "extended_data": {"IMEI": "333333333333333"}
                        }
                    }
                }
            ]

            # Build callsign map from database
            callsign_map = {}
            for mapping in mappings:
                callsign_map[mapping.identifier_value] = {
                    "custom_callsign": mapping.custom_callsign,
                    "team_member_enabled": True,
                    "team_role": mapping.team_role,
                    "team_color": mapping.team_color
                }

            plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

            # Generate COT for all trackers
            locations = [
                {
                    "uid": f"ANDROID-{i}",
                    "name": data["name"],
                    "lat": data["lat"],
                    "lon": data["lon"],
                    "altitude": data["altitude"],
                    "accuracy": data["accuracy"],
                    "additional_data": data["additional_data"]
                }
                for i, data in enumerate(tracker_data)
            ]

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                events = loop.run_until_complete(
                    QueuedCOTService._create_pytak_events(
                        locations, "a-f-G-E-V-C", 300
                    )
                )
            finally:
                loop.close()

            assert len(events) == 3

            # Verify each COT event
            expected_configs = [
                ("TeamLead1", "Team Lead", "Blue"),
                ("Sniper1", "Sniper", "Green"),
                ("Medic1", "Medic", "Red")
            ]

            for event_xml, (callsign, role, color) in zip(events, expected_configs):
                root = etree.fromstring(event_xml)

                # Verify team member type
                assert root.get("type") == "a-f-G-U-C"

                detail = root.find("detail")

                # Verify callsign
                contact = detail.find("contact")
                assert contact.get("callsign") == callsign

                # Verify role and color
                group = detail.find("__group")
                assert group.get("role") == role
                assert group.get("name") == color

    def test_mixed_team_member_and_standard_trackers_workflow(self, integration_client, integration_app, team_member_stream):
        """Test workflow with both team members and standard trackers"""

        with integration_app.app_context():
            # Configure mixed mappings
            payload = {
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "mappings": [
                    {
                        "identifier_value": "111111111111111",
                        "custom_callsign": "TeamMember1",
                        "cot_type_override": "team_member",
                        "team_role": "Team Lead",
                        "team_color": "Blue",
                        "enabled": True
                    },
                    {
                        "identifier_value": "222222222222222",
                        "custom_callsign": "StandardTracker",
                        "cot_type_override": None,  # Standard point
                        "enabled": True
                    }
                ]
            }

            response = integration_client.post(
                f"/api/streams/{team_member_stream.id}/callsign-mappings",
                json=payload
            )

            assert response.status_code == 200

            # Process through plugin
            plugin_config = {
                "url": "https://test.example.com/feed.kml",
                "username": "test",
                "password": "test"
            }
            plugin = GarminPlugin(plugin_config)

            tracker_data = [
                {
                    "name": "Device1",
                    "lat": 27.0,
                    "lon": 43.0,
                    "additional_data": {
                        "raw_placemark": {
                            "extended_data": {"IMEI": "111111111111111"}
                        }
                    }
                },
                {
                    "name": "Device2",
                    "lat": 28.0,
                    "lon": 44.0,
                    "additional_data": {
                        "raw_placemark": {
                            "extended_data": {"IMEI": "222222222222222"}
                        }
                    }
                }
            ]

            # Build callsign map
            mappings = CallsignMapping.query.filter_by(
                stream_id=team_member_stream.id
            ).all()

            callsign_map = {}
            for mapping in mappings:
                if mapping.cot_type_override == "team_member":
                    callsign_map[mapping.identifier_value] = {
                        "custom_callsign": mapping.custom_callsign,
                        "team_member_enabled": True,
                        "team_role": mapping.team_role,
                        "team_color": mapping.team_color
                    }
                else:
                    callsign_map[mapping.identifier_value] = {
                        "custom_callsign": mapping.custom_callsign
                    }

            plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

            # Generate COT
            locations = [
                {
                    "uid": f"ANDROID-{i}",
                    "name": data["name"],
                    "lat": data["lat"],
                    "lon": data["lon"],
                    "additional_data": data["additional_data"]
                }
                for i, data in enumerate(tracker_data)
            ]

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                events = loop.run_until_complete(
                    QueuedCOTService._create_pytak_events(
                        locations, "a-f-G-E-V-C", 300
                    )
                )
            finally:
                loop.close()

            assert len(events) == 2

            # Parse events
            roots = [etree.fromstring(event) for event in events]

            # First should be team member
            assert roots[0].get("type") == "a-f-G-U-C"
            detail0 = roots[0].find("detail")
            assert detail0.find("__group") is not None
            assert detail0.find("contact").get("callsign") == "TeamMember1"

            # Second should be standard
            assert roots[1].get("type") == "a-f-G-E-V-C"
            detail1 = roots[1].find("detail")
            assert detail1.find("__group") is None
            assert detail1.find("contact").get("callsign") == "StandardTracker"


class TestTeamMemberPerformance:
    """Test performance characteristics of team member feature"""

    def test_team_member_processing_performance(self, integration_client, integration_app, team_member_stream):
        """Test that team member processing doesn't significantly impact performance"""

        with integration_app.app_context():
            # Configure 10 team members
            mappings = []
            for i in range(10):
                mappings.append({
                    "identifier_value": f"{i:015d}",
                    "custom_callsign": f"Member{i}",
                    "cot_type_override": "team_member",
                    "team_role": "Team Member",
                    "team_color": "Blue",
                    "enabled": True
                })

            payload = {
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "mappings": mappings
            }

            response = integration_client.post(
                f"/api/streams/{team_member_stream.id}/callsign-mappings",
                json=payload
            )

            assert response.status_code == 200

            # Create tracker data
            plugin_config = {
                "url": "https://test.example.com/feed.kml",
                "username": "test",
                "password": "test"
            }
            plugin = GarminPlugin(plugin_config)

            tracker_data = [
                {
                    "name": f"Device{i}",
                    "lat": 27.0 + i * 0.1,
                    "lon": 43.0 + i * 0.1,
                    "additional_data": {
                        "raw_placemark": {
                            "extended_data": {"IMEI": f"{i:015d}"}
                        }
                    }
                }
                for i in range(10)
            ]

            # Build callsign map
            db_mappings = CallsignMapping.query.filter_by(
                stream_id=team_member_stream.id
            ).all()

            callsign_map = {}
            for mapping in db_mappings:
                callsign_map[mapping.identifier_value] = {
                    "custom_callsign": mapping.custom_callsign,
                    "team_member_enabled": True,
                    "team_role": mapping.team_role,
                    "team_color": mapping.team_color
                }

            # Measure plugin processing time
            import time
            start_time = time.time()
            plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)
            plugin_time = time.time() - start_time

            # Plugin processing should be fast (< 100ms for 10 trackers)
            assert plugin_time < 0.1, f"Plugin processing took {plugin_time}s, expected < 0.1s"

            # Measure COT generation time
            locations = [
                {
                    "uid": f"ANDROID-{i}",
                    "name": data["name"],
                    "lat": data["lat"],
                    "lon": data["lon"],
                    "additional_data": data["additional_data"]
                }
                for i, data in enumerate(tracker_data)
            ]

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                start_time = time.time()
                events = loop.run_until_complete(
                    QueuedCOTService._create_pytak_events(
                        locations, "a-f-G-E-V-C", 300
                    )
                )
                cot_time = time.time() - start_time
            finally:
                loop.close()

            # COT generation should be fast (< 500ms for 10 trackers)
            assert cot_time < 0.5, f"COT generation took {cot_time}s, expected < 0.5s"

            # Verify all events generated
            assert len(events) == 10


class TestTeamMemberErrorHandling:
    """Test error handling throughout the team member workflow"""

    def test_malformed_team_member_data_handling(self, integration_client, integration_app, team_member_stream):
        """Test that malformed team member data is handled gracefully"""

        with integration_app.app_context():
            # Process tracker with incomplete team member data
            plugin_config = {
                "url": "https://test.example.com/feed.kml",
                "username": "test",
                "password": "test"
            }
            plugin = GarminPlugin(plugin_config)

            tracker_data = [
                {
                    "name": "Device1",
                    "lat": 27.0,
                    "lon": 43.0,
                    "altitude": 100.0,
                    "accuracy": 10.0,
                    "additional_data": {
                        "raw_placemark": {
                            "extended_data": {"IMEI": "123456789012345"}
                        }
                    }
                }
            ]

            # Malformed callsign map (missing role/color)
            callsign_map = {
                "123456789012345": {
                    "custom_callsign": "MalformedMember",
                    "team_member_enabled": True
                    # Missing team_role and team_color
                }
            }

            # Should not raise exception
            plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

            # Verify plugin added team member flag but with None role/color
            assert tracker_data[0]["additional_data"]["team_member_enabled"] is True
            assert tracker_data[0]["additional_data"]["team_role"] is None
            assert tracker_data[0]["additional_data"]["team_color"] is None

            # Generate COT - should handle gracefully
            locations = [
                {
                    "uid": "ANDROID-test",
                    "name": tracker_data[0]["name"],
                    "lat": tracker_data[0]["lat"],
                    "lon": tracker_data[0]["lon"],
                    "altitude": tracker_data[0]["altitude"],
                    "accuracy": tracker_data[0]["accuracy"],
                    "additional_data": tracker_data[0]["additional_data"]
                }
            ]

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                events = loop.run_until_complete(
                    QueuedCOTService._create_pytak_events(
                        locations, "a-f-G-E-V-C", 300
                    )
                )
            finally:
                loop.close()

            # Should still generate event
            assert len(events) == 1

            # Parse and verify event
            root = etree.fromstring(events[0])

            # Should still be team member type
            assert root.get("type") == "a-f-G-U-C"

            # Group element should have empty values
            detail = root.find("detail")
            group = detail.find("__group")
            assert group is not None
            # Should have empty string values for None
            assert group.get("role") == ""
            assert group.get("name") == ""

    def test_backward_compatibility_with_existing_streams(self, integration_client, integration_app, team_member_stream):
        """Test that existing streams without team member config continue working"""

        with integration_app.app_context():
            # Configure regular callsign mapping (no team member)
            payload = {
                "enable_callsign_mapping": True,
                "callsign_identifier_field": "imei",
                "mappings": [
                    {
                        "identifier_value": "123456789012345",
                        "custom_callsign": "RegularCallsign",
                        "enabled": True
                    }
                ]
            }

            response = integration_client.post(
                f"/api/streams/{team_member_stream.id}/callsign-mappings",
                json=payload
            )

            assert response.status_code == 200

            # Process through plugin
            plugin_config = {
                "url": "https://test.example.com/feed.kml",
                "username": "test",
                "password": "test"
            }
            plugin = GarminPlugin(plugin_config)

            tracker_data = [
                {
                    "name": "Device1",
                    "lat": 27.0,
                    "lon": 43.0,
                    "additional_data": {
                        "raw_placemark": {
                            "extended_data": {"IMEI": "123456789012345"}
                        }
                    }
                }
            ]

            callsign_map = {
                "123456789012345": {
                    "custom_callsign": "RegularCallsign"
                }
            }

            plugin.apply_callsign_mapping(tracker_data, "imei", callsign_map)

            # Verify no team member metadata
            assert "team_member_enabled" not in tracker_data[0]["additional_data"]

            # Generate COT - should be standard format
            locations = [
                {
                    "uid": "ANDROID-test",
                    "name": tracker_data[0]["name"],
                    "lat": tracker_data[0]["lat"],
                    "lon": tracker_data[0]["lon"],
                    "additional_data": tracker_data[0]["additional_data"]
                }
            ]

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                events = loop.run_until_complete(
                    QueuedCOTService._create_pytak_events(
                        locations, "a-f-G-E-V-C", 300
                    )
                )
            finally:
                loop.close()

            root = etree.fromstring(events[0])

            # Should be standard COT type
            assert root.get("type") == "a-f-G-E-V-C"

            # Should not have team member elements
            detail = root.find("detail")
            assert detail.find("__group") is None
