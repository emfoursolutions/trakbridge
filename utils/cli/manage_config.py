#!/usr/bin/env python3
"""
ABOUTME: Configuration management CLI for TrakBridge
ABOUTME: Provides commands to install, validate, and manage configuration files
"""

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Any

import yaml

# Add the app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from config.base import ConfigLoader, BaseConfig


class ConfigManager:
    """Configuration management utility for TrakBridge."""
    
    def __init__(self, external_config_dir: str = None):
        self.external_config_dir = Path(external_config_dir or os.environ.get("TRAKBRIDGE_CONFIG_DIR", "./config"))
        self.bundled_config_dir = Path(__file__).parent.parent / "config" / "settings"
        
        # Ensure external config directory exists
        self.external_config_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = self._setup_logging()
        
    def _setup_logging(self) -> logging.Logger:
        """Setup logging for the config manager."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)
    
    def list_configs(self) -> Dict[str, Dict[str, Any]]:
        """List all configuration files and their status."""
        configs = {}
        
        # Find all YAML files in bundled config
        for bundled_file in self.bundled_config_dir.glob("*.yaml"):
            filename = bundled_file.name
            external_file = self.external_config_dir / filename
            
            configs[filename] = {
                "bundled_exists": True,
                "bundled_path": str(bundled_file),
                "external_exists": external_file.exists(),
                "external_path": str(external_file),
                "status": "external" if external_file.exists() else "bundled_only"
            }
            
            if external_file.exists():
                try:
                    # Check if files are different
                    with open(bundled_file, 'r') as f:
                        bundled_content = f.read()
                    with open(external_file, 'r') as f:
                        external_content = f.read()
                    
                    configs[filename]["files_differ"] = bundled_content != external_content
                except Exception as e:
                    configs[filename]["error"] = str(e)
        
        # Find external-only configs
        for external_file in self.external_config_dir.glob("*.yaml"):
            filename = external_file.name
            if filename not in configs:
                configs[filename] = {
                    "bundled_exists": False,
                    "bundled_path": None,
                    "external_exists": True,
                    "external_path": str(external_file),
                    "status": "external_only"
                }
        
        return configs
    
    def install_config(self, filename: str = None, update_mode: str = "preserve") -> bool:
        """
        Install configuration files to external directory.
        
        Args:
            filename: Specific file to install (None for all)
            update_mode: How to handle existing files (preserve, overwrite, merge)
            
        Returns:
            True if successful
        """
        if filename:
            files_to_process = [self.bundled_config_dir / filename]
        else:
            files_to_process = list(self.bundled_config_dir.glob("*.yaml"))
        
        success = True
        installed_count = 0
        updated_count = 0
        skipped_count = 0
        
        for bundled_file in files_to_process:
            if not bundled_file.exists():
                self.logger.error(f"Bundled config file not found: {bundled_file}")
                success = False
                continue
            
            external_file = self.external_config_dir / bundled_file.name
            
            try:
                if external_file.exists():
                    if update_mode == "preserve":
                        self.logger.info(f"Preserving existing config: {bundled_file.name}")
                        skipped_count += 1
                        continue
                    elif update_mode == "overwrite":
                        self.logger.info(f"Overwriting config: {bundled_file.name}")
                        shutil.copy2(bundled_file, external_file)
                        updated_count += 1
                    elif update_mode == "merge":
                        # For now, preserve existing (merge could be implemented later)
                        self.logger.info(f"Preserving existing config (merge not yet implemented): {bundled_file.name}")
                        skipped_count += 1
                        continue
                else:
                    self.logger.info(f"Installing new config: {bundled_file.name}")
                    shutil.copy2(bundled_file, external_file)
                    installed_count += 1
                    
            except Exception as e:
                self.logger.error(f"Failed to process {bundled_file.name}: {e}")
                success = False
        
        self.logger.info(f"Configuration installation complete:")
        self.logger.info(f"  Installed: {installed_count} files")
        self.logger.info(f"  Updated: {updated_count} files") 
        self.logger.info(f"  Preserved: {skipped_count} files")
        
        return success
    
    def validate_config(self, environment: str = "development") -> Dict[str, Any]:
        """
        Validate configuration files and report issues.
        
        Args:
            environment: Environment to validate for
            
        Returns:
            Validation results
        """
        results = {
            "environment": environment,
            "valid": True,
            "issues": [],
            "warnings": [],
            "config_sources": {}
        }
        
        try:
            # Test configuration loading
            config = BaseConfig(environment=environment)
            
            # Run built-in validation
            issues = config.validate_config()
            if issues:
                results["issues"].extend(issues)
                results["valid"] = False
            
            # Test each configuration file
            loader = ConfigLoader(environment=environment)
            
            config_files = [
                "app.yaml",
                "database.yaml", 
                "threading.yaml",
                "logging.yaml",
                "authentication.yaml"
            ]
            
            for filename in config_files:
                try:
                    config_data = loader.load_config_file(filename)
                    
                    # Determine source
                    external_path = loader.external_config_dir / filename
                    bundled_path = loader.bundled_config_dir / filename
                    
                    if external_path.exists():
                        source = f"external:{external_path}"
                    elif bundled_path.exists():
                        source = f"bundled:{bundled_path}"
                    else:
                        source = "missing"
                        results["issues"].append(f"Configuration file '{filename}' not found")
                        results["valid"] = False
                    
                    results["config_sources"][filename] = source
                    
                    # Basic YAML validation (already done by load_config_file)
                    if not config_data:
                        results["warnings"].append(f"Configuration file '{filename}' is empty")
                        
                except Exception as e:
                    results["issues"].append(f"Failed to load '{filename}': {e}")
                    results["valid"] = False
            
            # Test authentication configuration specifically
            try:
                auth_config = config.get_auth_config()
                if not auth_config:
                    results["warnings"].append("No authentication configuration found")
                else:
                    # Check for enabled providers
                    providers = auth_config.get("providers", {})
                    enabled_providers = [name for name, cfg in providers.items() if cfg.get("enabled", False)]
                    
                    if not enabled_providers:
                        results["issues"].append("No authentication providers are enabled")
                        results["valid"] = False
                    else:
                        results["warnings"].append(f"Enabled auth providers: {', '.join(enabled_providers)}")
                        
                    # Validate LDAP config if enabled
                    if providers.get("ldap", {}).get("enabled", False):
                        ldap_config = providers["ldap"]
                        required_ldap_fields = ["server", "bind_dn", "user_search_base"]
                        for field in required_ldap_fields:
                            if not ldap_config.get(field):
                                results["issues"].append(f"LDAP provider missing required field: {field}")
                                results["valid"] = False
                    
                    # Validate OIDC config if enabled  
                    if providers.get("oidc", {}).get("enabled", False):
                        oidc_config = providers["oidc"]
                        required_oidc_fields = ["issuer", "client_id", "client_secret"]
                        for field in required_oidc_fields:
                            if not oidc_config.get(field):
                                results["issues"].append(f"OIDC provider missing required field: {field}")
                                results["valid"] = False
                                
            except Exception as e:
                results["issues"].append(f"Authentication configuration validation failed: {e}")
                results["valid"] = False
                
        except Exception as e:
            results["issues"].append(f"Critical configuration error: {e}")
            results["valid"] = False
        
        return results
    
    def backup_config(self, backup_dir: str = None) -> str:
        """
        Create a backup of the external configuration directory.
        
        Args:
            backup_dir: Directory to store backup (default: ./config-backup-{timestamp})
            
        Returns:
            Path to backup directory
        """
        import datetime
        
        if not backup_dir:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = f"./config-backup-{timestamp}"
        
        backup_path = Path(backup_dir)
        
        if backup_path.exists():
            raise ValueError(f"Backup directory already exists: {backup_path}")
        
        shutil.copytree(self.external_config_dir, backup_path)
        self.logger.info(f"Configuration backed up to: {backup_path}")
        
        return str(backup_path)
    
    def restore_config(self, backup_dir: str) -> bool:
        """
        Restore configuration from a backup directory.
        
        Args:
            backup_dir: Path to backup directory
            
        Returns:
            True if successful
        """
        backup_path = Path(backup_dir)
        
        if not backup_path.exists():
            raise ValueError(f"Backup directory not found: {backup_path}")
        
        # Create a backup of current config before restoring
        current_backup = self.backup_config()
        self.logger.info(f"Current config backed up to: {current_backup}")
        
        try:
            # Remove current external config
            if self.external_config_dir.exists():
                shutil.rmtree(self.external_config_dir)
            
            # Restore from backup
            shutil.copytree(backup_path, self.external_config_dir)
            self.logger.info(f"Configuration restored from: {backup_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to restore configuration: {e}")
            return False


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="TrakBridge Configuration Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all configuration files
  python manage_config.py list
  
  # Install all default configurations 
  python manage_config.py install
  
  # Install specific configuration file
  python manage_config.py install --file authentication.yaml
  
  # Install with overwrite mode
  python manage_config.py install --update-mode overwrite
  
  # Validate configuration
  python manage_config.py validate
  
  # Validate for production environment
  python manage_config.py validate --environment production
  
  # Backup current configuration
  python manage_config.py backup
  
  # Restore from backup
  python manage_config.py restore --backup-dir ./config-backup-20250127_143022
        """
    )
    
    parser.add_argument(
        "--config-dir",
        default=None,
        help="External configuration directory (default: ./config or TRAKBRIDGE_CONFIG_DIR)"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # List command
    list_parser = subparsers.add_parser("list", help="List all configuration files")
    list_parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    
    # Install command
    install_parser = subparsers.add_parser("install", help="Install configuration files")
    install_parser.add_argument("--file", help="Specific file to install (default: all)")
    install_parser.add_argument(
        "--update-mode", 
        choices=["preserve", "overwrite", "merge"], 
        default="preserve",
        help="How to handle existing files"
    )
    
    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate configuration")
    validate_parser.add_argument("--environment", default="development", help="Environment to validate")
    validate_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    
    # Backup command
    backup_parser = subparsers.add_parser("backup", help="Backup configuration")
    backup_parser.add_argument("--backup-dir", help="Backup directory path")
    
    # Restore command
    restore_parser = subparsers.add_parser("restore", help="Restore configuration from backup")
    restore_parser.add_argument("--backup-dir", required=True, help="Backup directory path")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        config_manager = ConfigManager(external_config_dir=args.config_dir)
        
        if args.command == "list":
            configs = config_manager.list_configs()
            
            if args.format == "json":
                print(json.dumps(configs, indent=2))
            else:
                print(f"Configuration files (External dir: {config_manager.external_config_dir}):")
                print("-" * 80)
                for filename, info in configs.items():
                    status = info["status"]
                    print(f"{filename:30} | {status:15}")
                    if info.get("files_differ"):
                        print(f"{'':30} | {'(differs from bundled)':15}")
        
        elif args.command == "install":
            success = config_manager.install_config(
                filename=args.file,
                update_mode=args.update_mode
            )
            sys.exit(0 if success else 1)
            
        elif args.command == "validate":
            results = config_manager.validate_config(environment=args.environment)
            
            if args.format == "json":
                print(json.dumps(results, indent=2))
            else:
                print(f"Configuration validation for environment: {results['environment']}")
                print("-" * 60)
                
                if results["valid"]:
                    print("✓ Configuration is valid")
                else:
                    print("✗ Configuration has issues")
                
                if results["issues"]:
                    print("\nIssues:")
                    for issue in results["issues"]:
                        print(f"  - {issue}")
                
                if results["warnings"]:
                    print("\nWarnings:")
                    for warning in results["warnings"]:
                        print(f"  - {warning}")
                
                print("\nConfiguration sources:")
                for filename, source in results["config_sources"].items():
                    print(f"  {filename:20} | {source}")
            
            sys.exit(0 if results["valid"] else 1)
            
        elif args.command == "backup":
            backup_path = config_manager.backup_config(backup_dir=args.backup_dir)
            print(f"Configuration backed up to: {backup_path}")
            
        elif args.command == "restore":
            success = config_manager.restore_config(backup_dir=args.backup_dir)
            sys.exit(0 if success else 1)
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()