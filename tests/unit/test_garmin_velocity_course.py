"""
ABOUTME: Unit tests for Garmin velocity and course extraction
ABOUTME: Tests parsing of velocity (km/h → m/s) and course (degrees) from KML
"""

import pytest
from plugins.garmin_plugin import GarminPlugin


class TestGarminVelocityParsing:
    """Test Garmin velocity string parsing"""

    def test_parse_velocity_kmh(self):
        """Test parsing velocity in km/h format"""
        # 32.6 km/h = 9.055... m/s
        result = GarminPlugin._parse_velocity("32.6 km/h")
        assert result is not None
        assert abs(result - 9.055555) < 0.001

    def test_parse_velocity_mph(self):
        """Test parsing velocity in mph format"""
        # 20 mph = 8.9408 m/s
        result = GarminPlugin._parse_velocity("20.0 mph")
        assert result is not None
        assert abs(result - 8.9408) < 0.001

    def test_parse_velocity_ms(self):
        """Test parsing velocity in m/s format"""
        result = GarminPlugin._parse_velocity("10.5 m/s")
        assert result is not None
        assert abs(result - 10.5) < 0.001

    def test_parse_velocity_kph_variant(self):
        """Test parsing velocity with kph abbreviation"""
        result = GarminPlugin._parse_velocity("50 kph")
        assert result is not None
        assert abs(result - 13.888888) < 0.001

    def test_parse_velocity_no_unit_defaults_kmh(self):
        """Test parsing velocity without unit defaults to km/h"""
        result = GarminPlugin._parse_velocity("36.0")
        assert result is not None
        assert abs(result - 10.0) < 0.001  # 36 km/h = 10 m/s

    def test_parse_velocity_zero(self):
        """Test parsing zero velocity"""
        result = GarminPlugin._parse_velocity("0.0 km/h")
        assert result is not None
        assert result == 0.0

    def test_parse_velocity_none(self):
        """Test parsing None velocity"""
        result = GarminPlugin._parse_velocity(None)
        assert result is None

    def test_parse_velocity_empty_string(self):
        """Test parsing empty velocity string"""
        result = GarminPlugin._parse_velocity("")
        assert result is None

    def test_parse_velocity_invalid_format(self):
        """Test parsing invalid velocity format"""
        result = GarminPlugin._parse_velocity("not a number")
        assert result is None

    def test_parse_velocity_garmin_format(self):
        """Test parsing actual Garmin KML format"""
        # From example: "32.6 km/h"
        result = GarminPlugin._parse_velocity("32.6 km/h")
        assert result is not None
        assert result > 9.0 and result < 9.1


class TestGarminCourseParsing:
    """Test Garmin course/heading string parsing"""

    def test_parse_course_with_true(self):
        """Test parsing course with 'True' suffix"""
        result = GarminPlugin._parse_course("315.00 ° True")
        assert result is not None
        assert result == 315.0

    def test_parse_course_simple_degrees(self):
        """Test parsing simple degree format"""
        result = GarminPlugin._parse_course("45.5°")
        assert result is not None
        assert result == 45.5

    def test_parse_course_with_degrees_word(self):
        """Test parsing course with 'degrees' word"""
        result = GarminPlugin._parse_course("180 degrees")
        assert result is not None
        assert result == 180.0

    def test_parse_course_zero(self):
        """Test parsing zero course (north)"""
        result = GarminPlugin._parse_course("0.0 ° True")
        assert result is not None
        assert result == 0.0

    def test_parse_course_360_normalizes_to_0(self):
        """Test 360 degrees normalizes to 0"""
        result = GarminPlugin._parse_course("360.0 ° True")
        assert result is not None
        assert result == 0.0

    def test_parse_course_over_360_normalizes(self):
        """Test course over 360 normalizes correctly"""
        result = GarminPlugin._parse_course("405.0°")
        assert result is not None
        assert result == 45.0  # 405 % 360 = 45

    def test_parse_course_decimal(self):
        """Test parsing course with decimal precision"""
        result = GarminPlugin._parse_course("123.456 ° True")
        assert result is not None
        assert abs(result - 123.456) < 0.001

    def test_parse_course_none(self):
        """Test parsing None course"""
        result = GarminPlugin._parse_course(None)
        assert result is None

    def test_parse_course_empty_string(self):
        """Test parsing empty course string"""
        result = GarminPlugin._parse_course("")
        assert result is None

    def test_parse_course_invalid_format(self):
        """Test parsing invalid course format"""
        result = GarminPlugin._parse_course("not a number")
        assert result is None

    def test_parse_course_garmin_format(self):
        """Test parsing actual Garmin KML format"""
        # From example: "315.00 ° True"
        result = GarminPlugin._parse_course("315.00 ° True")
        assert result is not None
        assert result == 315.0


