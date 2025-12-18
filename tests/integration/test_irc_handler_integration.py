# ABOUTME: Integration tests for IRC handler end-to-end CoT message flow
# ABOUTME: Tests complete message processing from CoT XML to IRC output with filtering and formatting

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from plugins.irc_handler import IRCHandler


class TestIRCHandlerIntegration:
    """Integration tests for IRC handler end-to-end flow"""

    def setup_method(self):
        """Set up test fixtures"""
        self.base_config = {
            "server": "irc.test.com",
            "port": 6667,
            "use_ssl": "false",
            "nickname": "TestBot",
            "channel": "#test",
            "password": "",
            "uid_filter": "",
            "global_geofence_enabled": "false",
            "global_geofence_bounds": {},
            "message_rules": [],
        }

    @pytest.mark.asyncio
    async def test_end_to_end_chat_message(self):
        """Test complete flow: CoT XML → filtering → template formatting → IRC message"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}: {remarks}",
                "enabled": True,
            }
        ]

        handler = IRCHandler(config)

        # Mock IRC connection
        handler._connected = True
        handler._writer = MagicMock()
        handler._writer.is_closing.return_value = False
        handler._writer.drain = AsyncMock()

        # Sample chat message CoT
        cot_xml = b"""<?xml version="1.0"?>
        <event version="2.0" uid="ANDROID-123" type="b-t-f" time="2024-01-01T12:00:00Z" start="2024-01-01T12:00:00Z" stale="2024-01-01T12:05:00Z">
            <point lat="40.7128" lon="-74.0060" hae="10.0" ce="9999999.0" le="9999999.0" />
            <detail>
                <contact callsign="TestUser"/>
                <remarks>Hello from TAK!</remarks>
            </detail>
        </event>"""

        # Process message
        await handler.handle_cot_message(cot_xml, tak_server_id=1)

        # Verify IRC message was sent with correct format
        assert handler._writer.write.called
        sent_data = handler._writer.write.call_args[0][0].decode('utf-8')
        assert "PRIVMSG #test :[CHAT] TestUser: Hello from TAK!" in sent_data

    @pytest.mark.asyncio
    async def test_end_to_end_with_global_geofence(self):
        """Test complete flow with global geofence filtering"""
        config = self.base_config.copy()
        config["global_geofence_enabled"] = "true"
        config["global_geofence_bounds"] = {
            "north": 40.8,
            "south": 40.6,
            "east": -73.9,
            "west": -74.1
        }
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-a-*",
                "format_template": "[ALERT] {callsign} at {lat},{lon}",
                "enabled": True,
            }
        ]

        handler = IRCHandler(config)
        handler._connected = True
        handler._writer = MagicMock()
        handler._writer.is_closing.return_value = False
        handler._writer.drain = AsyncMock()

        # Message inside geofence
        cot_inside = b"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-1" type="b-a-o-can">
            <point lat="40.7" lon="-74.0" />
            <detail><contact callsign="InsideUser"/></detail>
        </event>"""

        await handler.handle_cot_message(cot_inside, tak_server_id=1)
        assert handler._writer.write.called

        # Reset mock
        handler._writer.reset_mock()

        # Message outside geofence
        cot_outside = b"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-2" type="b-a-o-can">
            <point lat="50.0" lon="-100.0" />
            <detail><contact callsign="OutsideUser"/></detail>
        </event>"""

        await handler.handle_cot_message(cot_outside, tak_server_id=1)
        # Should not send to IRC (filtered by geofence)
        assert not handler._writer.write.called

    @pytest.mark.asyncio
    async def test_end_to_end_with_uid_filter(self):
        """Test complete flow with UID filtering"""
        config = self.base_config.copy()
        config["uid_filter"] = "^ANDROID-.*"
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}: {remarks}",
                "enabled": True,
            }
        ]

        handler = IRCHandler(config)
        handler._connected = True
        handler._writer = MagicMock()
        handler._writer.is_closing.return_value = False
        handler._writer.drain = AsyncMock()

        # Matching UID
        cot_android = b"""<?xml version="1.0"?>
        <event version="2.0" uid="ANDROID-123" type="b-t-f">
            <point lat="40.7" lon="-74.0" />
            <detail>
                <contact callsign="AndroidUser"/>
                <remarks>Android message</remarks>
            </detail>
        </event>"""

        await handler.handle_cot_message(cot_android, tak_server_id=1)
        assert handler._writer.write.called

        # Reset mock
        handler._writer.reset_mock()

        # Non-matching UID
        cot_ios = b"""<?xml version="1.0"?>
        <event version="2.0" uid="IOS-456" type="b-t-f">
            <point lat="40.7" lon="-74.0" />
            <detail>
                <contact callsign="iOSUser"/>
                <remarks>iOS message</remarks>
            </detail>
        </event>"""

        await handler.handle_cot_message(cot_ios, tak_server_id=1)
        # Should not send to IRC (filtered by UID)
        assert not handler._writer.write.called

    @pytest.mark.asyncio
    async def test_end_to_end_multiple_rules(self):
        """Test complete flow with multiple message rules"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}: {remarks}",
                "enabled": True,
            },
            {
                "id": "rule-2",
                "cot_type_pattern": "b-a-*",
                "format_template": "[ALERT] {callsign} at {mgrs}",
                "enabled": True,
            },
            {
                "id": "rule-3",
                "cot_type_pattern": "a-f-*",
                "format_template": "[FRIENDLY] {callsign} - Battery: {battery}%",
                "enabled": True,
            },
        ]

        handler = IRCHandler(config)
        handler._connected = True
        handler._writer = MagicMock()
        handler._writer.is_closing.return_value = False
        handler._writer.drain = AsyncMock()

        # Test chat message (rule 1)
        cot_chat = b"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-1" type="b-t-f">
            <point lat="40.7" lon="-74.0" />
            <detail>
                <contact callsign="ChatUser"/>
                <remarks>Hello!</remarks>
            </detail>
        </event>"""

        await handler.handle_cot_message(cot_chat, tak_server_id=1)
        sent_data = handler._writer.write.call_args[0][0].decode('utf-8')
        assert "[CHAT] ChatUser: Hello!" in sent_data

        # Reset mock
        handler._writer.reset_mock()

        # Test alert message (rule 2)
        cot_alert = b"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-2" type="b-a-o-can">
            <point lat="40.7128" lon="-74.0060" />
            <detail><contact callsign="AlertUser"/></detail>
        </event>"""

        await handler.handle_cot_message(cot_alert, tak_server_id=1)
        sent_data = handler._writer.write.call_args[0][0].decode('utf-8')
        assert "[ALERT] AlertUser at" in sent_data  # MGRS will vary

        # Reset mock
        handler._writer.reset_mock()

        # Test friendly position (rule 3)
        cot_friendly = b"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-3" type="a-f-G-E-V">
            <point lat="40.7" lon="-74.0" />
            <detail>
                <contact callsign="FriendlyUser"/>
                <status battery="85"/>
            </detail>
        </event>"""

        await handler.handle_cot_message(cot_friendly, tak_server_id=1)
        sent_data = handler._writer.write.call_args[0][0].decode('utf-8')
        assert "[FRIENDLY] FriendlyUser - Battery: 85%" in sent_data

    @pytest.mark.asyncio
    async def test_end_to_end_extended_template_variables(self):
        """Test complete flow with extended template variables"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "a-f-*",
                "format_template": "[{group_name}] {callsign} ({group_role}) - Device: {device}, Battery: {battery}%, Speed: {speed}",
                "enabled": True,
            }
        ]

        handler = IRCHandler(config)
        handler._connected = True
        handler._writer = MagicMock()
        handler._writer.is_closing.return_value = False
        handler._writer.drain = AsyncMock()

        # Complex CoT with all extended fields
        cot_xml = b"""<?xml version="1.0"?>
        <event version="2.0" uid="ANDROID-abc123" type="a-f-G-U-C" time="2025-12-17T15:10:13Z" start="2025-12-17T15:10:12Z" stale="2025-12-17T15:16:27Z">
            <point lat="40.7128" lon="-74.0060" hae="10.0" ce="9999999.0" le="9999999.0"/>
            <detail>
                <__group name="Blue Team" role="Team Leader"/>
                <status battery="75"/>
                <takv device="SAMSUNG SM-G990E" platform="ATAK-CIV" os="36" version="5.4.0"/>
                <track speed="15.5" course="180.0"/>
                <contact xmppUsername="user@xmpp.example.com" callsign="Alpha1"/>
            </detail>
        </event>"""

        await handler.handle_cot_message(cot_xml, tak_server_id=1)
        sent_data = handler._writer.write.call_args[0][0].decode('utf-8')
        assert "[Blue Team] Alpha1 (Team Leader) - Device: SAMSUNG SM-G990E, Battery: 75%, Speed: 15.5" in sent_data

    @pytest.mark.asyncio
    async def test_end_to_end_deduplication(self):
        """Test that duplicate messages within TTL are filtered"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}: {remarks}",
                "enabled": True,
            }
        ]

        handler = IRCHandler(config)
        handler._connected = True
        handler._writer = MagicMock()
        handler._writer.is_closing.return_value = False
        handler._writer.drain = AsyncMock()

        cot_xml = b"""<?xml version="1.0"?>
        <event version="2.0" uid="ANDROID-123" type="b-t-f">
            <point lat="40.7" lon="-74.0" />
            <detail>
                <contact callsign="TestUser"/>
                <remarks>Duplicate test</remarks>
            </detail>
        </event>"""

        # First message should go through
        await handler.handle_cot_message(cot_xml, tak_server_id=1)
        assert handler._writer.write.call_count == 1

        # Second identical message should be deduplicated
        await handler.handle_cot_message(cot_xml, tak_server_id=1)
        assert handler._writer.write.call_count == 1  # Still 1, not 2

    @pytest.mark.asyncio
    async def test_end_to_end_message_splitting(self):
        """Test that long messages are split correctly"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}: {remarks}",
                "enabled": True,
            }
        ]

        handler = IRCHandler(config)
        handler._connected = True
        handler._writer = MagicMock()
        handler._writer.is_closing.return_value = False
        handler._writer.drain = AsyncMock()

        # Long message that should be split
        long_remarks = "A" * 500  # Exceeds 400 char limit
        cot_xml = f"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-1" type="b-t-f">
            <point lat="40.7" lon="-74.0" />
            <detail>
                <contact callsign="TestUser"/>
                <remarks>{long_remarks}</remarks>
            </detail>
        </event>""".encode('utf-8')

        await handler.handle_cot_message(cot_xml, tak_server_id=1)

        # Should have sent multiple chunks
        assert handler._writer.write.call_count > 1

    @pytest.mark.asyncio
    async def test_end_to_end_no_matching_rule(self):
        """Test that messages not matching any rule are filtered"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}",
                "enabled": True,
            }
        ]

        handler = IRCHandler(config)
        handler._connected = True
        handler._writer = MagicMock()
        handler._writer.is_closing.return_value = False
        handler._writer.drain = AsyncMock()

        # Message with non-matching type
        cot_xml = b"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-1" type="x-unknown-type">
            <point lat="40.7" lon="-74.0" />
            <detail><contact callsign="TestUser"/></detail>
        </event>"""

        await handler.handle_cot_message(cot_xml, tak_server_id=1)

        # Should not send to IRC
        assert not handler._writer.write.called

    @pytest.mark.asyncio
    async def test_end_to_end_connection_required(self):
        """Test that messages are not sent if not connected"""
        config = self.base_config.copy()
        config["message_rules"] = [
            {
                "id": "rule-1",
                "cot_type_pattern": "b-t-f",
                "format_template": "[CHAT] {callsign}",
                "enabled": True,
            }
        ]

        handler = IRCHandler(config)
        handler._connected = False  # Not connected

        cot_xml = b"""<?xml version="1.0"?>
        <event version="2.0" uid="TEST-1" type="b-t-f">
            <point lat="40.7" lon="-74.0" />
            <detail><contact callsign="TestUser"/></detail>
        </event>"""

        # Mock _ensure_connected to fail
        with patch.object(handler, '_ensure_connected', return_value=False):
            await handler.handle_cot_message(cot_xml, tak_server_id=1)

        # Should not attempt to send (no writer should be accessed)
        assert handler._writer is None

    @pytest.mark.asyncio
    async def test_config_round_trip(self):
        """Test that config can be saved and loaded correctly"""
        config = {
            "server": "irc.example.com",
            "port": 6697,
            "use_ssl": "true",
            "nickname": "TrakBot",
            "channel": "#tactical",
            "password": "secret123",
            "uid_filter": "^ANDROID-.*",
            "global_geofence_enabled": "true",
            "global_geofence_bounds": {
                "north": 40.8,
                "south": 40.6,
                "east": -73.9,
                "west": -74.1
            },
            "message_rules": [
                {
                    "id": "rule-1",
                    "cot_type_pattern": "b-t-f",
                    "format_template": "[CHAT] {callsign}: {remarks}",
                    "enabled": True,
                },
                {
                    "id": "rule-2",
                    "cot_type_pattern": "b-a-*",
                    "format_template": "[ALERT] {callsign} at {lat},{lon}",
                    "enabled": True,
                    "uid_filter": "^ANDROID-Team1.*",
                },
            ]
        }

        # Create handler with config
        handler = IRCHandler(config)

        # Verify config is accessible
        retrieved_config = handler.get_decrypted_config()

        assert retrieved_config["server"] == "irc.example.com"
        assert retrieved_config["port"] == 6697
        assert retrieved_config["use_ssl"] == "true"
        assert retrieved_config["global_geofence_enabled"] == "true"
        assert retrieved_config["global_geofence_bounds"]["north"] == 40.8
        assert len(retrieved_config["message_rules"]) == 2
        assert retrieved_config["message_rules"][0]["cot_type_pattern"] == "b-t-f"
        assert retrieved_config["message_rules"][1]["uid_filter"] == "^ANDROID-Team1.*"
