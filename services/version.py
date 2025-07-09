"""
File: services/version.py

Unified version module for TrakBridge application.

This module provides comprehensive version information access with fallback mechanisms,
development environment detection, and Git integration.

Author: {{AUTHOR}}
Created: {{CREATED_DATE}}
Last Modified: {{LASTMOD}}
Version: {{VERSION}}
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Global cache for version information
_version_cache: Optional[Dict[str, Any]] = None


class VersionInfo:
    """Comprehensive version information manager."""

    def __init__(self):
        self._base_version = None
        self._git_info = None
        self._environment_info = None
        self._developer_info = None
        self._is_development = None

    def _get_base_version(self) -> Dict[str, Any]:
        """Get base version information using fallback chain."""
        if self._base_version is not None:
            return self._base_version

        # Try different sources in order of preference
        version_sources = [
            self._get_version_from_scm,
            self._get_version_from_git_tag,
            self._get_version_from_environment,
            self._get_fallback_version
        ]

        for source_func in version_sources:
            try:
                version_info = source_func()
                if version_info:
                    logger.debug(f"Version loaded from {version_info['source']}: {version_info['version']}")
                    self._base_version = version_info
                    return self._base_version
            except Exception as e:
                logger.debug(f"Version source {source_func.__name__} failed: {e}")
                continue

        # Fallback should always work
        self._base_version = self._get_fallback_version()
        return self._base_version

    @staticmethod
    def _get_version_from_scm() -> Optional[Dict[str, Any]]:
        """Attempt to get version from setuptools-scm generated file."""
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

    def _get_version_from_git_tag(self) -> Optional[Dict[str, Any]]:
        """Attempt to get version from Git tags."""
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--abbrev=0"],
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                git_version = result.stdout.strip()
                if git_version.startswith('v'):
                    git_version = git_version[1:]

                return {
                    "version": git_version,
                    "version_tuple": self._parse_version_tuple(git_version),
                    "source": "git-tag"
                }
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            logger.debug("Git tag version detection failed")

        return None

    def _get_version_from_environment(self) -> Optional[Dict[str, Any]]:
        """Attempt to get version from environment variables."""
        env_version = os.getenv("TRAKBRIDGE_VERSION")
        if env_version:
            return {
                "version": env_version,
                "version_tuple": self._parse_version_tuple(env_version),
                "source": "environment"
            }
        return None

    def _get_fallback_version(self) -> Dict[str, Any]:
        """Get fallback version information."""
        fallback_version = "0.0.0.dev0"
        return {
            "version": fallback_version,
            "version_tuple": self._parse_version_tuple(fallback_version),
            "source": "fallback"
        }

    @staticmethod
    def _parse_version_tuple(version_string: str) -> Tuple:
        """Parse version string into tuple."""
        try:
            # Remove build metadata and pre-release info for tuple conversion
            clean_version = version_string.split('+')[0].split('-')[0]
            parts = clean_version.split('.')
            return tuple(int(part) for part in parts if part.isdigit())
        except (ValueError, AttributeError):
            return 0, 0, 0

    def _get_git_info(self) -> Dict[str, Any]:
        """Get comprehensive Git information."""
        if self._git_info is not None:
            return self._git_info

        git_info = {
            'available': False,
            'branch': None,
            'commit': None,
            'commit_short': None,
            'commit_date': None,
            'tag': None,
            'distance_from_tag': None,
            'is_dirty': False,
            'untracked_files': [],
            'modified_files': [],
            'staged_files': []
        }

        try:
            # Check if we're in a git repository
            result = subprocess.run(
                ['git', 'rev-parse', '--is-inside-work-tree'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                self._git_info = git_info
                return git_info

            git_info['available'] = True

            # Get all Git information in batch to minimize subprocess calls
            git_commands = {
                'branch': ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                'commit': ['git', 'rev-parse', 'HEAD'],
                'commit_date': ['git', 'log', '-1', '--format=%ci'],
                'status': ['git', 'status', '--porcelain']
            }

            # Execute Git commands
            for key, cmd in git_commands.items():
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        output = result.stdout.strip()

                        if key == 'branch':
                            git_info['branch'] = output
                        elif key == 'commit':
                            git_info['commit'] = output
                            git_info['commit_short'] = output[:8]
                        elif key == 'commit_date':
                            git_info['commit_date'] = output
                        elif key == 'status':
                            self._parse_git_status(output, git_info)

                except Exception as e:
                    logger.debug(f"Failed to get git {key}: {e}")

            # Get tag information
            try:
                # Check for exact tag match
                result = subprocess.run(
                    ['git', 'describe', '--tags', '--exact-match'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    git_info['tag'] = result.stdout.strip()
                else:
                    # Get distance from last tag
                    result = subprocess.run(
                        ['git', 'describe', '--tags', '--abbrev=0'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        last_tag = result.stdout.strip()
                        result = subprocess.run(
                            ['git', 'rev-list', f'{last_tag}..HEAD', '--count'],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0:
                            git_info['distance_from_tag'] = int(result.stdout.strip())
            except Exception as e:
                logger.debug(f"Failed to get tag info: {e}")

        except Exception as e:
            logger.debug(f"Git information gathering failed: {e}")

        self._git_info = git_info
        return git_info

    @staticmethod
    def _parse_git_status(status_output: str, git_info: Dict[str, Any]):
        """Parse git status output."""
        if not status_output:
            return

        git_info['is_dirty'] = True
        status_lines = status_output.split('\n')

        for line in status_lines:
            if line.strip():
                status_code = line[:2]
                filename = line[3:].strip()

                if status_code[0] in 'AMDRC':
                    git_info['staged_files'].append(filename)
                if status_code[1] in 'MD':
                    git_info['modified_files'].append(filename)
                if status_code == '??':
                    git_info['untracked_files'].append(filename)

    def _get_environment_info(self) -> Dict[str, Any]:
        """Get development environment information."""
        if self._environment_info is not None:
            return self._environment_info

        self._environment_info = {
            'python_executable': sys.executable,
            'python_version': sys.version,
            'python_version_info': sys.version_info,
            'platform': sys.platform,
            'working_directory': str(Path.cwd()),
            'script_directory': str(Path(__file__).parent),
            'user': os.environ.get('USER') or os.environ.get('USERNAME', 'unknown'),
            'hostname': os.environ.get('HOSTNAME') or os.environ.get('COMPUTERNAME', 'unknown'),
            'virtual_env': os.environ.get('VIRTUAL_ENV'),
            'flask_env': os.environ.get('FLASK_ENV', 'development'),
            'debug_mode': os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
        }

        return self._environment_info

    def _get_developer_info(self) -> Dict[str, Any]:
        """Get developer-specific information."""
        if self._developer_info is not None:
            return self._developer_info

        dev_info = {
            'name': 'unknown',
            'email': 'unknown'
        }

        try:
            # Get git user info
            for key, config_key in [('name', 'user.name'), ('email', 'user.email')]:
                result = subprocess.run(
                    ['git', 'config', config_key],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    dev_info[key] = result.stdout.strip()
        except Exception as e:
            logger.debug(f"Failed to get developer info: {e}")

        self._developer_info = dev_info
        return dev_info

    def is_development_build(self) -> bool:
        """Check if this is a development build."""
        if self._is_development is not None:
            return self._is_development

        git_info = self._get_git_info()
        base_version = self._get_base_version()
        env_info = self._get_environment_info()

        self._is_development = (
            git_info['is_dirty'] or
            (git_info['branch'] and git_info['branch'] not in ['main', 'master']) or
            'dev' in base_version['version'].lower() or
            env_info['debug_mode'] or
            base_version['source'] in ['fallback', 'git-tag']
        )

        return self._is_development

    def get_version(self) -> str:
        """Get the current version string."""
        return self._get_base_version()["version"]

    def get_version_tuple(self) -> Tuple:
        """Get the current version as a tuple."""
        return self._get_base_version()["version_tuple"]

    def get_development_version(self) -> str:
        """Get development-formatted version string."""
        base_version = self._get_base_version()
        version = base_version['version']

        if not self.is_development_build():
            return version

        git_info = self._get_git_info()

        # Add branch information if available and not main/master
        if git_info['available'] and git_info['branch']:
            branch = git_info['branch']
            if branch not in ['main', 'master']:
                version += f"-{branch}"

        # Add commit information
        if git_info['commit_short']:
            version += f"+{git_info['commit_short']}"

        # Add dirty flag
        if git_info['is_dirty']:
            version += ".dirty"

        # Add distance from tag if available
        if git_info['distance_from_tag'] and git_info['distance_from_tag'] > 0:
            version += f".dev{git_info['distance_from_tag']}"

        return version

    def get_version_info(self) -> Dict[str, Any]:
        """Get detailed version information."""
        base_version = self._get_base_version()

        return {
            **base_version,
            "development_version": self.get_development_version(),
            "is_development": self.is_development_build(),
            "git": self._get_git_info(),
            "environment": self._get_environment_info(),
            "developer": self._get_developer_info(),
            "timestamp": datetime.now().isoformat()
        }

    def format_version(self,
                      include_git: bool = True,
                      include_env: bool = False,
                      include_build_info: bool = False) -> str:
        """Format version information for display."""
        version = self.get_development_version() if self.is_development_build() else self.get_version()
        parts = [f"TrakBridge {version}"]

        if include_git and self._get_git_info()['available']:
            git_info = self._get_git_info()
            git_parts = []

            if git_info['branch']:
                git_parts.append(f"branch: {git_info['branch']}")
            if git_info['commit_short']:
                git_parts.append(f"commit: {git_info['commit_short']}")
            if git_info['is_dirty']:
                git_parts.append("dirty")

            if git_parts:
                parts.append(f"({', '.join(git_parts)})")

        if include_env:
            env_info = self._get_environment_info()
            env_parts = []

            if env_info['virtual_env']:
                venv_name = Path(env_info['virtual_env']).name
                env_parts.append(f"venv: {venv_name}")
            env_parts.append(f"python: {sys.version_info.major}.{sys.version_info.minor}")

            if env_parts:
                parts.append(f"[{', '.join(env_parts)}]")

        if include_build_info:
            base_version = self._get_base_version()
            parts.append(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
            if base_version['source'] != 'setuptools-scm':
                parts.append(f"({base_version['source']})")

        return " ".join(parts)


# Global instance
_version_instance: Optional[VersionInfo] = None


def _get_version_instance() -> VersionInfo:
    """Get the global version instance."""
    global _version_instance
    if _version_instance is None:
        _version_instance = VersionInfo()
    return _version_instance


# Public API functions
def get_version() -> str:
    """Get the current version string."""
    return _get_version_instance().get_version()


def get_version_tuple() -> Tuple:
    """Get the current version as a tuple."""
    return _get_version_instance().get_version_tuple()


def get_development_version() -> str:
    """Get development version string."""
    return _get_version_instance().get_development_version()


def get_version_info() -> Dict[str, Any]:
    """Get detailed version information."""
    return _get_version_instance().get_version_info()


def format_version(include_git: bool = True,
                  include_env: bool = False,
                  include_build_info: bool = False) -> str:
    """Format version information for display."""
    return _get_version_instance().format_version(include_git, include_env, include_build_info)


def is_development_build() -> bool:
    """Check if this is a development build."""
    return _get_version_instance().is_development_build()


def is_release_version() -> bool:
    """Check if this is a release version."""
    return not is_development_build()


# Backward compatibility aliases
def get_build_info() -> Dict[str, Any]:
    """Get build information (alias for get_version_info)."""
    return get_version_info()


def get_full_development_info() -> Dict[str, Any]:
    """Get full development information (alias for get_version_info)."""
    return get_version_info()


def format_development_version(include_git: bool = True, include_env: bool = False) -> str:
    """Format development version for display (alias for format_version)."""
    return format_version(include_git, include_env)


# Module-level convenience variables
__version__ = get_version()
__version_info__ = get_version_info()


# Export main functions
__all__ = [
    "get_version",
    "get_version_tuple",
    "get_development_version",
    "get_version_info",
    "format_version",
    "is_development_build",
    "is_release_version",
    "get_build_info",
    "get_full_development_info",
    "format_development_version",
    "__version__",
    "__version_info__"
]


if __name__ == "__main__":
    # CLI usage for testing
    import json

    version_info = _get_version_instance()

    print("TrakBridge Version Information")
    print("=" * 40)
    print(f"Version: {version_info.get_version()}")
    print(f"Development Version: {version_info.get_development_version()}")
    print(f"Formatted: {version_info.format_version(include_git=True, include_env=True, include_build_info=True)}")
    print(f"Development Build: {version_info.is_development_build()}")
    print(f"Release Build: {is_release_version()}")

    print("\nDetailed Information:")
    print(json.dumps(version_info.get_version_info(), indent=2, default=str))
