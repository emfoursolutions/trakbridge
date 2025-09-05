"""
File: services/cli/version_commands.py

Flask CLI commands for version management in TrakBridge application.

This module provides CLI commands for displaying, validating, and managing
version information in development and production environments.

Author: Emfour Solutions
Created: 18-Jul-2025
Last Modified: {{LASTMOD}}
"""

import json
import sys

import click
from flask import current_app
from flask.cli import with_appcontext

# Import unified version module
from services.version import _get_version_instance, get_development_version, get_version


@click.group()
def version():
    """Version management commands."""
    pass


@version.command()
@click.option("--detailed", "-d", is_flag=True, help="Show detailed version information")
@click.option("--json", "-j", is_flag=True, help="Output in JSON format")
@click.option("--dev", is_flag=True, help="Show development version format")
@click.option("--git", is_flag=True, help="Include Git information")
@click.option("--env", is_flag=True, help="Include environment information")
@with_appcontext
def show(detailed, json, dev, git, env):
    """Display current version information."""

    version_instance = _get_version_instance()

    if json:
        if detailed:
            data = version_instance.get_version_info()
        else:
            data = {
                "version": version_instance.get_version(),
                "development_version": version_instance.get_development_version(),
                "is_development": version_instance.is_development_build(),
                "type": ("development" if version_instance.is_development_build() else "release"),
            }

        click.echo(json.dumps(data, indent=2, default=str))
        return

    # Text output
    click.echo(click.style("TrakBridge Version Information", fg="blue", bold=True))
    click.echo("=" * 40)

    # Show appropriate version based on flags
    if dev or version_instance.is_development_build():
        version_str = version_instance.get_development_version()
        version_label = "Development Version"
    else:
        version_str = version_instance.get_version()
        version_label = "Version"

    version_type = "Development" if version_instance.is_development_build() else "Release"

    click.echo(f"{version_label}: {click.style(version_str, fg='green', bold=True)}")
    click.echo(f"Type: {click.style(version_type, fg='yellow')}")

    # Show formatted version
    if git or env or detailed:
        formatted = version_instance.format_version(
            include_git=git or detailed,
            include_env=env or detailed,
            include_build_info=detailed,
        )
        click.echo(f"Formatted: {formatted}")

    if detailed:
        info = version_instance.get_version_info()

        click.echo(f"\nSource: {info.get('source', 'unknown')}")
        click.echo(f"Python: {info['environment']['python_version'].split()[0]}")
        click.echo(f"Platform: {info['environment']['platform']}")

        # Git information
        git_info = info.get("git", {})
        if git_info.get("available"):
            click.echo("\nGit Information:")
            if git_info.get("branch"):
                click.echo(f"  Branch: {git_info['branch']}")
            if git_info.get("commit_short"):
                click.echo(f"  Commit: {git_info['commit_short']}")
            if git_info.get("tag"):
                click.echo(f"  Tag: {git_info['tag']}")
            if git_info.get("is_dirty"):
                click.echo(f"  Status: {click.style('Dirty', fg='red')}")
                if git_info.get("modified_files"):
                    click.echo(f"  Modified: {len(git_info['modified_files'])} files")
                if git_info.get("staged_files"):
                    click.echo(f"  Staged: {len(git_info['staged_files'])} files")
                if git_info.get("untracked_files"):
                    click.echo(f"  Untracked: {len(git_info['untracked_files'])} files")

        # Environment information
        env_info = info.get("environment", {})
        if env_info.get("virtual_env"):
            venv_name = env_info["virtual_env"].split("/")[-1]
            click.echo("\nEnvironment:")
            click.echo(f"  Virtual Env: {venv_name}")
            click.echo(f"  Debug Mode: {'Yes' if env_info.get('debug_mode') else 'No'}")

        # Developer information
        dev_info = info.get("developer", {})
        if dev_info.get("name") != "unknown":
            click.echo("\nDeveloper:")
            click.echo(f"  Name: {dev_info['name']}")
            click.echo(f"  Email: {dev_info['email']}")

    # Show Flask app context if available
    if current_app:
        click.echo(f"\nFlask App: {current_app.name}")
        click.echo(f"Debug Mode: {'Yes' if current_app.debug else 'No'}")