class TestGarminLocationDictWithVelocityCourse:
    """Test location dict creation with velocity and course"""

    def test_location_dict_includes_speed_and_course(self):
        """Test that _create_location_dict adds speed and course fields"""
        plugin = GarminPlugin(
            config={
                "url": "https://share.garmin.com/test",
                "username": "test",
                "password": "test",
            }
        )

        placemark = {
            "name": "Test Device",
            "lat": 46.886493,
            "lon": 29.207861,
            "uid": "test-001",
            "description": "Test",
            "timestamp": None,
            "extended_data": {
                "Velocity": "32.6 km/h",
                "Course": "315.00 ° True",
                "IMEI": "300434038594510",
            },
        }

        location = plugin._create_location_dict(placemark)

        # Check that speed and course are present as top-level fields
        assert "speed" in location
        assert "course" in location
        assert location["speed"] is not None
        assert location["course"] is not None
        assert abs(location["speed"] - 9.055555) < 0.001
        assert location["course"] == 315.0

    def test_location_dict_without_velocity_course(self):
        """Test location dict when velocity/course not present"""
        plugin = GarminPlugin(
            config={
                "url": "https://share.garmin.com/test",
                "username": "test",
                "password": "test",
            }
        )

        placemark = {
            "name": "Test Device",
            "lat": 46.886493,
            "lon": 29.207861,
            "uid": "test-002",
            "description": "Test",
            "timestamp": None,
            "extended_data": {"IMEI": "300434038594510"},
        }

        location = plugin._create_location_dict(placemark)

        # Check that speed and course are NOT present when not in extended_data
        assert "speed" not in location
        assert "course" not in location

    def test_location_dict_with_invalid_velocity_course(self):
        """Test location dict handles invalid velocity/course gracefully"""
        plugin = GarminPlugin(
            config={
                "url": "https://share.garmin.com/test",
                "username": "test",
                "password": "test",
            }
        )

        placemark = {
            "name": "Test Device",
            "lat": 46.886493,
            "lon": 29.207861,
            "uid": "test-003",
            "description": "Test",
            "timestamp": None,
            "extended_data": {
                "Velocity": "invalid",
                "Course": "invalid",
                "IMEI": "300434038594510",
            },
        }

        location = plugin._create_location_dict(placemark)

        # Check that speed and course are NOT present when parsing fails
        assert "speed" not in location
        assert "course" not in location

    def test_location_dict_with_zero_velocity(self):
        """Test location dict with zero velocity (stationary device)"""
        plugin = GarminPlugin(
            config={
                "url": "https://share.garmin.com/test",
                "username": "test",
                "password": "test",
            }
        )

        placemark = {
            "name": "Test Device",
            "lat": 46.886493,
            "lon": 29.207861,
            "uid": "test-004",
            "description": "Test",
            "timestamp": None,
            "extended_data": {
                "Velocity": "0.0 km/h",
                "Course": "0.0 ° True",
                "IMEI": "300434038594510",
            },
        }

        location = plugin._create_location_dict(placemark)

        # Check that zero values are properly included
        assert "speed" in location
        assert "course" in location
        assert location["speed"] == 0.0
        assert location["course"] == 0.0
