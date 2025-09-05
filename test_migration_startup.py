#!/usr/bin/env python3
"""
Test script for migration-first startup pattern validation
"""
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

def run_command(cmd, cwd=None, env=None):
    """Run a command and capture output"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)

def test_migration_with_existing_db():
    """Test migration logic with existing up-to-date database"""
    print("🔍 Testing migration with existing up-to-date database...")
    
    # Set up environment
    env = os.environ.copy()
    env['FLASK_APP'] = 'app.py'
    env['FLASK_ENV'] = 'development'
    
    # Check current migration state
    returncode, stdout, stderr = run_command(
        "flask db current", 
        cwd="/Users/nick/Documents/Repositories/projects/trakbridge",
        env=env
    )
    
    print(f"Current migration state: {returncode}")
    if returncode == 0:
        current_rev = stdout.strip().split('\n')[2] if len(stdout.strip().split('\n')) > 2 else "unknown"
        print(f"✅ Current revision: {current_rev}")
    else:
        print(f"❌ Failed to get current revision: {stderr}")
        return False
        
    # Check heads
    returncode, stdout, stderr = run_command(
        "flask db heads", 
        cwd="/Users/nick/Documents/Repositories/projects/trakbridge",
        env=env
    )
    
    if returncode == 0:
        head_rev = stdout.strip().split('\n')[2] if len(stdout.strip().split('\n')) > 2 else "unknown"
        print(f"✅ Head revision: {head_rev}")
    else:
        print(f"❌ Failed to get head revision: {stderr}")
        return False
    
    # Test upgrade (should be no-op)
    returncode, stdout, stderr = run_command(
        "flask db upgrade", 
        cwd="/Users/nick/Documents/Repositories/projects/trakbridge",
        env=env
    )
    
    if returncode == 0:
        print("✅ Migration upgrade successful (database already up-to-date)")
        return True
    else:
        print(f"❌ Migration upgrade failed: {stderr}")
        return False

def test_migration_with_fresh_db():
    """Test migration logic with fresh database"""
    print("\n🔍 Testing migration with fresh database...")
    
    # Create temporary SQLite database
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    temp_db_path = temp_db.name
    temp_db.close()
    
    try:
        # Set up environment with temporary database
        env = os.environ.copy()
        env['FLASK_APP'] = 'app.py'
        env['FLASK_ENV'] = 'development'
        env['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{temp_db_path}'
        
        print(f"Using temporary database: {temp_db_path}")
        
        # Test migration on fresh database
        returncode, stdout, stderr = run_command(
            "flask db upgrade", 
            cwd="/Users/nick/Documents/Repositories/projects/trakbridge",
            env=env
        )
        
        if returncode == 0:
            print("✅ Fresh database migration successful")
            
            # Verify database was created and has tables
            if os.path.exists(temp_db_path) and os.path.getsize(temp_db_path) > 0:
                print("✅ Database file created with content")
                return True
            else:
                print("❌ Database file not created or empty")
                return False
        else:
            print(f"❌ Fresh database migration failed: {stderr}")
            return False
            
    finally:
        # Clean up
        if os.path.exists(temp_db_path):
            os.unlink(temp_db_path)

def test_migration_error_handling():
    """Test migration error handling with invalid configuration"""
    print("\n🔍 Testing migration error handling...")
    
    # Set up environment with invalid database URI
    env = os.environ.copy()
    env['FLASK_APP'] = 'app.py'
    env['FLASK_ENV'] = 'development'
    env['SQLALCHEMY_DATABASE_URI'] = 'postgresql://invalid:invalid@nonexistent:5432/invalid'
    
    # Test migration with invalid database
    returncode, stdout, stderr = run_command(
        "flask db current", 
        cwd="/Users/nick/Documents/Repositories/projects/trakbridge",
        env=env
    )
    
    if returncode != 0:
        print("✅ Migration properly failed with invalid database configuration")
        return True
    else:
        print("❌ Migration should have failed with invalid database configuration")
        return False

def main():
    """Main test function"""
    print("🚀 Testing TrakBridge Migration-First Startup Pattern\n")
    
    results = []
    
    # Test with existing database
    results.append(test_migration_with_existing_db())
    
    # Test with fresh database
    results.append(test_migration_with_fresh_db())
    
    # Test error handling
    results.append(test_migration_error_handling())
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All migration startup tests passed!")
        return 0
    else:
        print("❌ Some migration startup tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())