@version.command()
@with_appcontext
def validate():
    """Validate version consistency and Git repository state."""

    click.echo(click.style("Version Validation", fg="blue", bold=True))
    click.echo("=" * 30)

    issues = []
    warnings = []

    version_instance = _get_version_instance()
    version_info = version_instance.get_version_info()

    # Check version source
    source = version_info.get("source", "unknown")

    if source == "fallback":
        issues.append("Using fallback version - no Git tags or version file found")
    elif source == "git-tag":
        warnings.append("Using Git tag version directly - consider using setuptools-scm")
    elif source == "environment":
        warnings.append("Using environment variable version")

    # Check if in development
    if version_instance.is_development_build():
        dev_indicators = []
        version_str = version_instance.get_development_version()

        if "dev" in version_str.lower():
            dev_indicators.append("'dev' in version string")
        if "dirty" in version_str.lower():
            dev_indicators.append("uncommitted changes detected")
        if source == "fallback":
            dev_indicators.append("fallback version in use")

        git_info = version_info.get("git", {})
        if git_info.get("branch") and git_info["branch"] not in ["main", "master"]:
            dev_indicators.append(f"non-main branch: {git_info['branch']}")

        if dev_indicators:
            warnings.append(f"Development build detected: {', '.join(dev_indicators)}")

    # Check Git repository state
    git_info = version_info.get("git", {})
    if not git_info.get("available"):
        issues.append("Not in a Git repository or Git not available")
    else:
        # Check for uncommitted changes
        if git_info.get("is_dirty"):
            file_counts = []
            if git_info.get("modified_files"):
                file_counts.append(f"{len(git_info['modified_files'])} modified")
            if git_info.get("staged_files"):
                file_counts.append(f"{len(git_info['staged_files'])} staged")
            if git_info.get("untracked_files"):
                file_counts.append(f"{len(git_info['untracked_files'])} untracked")

            warnings.append(f"Uncommitted changes: {', '.join(file_counts)}")

        # Check for tags
        if not git_info.get("tag") and git_info.get("distance_from_tag") is None:
            warnings.append("No Git tags found - consider creating initial tag")

    # Check environment consistency
    env_info = version_info.get("environment", {})
    if current_app and current_app.debug != env_info.get("debug_mode"):
        warnings.append("Flask debug mode doesn't match environment debug setting")

    # Report results
    if not issues and not warnings:
        click.echo(click.style("✓ All validations passed", fg="green", bold=True))
    else:
        if issues:
            click.echo(click.style("Issues found:", fg="red", bold=True))
            for issue in issues:
                click.echo(f"  • {issue}")

        if warnings:
            click.echo(click.style("Warnings:", fg="yellow", bold=True))
            for warning in warnings:
                click.echo(f"  • {warning}")

    # Exit with appropriate code
    if issues:
        sys.exit(1)
    elif warnings:
        sys.exit(0)  # Warnings don't fail the command
    else:
        sys.exit(0)


@version.command()
@click.option("--force", "-f", is_flag=True, help="Force cache refresh")
@with_appcontext
def refresh(force):
    """Refresh cached version information."""

    if not force:
        click.confirm("This will refresh the cached version information. Continue?", abort=True)

    # Get the version instance and clear its cache
    version_instance = _get_version_instance()

    # Clear all cached data
    version_instance._base_version = None
    version_instance._git_info = None
    version_instance._environment_info = None
    version_instance._developer_info = None
    version_instance._is_development = None

    # Also clear the global cache
    import services.version

    services.version._version_instance = None

    click.echo("Refreshing version cache...")

    # Force reload by getting new instance
    new_version = get_version()
    dev_version = get_development_version()

    click.echo("Version cache refreshed:")
    click.echo(f"  Base: {click.style(new_version, fg='green')}")
    click.echo(f"  Development: {click.style(dev_version, fg='blue')}")


