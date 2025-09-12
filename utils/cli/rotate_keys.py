#!/usr/bin/env python3
"""
Key Rotation Script for TrakBridge

This script rotates the encryption key and re-encrypts all sensitive data in the database.
"""

import base64
import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import click

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.encryption_service import EncryptionService, get_encryption_service


def get_database_info():
    """Get database type and connection information"""
    try:
        from app import app

        with app.app_context():
            from database import db

            # Get database URI
            db_uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")

            # Determine database type
            if "sqlite" in db_uri.lower():
                db_type = "sqlite"
                db_path = db_uri.replace("sqlite:///", "")
                if db_path.startswith("/"):
                    db_path = db_path
                else:
                    # Relative path, make it absolute
                    db_path = os.path.join(os.getcwd(), db_path)
            elif "mysql" in db_uri.lower():
                db_type = "mysql"
                db_path = db_uri
            elif "postgresql" in db_uri.lower():
                db_type = "postgresql"
                db_path = db_uri
            else:
                db_type = "unknown"
                db_path = db_uri

            return {
                "type": db_type,
                "uri": db_uri,
                "path": db_path,
                "engine": str(db.engine),
            }
    except Exception as e:
        return {"type": "unknown", "uri": "unknown", "path": "unknown", "error": str(e)}


def backup_sqlite(db_info, backup_dir, timestamp):
    """Backup SQLite database"""
    try:
        db_path = db_info["path"]
        backup_path = backup_dir / f"trakbridge_sqlite_{timestamp}.db"

        # Copy the database file
        shutil.copy2(db_path, backup_path)

        return {
            "success": True,
            "backup_path": str(backup_path),
            "size": backup_path.stat().st_size,
            "type": "sqlite",
        }
    except Exception as e:
        return {"success": False, "error": str(e), "backup_path": None}


def backup_mysql(db_info, backup_dir, timestamp):
    """Backup MySQL database"""
    try:
        # Extract database name from URI
        uri = db_info["uri"]
        # Parse mysql://user:pass@host:port/dbname
        db_name = uri.split("/")[-1].split("?")[0]

        backup_path = backup_dir / f"trakbridge_mysql_{timestamp}.sql"

        # Use mysqldump
        cmd = ["mysqldump", "--single-transaction", "--routines", "--triggers", db_name]

        # Add credentials if in URI
        if "@" in uri:
            # Extract user:pass@host:port
            auth_host = uri.split("://")[1].split("/")[0]
            if ":" in auth_host.split("@")[0]:
                user_pass = auth_host.split("@")[0]
                user, password = user_pass.split(":", 1)
                cmd.extend(["-u", user, f"-p{password}"])

        with open(backup_path, "w") as f:
            result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True)

        if result.returncode == 0:
            return {
                "success": True,
                "backup_path": str(backup_path),
                "size": backup_path.stat().st_size,
                "type": "mysql",
            }
        else:
            return {
                "success": False,
                "error": f"mysqldump failed: {result.stderr}",
                "backup_path": None,
            }

    except Exception as e:
        return {"success": False, "error": str(e), "backup_path": None}


def backup_postgresql(db_info, backup_dir, timestamp):
    """Backup PostgreSQL database"""
    try:
        # Extract database name from URI
        uri = db_info["uri"]
        db_name = uri.split("/")[-1]

        backup_path = backup_dir / f"trakbridge_postgresql_{timestamp}.sql"

        # Use pg_dump
        cmd = [
            "pg_dump",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            db_name,
        ]

        # Add credentials if in URI
        if "@" in uri:
            # Extract user:pass@host:port
            auth_host = uri.split("://")[1].split("/")[0]
            if ":" in auth_host.split("@")[0]:
                user_pass = auth_host.split("@")[0]
                user, password = user_pass.split(":", 1)
                cmd.extend(["-U", user])
                # Set password environment variable
                env = os.environ.copy()
                env["PGPASSWORD"] = password
            else:
                env = os.environ.copy()
        else:
            env = os.environ.copy()

        with open(backup_path, "w") as f:
            result = subprocess.run(
                cmd, stdout=f, stderr=subprocess.PIPE, text=True, env=env
            )

        if result.returncode == 0:
            return {
                "success": True,
                "backup_path": str(backup_path),
                "size": backup_path.stat().st_size,
                "type": "postgresql",
            }
        else:
            return {
                "success": False,
                "error": f"pg_dump failed: {result.stderr}",
                "backup_path": None,
            }

    except Exception as e:
        return {"success": False, "error": str(e), "backup_path": None}


