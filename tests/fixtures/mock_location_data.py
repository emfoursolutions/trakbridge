"""
ABOUTME: Test fixtures for generating mock GPS location data for parallel processing tests
ABOUTME: Provides realistic and edge-case GPS data for comprehensive testing scenarios
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List
import random
import uuid


def generate_mock_gps_points(count: int) -> List[Dict]:
    """
    Generate realistic GPS point data for testing parallel processing

    Args:
        count: Number of GPS points to generate

    Returns:
        List of GPS point dictionaries matching expected format
    """
    points = []
    base_time = datetime.now(timezone.utc)

    # Realistic coordinate ranges (global coverage)
    lat_range = (-85.0, 85.0)  # Avoid extreme polar regions
    lon_range = (-180.0, 180.0)

    for i in range(count):
        # Generate realistic coordinates
        lat = random.uniform(*lat_range)
        lon = random.uniform(*lon_range)

        # Vary timestamps slightly
        timestamp = base_time + timedelta(seconds=random.randint(-3600, 3600))

        point = {
            "name": f"TestDevice_{i:03d}",
            "lat": round(lat, 6),  # GPS precision
            "lon": round(lon, 6),
            "timestamp": timestamp,
            "uid": f"test-{uuid.uuid4()}",
            "description": f"Test GPS point {i+1} for parallel processing validation",
            "additional_data": {
                "source": "test_fixture",
                "point_index": i,
                "batch_id": f"test_batch_{i // 50}",  # Group into batches of 50
            },
        }

        # Add optional fields to some points for variety
        if i % 3 == 0:
            point["altitude"] = random.uniform(0, 5000)  # 0-5000m elevation

        if i % 4 == 0:
            point["accuracy"] = random.uniform(1, 100)  # 1-100m accuracy

        if i % 5 == 0:
            point["speed"] = random.uniform(0, 120)  # 0-120 km/h
            point["heading"] = random.uniform(0, 360)  # 0-360 degrees

        points.append(point)

    return points


def generate_invalid_gps_points() -> List[Dict]:
    """
    Generate problematic GPS data for error testing

    Returns:
        List of GPS points with various data issues
    """
    return [
        # Missing required fields
        {"name": "MissingCoords"},
        # Invalid coordinates
        {"name": "InvalidLat", "lat": 91.0, "lon": 0.0, "uid": "invalid-lat"},
        {"name": "InvalidLon", "lat": 0.0, "lon": 181.0, "uid": "invalid-lon"},
        # Bad data types
        {
            "name": "BadTypes",
            "lat": "not_a_number",
            "lon": "also_not_a_number",
            "uid": "bad-types",
        },
        # Missing UID
        {"name": "NoUID", "lat": 45.0, "lon": -75.0},
        # Invalid timestamp
        {
            "name": "BadTimestamp",
            "lat": 40.0,
            "lon": -74.0,
            "uid": "bad-time",
            "timestamp": "not_a_date",
        },
    ]


def generate_mixed_valid_invalid_points(
    valid_count: int = 50, invalid_count: int = 5
) -> List[Dict]:
    """
    Generate a mix of valid and invalid GPS points for error isolation testing

    Args:
        valid_count: Number of valid points to generate
        invalid_count: Number of invalid points to include

    Returns:
        List of mixed GPS points in random order
    """
    valid_points = generate_mock_gps_points(valid_count)
    invalid_points = generate_invalid_gps_points()[:invalid_count]

    # Mix them together randomly
    all_points = valid_points + invalid_points
    random.shuffle(all_points)

    return all_points


def generate_performance_test_datasets() -> Dict[str, List[Dict]]:
    """
    Generate standardized datasets for performance benchmarking

    Returns:
        Dictionary of named datasets for consistent performance testing
    """
    return {
        "tiny": generate_mock_gps_points(1),
        "small": generate_mock_gps_points(5),
        "medium": generate_mock_gps_points(50),
        "large": generate_mock_gps_points(300),
        "extra_large": generate_mock_gps_points(1000),
        "mixed_errors": generate_mixed_valid_invalid_points(100, 10),
    }


def get_expected_cot_count(dataset_name: str) -> int:
    """
    Get expected number of valid COT events for a given dataset

    Args:
        dataset_name: Name of the dataset from generate_performance_test_datasets

    Returns:
        Expected number of valid COT events
    """
    expected_counts = {
        "tiny": 1,
        "small": 5,
        "medium": 50,
        "large": 300,
        "extra_large": 1000,
        "mixed_errors": 100,  # Only valid points should produce COT events
    }

    return expected_counts.get(dataset_name, 0)