@version.command()
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "yaml", "env", "toml"]),
    default="json",
    help="Output format",
)
@click.option("--include-git", is_flag=True, help="Include Git information")
@click.option("--include-env", is_flag=True, help="Include environment information")
@with_appcontext
def export(output, output_format, include_git, include_env):
    """Export version information to file."""

    version_instance = _get_version_instance()

    if include_git or include_env:
        version_data = version_instance.get_version_info()

        # Filter data based on flags
        if not include_git:
            version_data.pop("git", None)
        if not include_env:
            version_data.pop("environment", None)
    else:
        # Basic version data
        version_data = {
            "version": version_instance.get_version(),
            "development_version": version_instance.get_development_version(),
            "is_development": version_instance.is_development_build(),
            "source": version_instance._get_base_version()["source"],
            "timestamp": version_instance.get_version_info()["timestamp"],
        }

    if output_format == "json":
        content = json.dumps(version_data, indent=2, default=str)
    elif output_format == "yaml":
        try:
            import yaml

            content = yaml.dump(version_data, default_flow_style=False)
        except ImportError:
            click.echo("PyYAML not installed. Install with: pip install PyYAML")
            sys.exit(1)
    elif output_format == "toml":
        try:
            import tomli_w

            content = tomli_w.dumps(version_data)
        except ImportError:
            click.echo("tomli-w not installed. Install with: pip install tomli-w")
            sys.exit(1)
    elif output_format == "env":
        dev_version = version_data.get("development_version", version_data["version"])
        is_dev = str(version_data.get("is_development", False)).lower()
        version_source = version_data.get("source", "unknown")

        env_lines = [
            f"TRAKBRIDGE_VERSION={version_data['version']}",
            f"TRAKBRIDGE_DEVELOPMENT_VERSION={dev_version}",
            f"TRAKBRIDGE_IS_DEVELOPMENT={is_dev}",
            f"TRAKBRIDGE_VERSION_SOURCE={version_source}",
        ]

        if include_env and "environment" in version_data:
            env_info = version_data["environment"]
            env_lines.extend(
                [
                    f"TRAKBRIDGE_PYTHON_VERSION={env_info.get('python_version', '').split()[0]}",
                    f"TRAKBRIDGE_PLATFORM={env_info.get('platform', 'unknown')}",
                    f"TRAKBRIDGE_DEBUG_MODE={str(env_info.get('debug_mode', False)).lower()}",
                ]
            )

        if include_git and "git" in version_data:
            git_info = version_data["git"]
            if git_info.get("available"):
                env_lines.extend(
                    [
                        f"TRAKBRIDGE_GIT_BRANCH={git_info.get('branch', 'unknown')}",
                        f"TRAKBRIDGE_GIT_COMMIT={git_info.get('commit_short', 'unknown')}",
                        f"TRAKBRIDGE_GIT_DIRTY={str(git_info.get('is_dirty', False)).lower()}",
                    ]
                )

        content = "\n".join(env_lines)

    if output:
        with open(output, "w") as f:
            f.write(content)
        click.echo(f"Version information exported to {output}")
    else:
        click.echo(content)


@version.command()
@click.argument("version_string", required=False)
@click.option("--strict", is_flag=True, help="Use strict semantic versioning validation")
@with_appcontext
def check(version_string, strict):
    """Check if a version string is valid semantic version."""

    if not version_string:
        version_instance = _get_version_instance()
        version_string = version_instance.get_development_version()
        click.echo(f"Checking current development version: {version_string}")

    # Import regex for pattern matching
    import re

    if strict:
        # Strict semantic version regex pattern
        semver_pattern = (
            r"^(\d+)\.(\d+)\.(\d+)"
            r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
            r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
        )
    else:
        # Relaxed pattern that allows development versions
        semver_pattern = (
            r"^v?(\d+)\.(\d+)\.(\d+)(?:\.(\w+))?"
            r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
            r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
            r"(?:\.(dirty|dev\d+))?$"
        )

    match = re.match(semver_pattern, version_string)

    if match:
        groups = match.groups()
        major, minor, patch = groups[0], groups[1], groups[2]

        click.echo(click.style("✓ Valid version format", fg="green", bold=True))
        click.echo(f"  Major: {major}")
        click.echo(f"  Minor: {minor}")
        click.echo(f"  Patch: {patch}")

        if strict:
            prerelease, build = groups[3], groups[4]
            if prerelease:
                click.echo(f"  Pre-release: {prerelease}")
            if build:
                click.echo(f"  Build: {build}")
        else:
            # Handle relaxed pattern groups
            if len(groups) > 3 and groups[3]:
                click.echo(f"  Additional: {groups[3]}")

            # Check for development indicators
            if "dev" in version_string.lower():
                click.echo(f"  Type: {click.style('Development', fg='yellow')}")
            if "dirty" in version_string.lower():
                click.echo(f"  State: {click.style('Dirty', fg='red')}")
    else:
        click.echo(click.style("✗ Invalid version format", fg="red", bold=True))
        if strict:
            click.echo("Expected format: MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]")
        else:
            click.echo(
                "Expected format: MAJOR.MINOR.PATCH[.ADDITIONAL][-PRERELEASE][+BUILD][.dirty|.devN]"
            )
        sys.exit(1)


