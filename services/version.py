"""
File: services/version.py

Version module for TrakBridge application.

This module provides version information access with fallback mechanisms
for development environments and version display utilities.

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Version information storage
_version_info: Optional[Dict[str, Any]] = None


def _get_version_from_scm() -> Optional[Dict[str, Any]]:
    """
    Attempt to get version from setuptools-scm generated file.

    Returns:
        Dictionary with version info or None if not available
    """
    try:
        from _version import __version__, __version_tuple__
        return {
            "version": __version__,
            "version_tuple": __version_tuple__,
            "source": "setuptools-scm"
        }
    except ImportError:
        logger.debug("setuptools-scm version file not found")
        return None


def _get_version_from_git() -> Optional[Dict[str, Any]]:
    """
    Attempt to get version directly from Git (fallback).

    Returns:
        Dictionary with version info or None if not available
    """
    try:
        import subprocess

        # Get the current directory
        cwd = Path(__file__).parent

        # Try to get version from git describe
        result = subprocess.run(
            ["git", "describe", "--tags", "--dirty", "--always"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            git_version = result.stdout.strip()

            # Clean up the version string
            if git_version.startswith('v'):
                git_version = git_version[1:]

            return {
                "version": git_version,
                "version_tuple": _parse_version_tuple(git_version),
                "source": "git"
            }

    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        logger.debug("Git version detection failed")

    return None


def _get_version_from_environment() -> Optional[Dict[str, Any]]:
    """
    Attempt to get version from environment variables.

    Returns:
        Dictionary with version info or None if not available
    """
    env_version = os.getenv("trakbridge_VERSION")
    if env_version:
        return {
            "version": env_version,
            "version_tuple": _parse_version_tuple(env_version),
            "source": "environment"
        }
    return None


def _get_fallback_version() -> Dict[str, Any]:
    """
    Get fallback version information.

    Returns:
        Dictionary with fallback version info
    """
    fallback_version = "0.0.0.dev0"
    return {
        "version": fallback_version,
        "version_tuple": _parse_version_tuple(fallback_version),
        "source": "fallback"
    }


def _parse_version_tuple(version_string: str) -> Tuple:
    """
    Parse version string into tuple.

    Args:
        version_string: Version string to parse

    Returns:
        Tuple representation of version
    """
    try:
        # Simple parsing - remove common suffixes for tuple conversion
        clean_version = version_string.split('+')[0]  # Remove build metadata
        clean_version = clean_version.split('-')[0]  # Remove pre-release info

        parts = clean_version.split('.')
        return tuple(int(part) for part in parts if part.isdigit())
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _load_version_info() -> Dict[str, Any]:
    """
    Load version information using fallback chain.

    Returns:
        Dictionary with version information
    """
    global _version_info

    if _version_info is not None:
        return _version_info

    # Try different sources in order of preference
    version_sources = [
        _get_version_from_scm,
        _get_version_from_git,
        _get_version_from_environment,
        _get_fallback_version  # This always returns a value
    ]

    for source_func in version_sources:
        try:
            version_info = source_func()
            if version_info:
                logger.debug(f"Version loaded from {version_info['source']}: {version_info['version']}")
                _version_info = version_info
                return _version_info
        except Exception as e:
            logger.debug(f"Version source {source_func.__name__} failed: {e}")
            continue

    # This should never happen since fallback always returns a value
    _version_info = _get_fallback_version()
    return _version_info


def get_version() -> str:
    """
    Get the current version string.

    Returns:
        Version string (e.g., "1.0.0", "1.0.0.dev1")
    """
    return _load_version_info()["version"]


def get_version_tuple() -> Tuple:
    """
    Get the current version as a tuple.

    Returns:
        Version tuple (e.g., (1, 0, 0))
    """
    return _load_version_info()["version_tuple"]


def get_version_info() -> Dict[str, Any]:
    """
    Get detailed version information.

    Returns:
        Dictionary containing:
        - version: Version string
        - version_tuple: Version tuple
        - source: Where the version was loaded from
        - python_version: Python version info
        - platform: Platform information
    """
    version_info = _load_version_info().copy()

    # Add additional system information
    version_info.update({
        "python_version": sys.version,
        "python_version_info": sys.version_info,
        "platform": sys.platform,
        "executable": sys.executable
    })

    return version_info


def get_build_info() -> Dict[str, Any]:
    """
    Get build and runtime information.

    Returns:
        Dictionary with build information
    """
    info = get_version_info()

    # Add build-specific information
    build_info = {
        "version": info["version"],
        "version_source": info["source"],
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": sys.platform,
        "cwd": str(Path.cwd()),
        "module_path": str(Path(__file__).parent),
    }

    # Add Git information if available
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            build_info["git_commit"] = result.stdout.strip()[:8]
    except:
        pass

    return build_info


def format_version(include_build_info: bool = False) -> str:
    """
    Format version information for display.

    Args:
        include_build_info: Whether to include build information

    Returns:
        Formatted version string
    """
    version = get_version()

    if not include_build_info:
        return f"trakbridge v{version}"

    build_info = get_build_info()

    parts = [f"trakbridge v{version}"]

    if "git_commit" in build_info:
        parts.append(f"({build_info['git_commit']})")

    parts.append(f"Python {build_info['python_version']}")

    return " ".join(parts)


def is_development_version() -> bool:
    """
    Check if this is a development version.

    Returns:
        True if this is a development version
    """
    version = get_version()
    return any(marker in version.lower() for marker in ["dev", "dirty", "unknown"])


def is_release_version() -> bool:
    """
    Check if this is a release version.

    Returns:
        True if this is a release version
    """
    return not is_development_version()


# Module-level convenience variables
__version__ = get_version()
__version_info__ = get_version_info()

# Export main functions
__all__ = [
    "get_version",
    "get_version_tuple",
    "get_version_info",
    "get_build_info",
    "format_version",
    "is_development_version",
    "is_release_version",
    "__version__",
    "__version_info__"
]

if __name__ == "__main__":
    # CLI usage for testing
    import json

    print("TrakBridge Version Information")
    print("=" * 40)
    print(f"Version: {get_version()}")
    print(f"Formatted: {format_version(include_build_info=True)}")
    print(f"Development: {is_development_version()}")
    print(f"Release: {is_release_version()}")
    print("\nDetailed Information:")
    print(json.dumps(get_version_info(), indent=2, default=str))