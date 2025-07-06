# =============================================================================
# services/key_rotation_service.py - Key Rotation Service with Web Interface
# =============================================================================

import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging
import json

from flask import current_app
from services.encryption_service import get_encryption_service, EncryptionService


class KeyRotationService:
    """Service for rotating encryption keys with database backup and web interface"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.rotation_log: List[Dict[str, Any]] = []
        self.is_rotating = False
        self.rotation_thread: Optional[threading.Thread] = None

    def get_database_info(self) -> Dict[str, Any]:
        """Get database type and connection information"""
        try:
            from database import db
            
            # Get database URI
            db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
            
            # Determine database type
            if 'sqlite' in db_uri.lower():
                db_type = 'sqlite'
                db_path = db_uri.replace('sqlite:///', '')
                if db_path.startswith('/'):
                    db_path = db_path
                else:
                    # Relative path, make it absolute
                    db_path = os.path.join(os.getcwd(), db_path)
            elif 'mysql' in db_uri.lower():
                db_type = 'mysql'
                db_path = db_uri
            elif 'postgresql' in db_uri.lower():
                db_type = 'postgresql'
                db_path = db_uri
            else:
                db_type = 'unknown'
                db_path = db_uri

            return {
                'type': db_type,
                'uri': db_uri,
                'path': db_path,
                'engine': str(db.engine)
            }
        except Exception as e:
            self.logger.error(f"Error getting database info: {e}")
            return {
                'type': 'unknown',
                'uri': 'unknown',
                'path': 'unknown',
                'error': str(e)
            }

    def create_database_backup(self) -> Dict[str, Any]:
        """Create a backup of the database based on its type"""
        try:
            db_info = self.get_database_info()
            db_type = db_info['type']
            
            # Create backup directory
            backup_dir = Path('backups')
            backup_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if db_type == 'sqlite':
                return self._backup_sqlite(db_info, backup_dir, timestamp)
            elif db_type == 'mysql':
                return self._backup_mysql(db_info, backup_dir, timestamp)
            elif db_type == 'postgresql':
                return self._backup_postgresql(db_info, backup_dir, timestamp)
            else:
                return {
                    'success': False,
                    'error': f'Unsupported database type: {db_type}',
                    'backup_path': None
                }
                
        except Exception as e:
            self.logger.error(f"Error creating database backup: {e}")
            return {
                'success': False,
                'error': str(e),
                'backup_path': None
            }

    def _backup_sqlite(self, db_info: Dict[str, Any], backup_dir: Path, timestamp: str) -> Dict[str, Any]:
        """Backup SQLite database"""
        try:
            db_path = db_info['path']
            backup_path = backup_dir / f"trakbridge_sqlite_{timestamp}.db"
            
            # Copy the database file
            shutil.copy2(db_path, backup_path)
            
            return {
                'success': True,
                'backup_path': str(backup_path),
                'size': backup_path.stat().st_size,
                'type': 'sqlite'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'backup_path': None
            }

    def _backup_mysql(self, db_info: Dict[str, Any], backup_dir: Path, timestamp: str) -> Dict[str, Any]:
        """Backup MySQL database"""
        try:
            # Extract database name from URI
            uri = db_info['uri']
            # Parse mysql://user:pass@host:port/dbname
            db_name = uri.split('/')[-1].split('?')[0]
            
            backup_path = backup_dir / f"trakbridge_mysql_{timestamp}.sql"
            
            # Use mysqldump
            cmd = [
                'mysqldump',
                '--single-transaction',
                '--routines',
                '--triggers',
                db_name
            ]
            
            # Add credentials if in URI
            if '@' in uri:
                # Extract user:pass@host:port
                auth_host = uri.split('://')[1].split('/')[0]
                if ':' in auth_host.split('@')[0]:
                    user_pass = auth_host.split('@')[0]
                    user, password = user_pass.split(':', 1)
                    cmd.extend(['-u', user, f'-p{password}'])
            
            with open(backup_path, 'w') as f:
                result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)
            
            if result.returncode == 0:
                return {
                    'success': True,
                    'backup_path': str(backup_path),
                    'size': backup_path.stat().st_size,
                    'type': 'mysql'
                }
            else:
                return {
                    'success': False,
                    'error': f'mysqldump failed: {result.stderr}',
                    'backup_path': None
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'backup_path': None
            }

    def _backup_postgresql(self, db_info: Dict[str, Any], backup_dir: Path, timestamp: str) -> Dict[str, Any]:
        """Backup PostgreSQL database"""
        try:
            # Extract database name from URI
            uri = db_info['uri']
            db_name = uri.split('/')[-1]
            
            backup_path = backup_dir / f"trakbridge_postgresql_{timestamp}.sql"
            
            # Use pg_dump
            cmd = [
                'pg_dump',
                '--clean',
                '--if-exists',
                '--no-owner',
                '--no-privileges',
                db_name
            ]
            
            # Add credentials if in URI
            if '@' in uri:
                # Extract user:pass@host:port
                auth_host = uri.split('://')[1].split('/')[0]
                if ':' in auth_host.split('@')[0]:
                    user_pass = auth_host.split('@')[0]
                    user, password = user_pass.split(':', 1)
                    cmd.extend(['-U', user])
                    # Set password environment variable
                    env = os.environ.copy()
                    env['PGPASSWORD'] = password
                else:
                    env = os.environ.copy()
            else:
                env = os.environ.copy()
            
            with open(backup_path, 'w') as f:
                result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True, env=env)
            
            if result.returncode == 0:
                return {
                    'success': True,
                    'backup_path': str(backup_path),
                    'size': backup_path.stat().st_size,
                    'type': 'postgresql'
                }
            else:
                return {
                    'success': False,
                    'error': f'pg_dump failed: {result.stderr}',
                    'backup_path': None
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'backup_path': None
            }

    def get_key_storage_info(self) -> Dict[str, Any]:
        """Detect current key storage method"""
        try:
            # Check environment variable
            if os.environ.get('TB_MASTER_KEY'):
                return {
                    'method': 'environment_variable',
                    'name': 'TB_MASTER_KEY',
                    'secure': True
                }
            
            # Check key file
            app_root = current_app.root_path
            key_file_paths = [
                os.path.join(app_root, 'secrets', 'tb_master_key'),
            ]
            
            for key_file_path in key_file_paths:
                if os.path.exists(key_file_path):
                    return {
                        'method': 'file',
                        'path': key_file_path,
                        'secure': True
                    }
            
            return {
                'method': 'generated',
                'secure': False,
                'warning': 'Using generated key - not persistent'
            }
            
        except Exception as e:
            return {
                'method': 'unknown',
                'error': str(e),
                'secure': False
            }

    def update_key_storage(self, new_key: str) -> Dict[str, Any]:
        """Update key storage method with new key"""
        try:
            storage_info = self.get_key_storage_info()
            method = storage_info.get('method')
            
            if method == 'environment_variable':
                return {
                    'success': True,
                    'method': 'environment_variable',
                    'instruction': f'Set environment variable: export TB_MASTER_KEY="{new_key}"'
                }
            
            elif method == 'file':
                key_file_path = storage_info.get('path')
                if key_file_path:
                    # Create directory if it doesn't exist
                    os.makedirs(os.path.dirname(key_file_path), exist_ok=True)
                    
                    # Write new key to file
                    with open(key_file_path, 'w') as f:
                        f.write(new_key)
                    
                    return {
                        'success': True,
                        'method': 'file',
                        'path': key_file_path,
                        'message': 'Key file updated successfully'
                    }
            
            else:
                # Create key file as default
                app_root = current_app.root_path
                key_file_path = os.path.join(app_root, 'secrets', 'tb_master_key')
                os.makedirs(os.path.dirname(key_file_path), exist_ok=True)
                
                with open(key_file_path, 'w') as f:
                    f.write(new_key)
                
                return {
                    'success': True,
                    'method': 'file',
                    'path': key_file_path,
                    'message': 'Created new key file'
                }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def start_rotation(self, new_key: str, create_backup: bool = True, flask_app=None) -> Dict[str, Any]:
        """Start key rotation in a background thread"""
        if self.is_rotating:
            return {
                'success': False,
                'error': 'Key rotation already in progress'
            }
        
        self.is_rotating = True
        self.rotation_log = []
        
        # Get the Flask app instance for the background thread
        if flask_app is None:
            from flask import current_app
            flask_app = current_app._get_current_object()  # Get the actual app object, not the proxy
        
        def rotation_worker():
            try:
                # Set up Flask application context for the background thread
                with flask_app.app_context():
                    self._log("Starting key rotation process...")
                    
                    # Step 1: Create backup
                    if create_backup:
                        self._log("Creating database backup...")
                        backup_result = self.create_database_backup()
                        if backup_result['success']:
                            self._log(f"Backup created: {backup_result['backup_path']}")
                        else:
                            self._log(f"Backup failed: {backup_result['error']}")
                            return None
                    
                    # Step 2: Test new key
                    self._log("Testing new encryption key...")
                    test_service = EncryptionService(new_key)
                    test_encrypted = test_service.encrypt_value("test")
                    test_decrypted = test_service.decrypt_value(test_encrypted)
                    
                    if test_decrypted != "test":
                        self._log("New key test failed")
                        return None
                    
                    self._log("New key test successful")
                    
                    # Step 3: Rotate database keys
                    self._log("Rotating database keys...")
                    encryption_service = get_encryption_service()
                    result = encryption_service.rotate_database_keys(new_key)
                    
                    if result["success"]:
                        self._log(f"{result['message']}")
                        self._log(f"Rotated {result['rotated_count']} certificate passwords")
                        
                        if result["errors"]:
                            for error in result["errors"]:
                                self._log(f"Error: {error}")
                    else:
                        self._log(f"Key rotation failed: {result.get('error', 'Unknown error')}")
                        return None
                    
                    # Step 4: Update key storage
                    self._log("Updating key storage...")
                    storage_result = self.update_key_storage(new_key)
                    if storage_result['success']:
                        self._log(f"Key storage updated: {storage_result.get('message', 'Success')}")
                    else:
                        self._log(f"Key storage update failed: {storage_result.get('error')}")
                    
                    self._log("Key rotation completed successfully!")
                    self._log("IMPORTANT: Restart the application for changes to take effect.")
                    
            except Exception as e:
                self._log(f"Key rotation failed: {e}")
            finally:
                self.is_rotating = False
            
            return None
        
        self.rotation_thread = threading.Thread(target=rotation_worker, daemon=True)
        self.rotation_thread.start()
        
        return {
            'success': True,
            'message': 'Key rotation started in background'
        }

    def get_rotation_status(self) -> Dict[str, Any]:
        """Get current rotation status and log"""
        return {
            'is_rotating': self.is_rotating,
            'log': self.rotation_log.copy(),
            'completed': not self.is_rotating and len(self.rotation_log) > 0
        }

    def _log(self, message: str):
        """Add a log entry with timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = {
            'timestamp': timestamp,
            'message': message
        }
        self.rotation_log.append(log_entry)
        self.logger.info(f"Key Rotation: {message}")

    def restart_application(self) -> Dict[str, Any]:
        """Attempt to restart the application"""
        try:
            # This is a complex operation that depends on deployment method
            # For now, we'll provide instructions
            
            # Check if we're running in a container
            if os.path.exists('/.dockerenv'):
                return {
                    'success': False,
                    'method': 'container',
                    'instruction': 'Restart the Docker container to apply new key'
                }
            
            # Check if we're running with systemd
            try:
                result = subprocess.run(['systemctl', 'is-active', 'trakbridge'], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    return {
                        'success': True,
                        'method': 'systemd',
                        'instruction': 'Run: sudo systemctl restart trakbridge'
                    }
            except FileNotFoundError:
                pass
            
            # Check if we're running with supervisor
            try:
                result = subprocess.run(['supervisorctl', 'status', 'trakbridge'], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    return {
                        'success': True,
                        'method': 'supervisor',
                        'instruction': 'Run: supervisorctl restart trakbridge'
                    }
            except FileNotFoundError:
                pass
            
            return {
                'success': False,
                'method': 'manual',
                'instruction': 'Manually restart the application process'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'instruction': 'Manually restart the application'
            }


# Global instance
key_rotation_service = KeyRotationService()


def get_key_rotation_service():
    """Get the key rotation service instance"""
    return key_rotation_service 