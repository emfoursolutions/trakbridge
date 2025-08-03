#!/usr/bin/env python3
"""
ABOUTME: Plugin management CLI utility for TrakBridge administrators
ABOUTME: Allows secure addition and management of plugin modules without code changes

Plugin Management CLI for TrakBridge
Allows administrators to manage allowed plugin modules securely.

Usage:
    python scripts/manage_plugins.py list
    python scripts/manage_plugins.py add plugins.my_custom_plugin
    python scripts/manage_plugins.py reload
"""

import sys
import os
import argparse

# Add the project root to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins.plugin_manager import get_plugin_manager


def list_allowed_modules():
    """List all currently allowed plugin modules."""
    manager = get_plugin_manager()
    modules = manager.get_allowed_plugin_modules()
    
    print("Currently allowed plugin modules:")
    print("=" * 40)
    
    builtin_modules = manager.BUILTIN_PLUGIN_MODULES
    
    for module in modules:
        if module in builtin_modules:
            print(f"  {module} (built-in)")
        else:
            print(f"  {module} (configured)")
    
    print(f"\nTotal: {len(modules)} modules allowed")


def add_plugin_module(module_name):
    """Add a plugin module to the allowed list."""
    manager = get_plugin_manager()
    
    if manager.add_allowed_plugin_module(module_name):
        print(f"✓ Successfully added plugin module: {module_name}")
        print("Note: This change is temporary. Add it to config/settings/plugins.yaml for persistence.")
        return True
    else:
        print(f"✗ Failed to add plugin module: {module_name}")
        print("Module name must follow security requirements:")
        print("  - Must start with 'plugins.' or be 'plugins'")
        print("  - No path traversal or dangerous characters")
        print("  - Only alphanumeric, dots, and underscores allowed")
        return False


def reload_config():
    """Reload plugin configuration from files."""
    manager = get_plugin_manager()
    manager.reload_plugin_config()
    print("✓ Plugin configuration reloaded from config files")


def main():
    parser = argparse.ArgumentParser(
        description="TrakBridge Plugin Management CLI",
        epilog="Use this tool to securely manage plugin modules without modifying core code."
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List command
    subparsers.add_parser('list', help='List all allowed plugin modules')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add a plugin module to allowed list (temporary)')
    add_parser.add_argument('module_name', help='Module name to add (e.g., plugins.my_plugin)')
    
    # Reload command
    subparsers.add_parser('reload', help='Reload plugin configuration from files')
    
    args = parser.parse_args()
    
    if args.command == 'list':
        list_allowed_modules()
    elif args.command == 'add':
        add_plugin_module(args.module_name)
    elif args.command == 'reload':
        reload_config()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()