def create_database_backup():
    """Create a backup of the database based on its type"""
    try:
        db_info = get_database_info()
        db_type = db_info["type"]

        # Create backup directory
        backup_dir = Path("backups")
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if db_type == "sqlite":
            return backup_sqlite(db_info, backup_dir, timestamp)
        elif db_type == "mysql":
            return backup_mysql(db_info, backup_dir, timestamp)
        elif db_type == "postgresql":
            return backup_postgresql(db_info, backup_dir, timestamp)
        else:
            return {
                "success": False,
                "error": f"Unsupported database type: {db_type}",
                "backup_path": None,
            }

    except Exception as e:
        return {"success": False, "error": str(e), "backup_path": None}


@click.command()
@click.option("--new-key", help="New encryption key (will prompt if not provided)")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.option(
    "--backup-db", is_flag=True, help="Create database backup before rotation"
)
@click.option("--generate-key", is_flag=True, help="Generate a new key automatically")
def rotate_keys(new_key, confirm, backup_db, generate_key):
    """Rotate the encryption key and re-encrypt all data"""

    # Handle key generation first
    if generate_key:
        new_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        click.echo(f"🔑 Generated new key: {new_key}")

    # Prompt for key if not provided and not generated
    if not new_key:
        new_key = click.prompt("Enter new master key")

    # Show what we're about to do
    click.echo(f"Using key: {new_key[:20]}...")
    click.echo(f"Backup database: {'Yes' if backup_db else 'No'}")
    click.echo(f"Skip confirmation: {'Yes' if confirm else 'No'}")

    # Confirmation check
    if not confirm:
        click.echo(
            "\n WARNING: This will re-encrypt all sensitive data with a new key."
        )
        click.echo("Make sure to backup your database before proceeding.")
        if not click.confirm("Do you want to continue?"):
            click.echo("Key rotation cancelled.")
            return

    try:
        # Create database backup if requested
        if backup_db:
            click.echo("\nCreating database backup...")
            backup_result = create_database_backup()

            if backup_result["success"]:
                click.echo(f"Backup created: {backup_result['backup_path']}")
                click.echo(f"Size: {backup_result['size']} bytes")
                click.echo(f" Type: {backup_result['type']}")
            else:
                click.echo(f"Backup failed: {backup_result['error']}")
                if not click.confirm("Continue without backup?"):
                    click.echo("Key rotation cancelled.")
                    return
                click.echo(" Proceeding without backup...")

        # Set up Flask application context for database operations
        click.echo("\nSetting up database connection...")
        from app import app

        with app.app_context():
            encryption_service = get_encryption_service()

            # Test the new key
            click.echo("Testing new key...")
            test_service = EncryptionService(new_key)
            test_encrypted = test_service.encrypt_value("test")
            test_decrypted = test_service.decrypt_value(test_encrypted)

            if test_decrypted != "test":
                click.echo("Error: New key test failed. Please check your key.")
                return

            click.echo("New key test successful.")

            # Rotate database keys (now includes both TAK servers and stream plugins)
            click.echo("Rotating database keys...")
            result = encryption_service.rotate_database_keys(new_key)

            if result["success"]:
                click.echo(f"{result['message']}")
                click.echo(
                    f"Rotated {result['rotated_count']} encrypted passwords (certificates + plugin configs)"
                )

                if result["errors"]:
                    click.echo(" Some errors occurred:")
                    for error in result["errors"]:
                        click.echo(f"   - {error}")
            else:
                click.echo(
                    f"Key rotation failed: {result.get('error', 'Unknown error')}"
                )
                return

        # Update environment variable or key file
        click.echo("\nKey rotation completed successfully!")
        click.echo(
            "Please update your TB_MASTER_KEY environment variable or key file with:"
        )
        click.echo(f" TB_MASTER_KEY='{new_key}'")
        click.echo(
            "\n IMPORTANT: Restart the application with the new key for changes to take effect."
        )

    except Exception as e:
        click.echo(f"Key rotation failed: {e}")
        return


if __name__ == "__main__":
    rotate_keys()