@version.command()
@with_appcontext
def debug():
    """Show detailed version resolution debug information."""

    click.echo(click.style("Version Resolution Debug", fg="blue", bold=True))
    click.echo("=" * 40)

    version_instance = _get_version_instance()

    # Test each version source
    sources = [
        ("setuptools-scm", version_instance._get_version_from_scm),
        ("git-tag", version_instance._get_version_from_git_tag),
        ("environment", version_instance._get_version_from_environment),
        ("fallback", version_instance._get_fallback_version),
    ]

    for name, func in sources:
        try:
            result = func()
            if result:
                status = click.style("✓ Available", fg="green")
                version = result.get("version", "unknown")
                source = result.get("source", name)
                click.echo(f"{name:15} {status} - {version} ({source})")
            else:
                status = click.style("✗ Not available", fg="red")
                click.echo(f"{name:15} {status}")
        except Exception as e:
            status = click.style("✗ Error", fg="red")
            click.echo(f"{name:15} {status} - {str(e)}")

    click.echo()

    # Show current resolution
    base_version = version_instance._get_base_version()

    # Extract styled values
    styled_base_version = click.style(base_version["version"], fg="green", bold=True)
    styled_dev_version = click.style(
        version_instance.get_development_version(), fg="blue", bold=True
    )
    styled_is_dev = click.style(str(version_instance.is_development_build()), fg="yellow")

    click.echo(f"Selected base version: {styled_base_version}")
    click.echo(f"Version source: {base_version['source']}")
    click.echo(f"Development version: {styled_dev_version}")
    click.echo(f"Is development build: {styled_is_dev}")

    # Show Git status
    git_info = version_instance._get_git_info()

    # Extract the git status styling
    git_status = "Available" if git_info["available"] else "Not available"
    git_color = "green" if git_info["available"] else "red"
    styled_git_status = click.style(git_status, fg=git_color)

    click.echo(f"\nGit repository: {styled_git_status}")

    if git_info["available"]:
        click.echo(f"  Branch: {git_info.get('branch', 'unknown')}")
        click.echo(f"  Commit: {git_info.get('commit_short', 'unknown')}")

        # Format dirty status with appropriate color
        is_dirty = git_info.get("is_dirty", False)
        dirty_color = "red" if is_dirty else "green"
        styled_dirty = click.style(str(is_dirty), fg=dirty_color)

        click.echo(f"  Dirty: {styled_dirty}")

        if git_info.get("distance_from_tag"):
            click.echo(f"  Distance from tag: {git_info['distance_from_tag']}")


@version.command()
@click.option("--git", is_flag=True, help="Include Git information")
@click.option("--env", is_flag=True, help="Include environment information")
@with_appcontext
def status(git, env):  # <-- FIXED: Added missing parameters
    """Show current version status summary."""

    version_instance = _get_version_instance()

    # Basic status
    click.echo(click.style("Version Status", fg="blue", bold=True))
    click.echo("=" * 20)

    is_dev = version_instance.is_development_build()
    status_color = "yellow" if is_dev else "green"
    status_text = "Development" if is_dev else "Release"

    click.echo(f"Status: {click.style(status_text, fg=status_color, bold=True)}")
    click.echo(f"Version: {version_instance.get_development_version()}")
    click.echo(f"Formatted: {version_instance.format_version(include_git=git, include_env=env)}")

    # Quick indicators
    if is_dev:
        git_info = version_instance._get_git_info()
        indicators = []

        if git_info.get("is_dirty"):
            indicators.append(click.style("dirty", fg="red"))
        if git_info.get("branch") and git_info["branch"] not in ["main", "master"]:
            indicators.append(click.style(f"branch:{git_info['branch']}", fg="yellow"))
        if git_info.get("distance_from_tag"):
            indicators.append(click.style(f"ahead:{git_info['distance_from_tag']}", fg="blue"))

        if indicators:
            click.echo(f"Indicators: {' '.join(indicators)}")


# Register the command group
def register_version_commands(app):
    """Register version commands with Flask app."""
    app.cli.add_command(version)


# For direct CLI usage
if __name__ == "__main__":
    version()
