#!/usr/bin/env python3
"""
Security Test Runner

Simple script to run the security tests and verify that all security fixes
are working properly. This can be used in CI/CD pipelines or for manual
verification.

Usage:
    python tests/run_security_tests.py
"""

import logging
import os
import subprocess
import sys

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_security_tests():
    """Run all security-related tests"""
    logger.info("Starting TrakBridge Security Test Suite")

    # Test files to run
    security_test_files = ["tests/test_security_fixes.py"]

    success = True

    for test_file in security_test_files:
        test_path = os.path.join(project_root, test_file)

        if not os.path.exists(test_path):
            logger.error(f"Test file not found: {test_path}")
            success = False
            continue

        logger.info(f"Running security tests: {test_file}")

        try:
            # Run pytest on the specific test file
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    test_path,
                    "-v",  # verbose output
                    "--tb=short",  # short traceback format
                    "--no-header",  # no pytest header
                    "-q",  # quiet mode, less output
                ],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=60,  # 60 second timeout
            )

            if result.returncode == 0:
                logger.info(f"✅ Security tests passed: {test_file}")
                if result.stdout:
                    logger.info(f"Test output:\n{result.stdout}")
            else:
                logger.error(f"❌ Security tests failed: {test_file}")
                logger.error(f"Return code: {result.returncode}")
                if result.stdout:
                    logger.error(f"STDOUT:\n{result.stdout}")
                if result.stderr:
                    logger.error(f"STDERR:\n{result.stderr}")
                success = False

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Security tests timed out: {test_file}")
            success = False
        except Exception as e:
            logger.error(f"❌ Error running security tests {test_file}: {e}")
            success = False

    return success


def validate_security_configurations():
    """Validate that security configurations are in place"""
    logger.info("Validating security configurations")

    validations = []

    # Check nginx configuration
    nginx_config_path = os.path.join(project_root, "init/nginx/nginx.conf")
    if os.path.exists(nginx_config_path):
        with open(nginx_config_path, "r") as f:
            nginx_content = f.read()

        # Check H2C protection
        if 'set $upgrade_header ""' in nginx_content:
            validations.append("✅ Nginx H2C protection enabled")
        else:
            validations.append("❌ Nginx H2C protection missing")

        # Check WebSocket support maintained
        if "proxy_http_version 1.1" in nginx_content:
            validations.append("✅ Nginx WebSocket support maintained")
        else:
            validations.append("❌ Nginx WebSocket support missing")
    else:
        validations.append("❌ Nginx configuration file not found")

    # Check application URL configuration
    app_config_path = os.path.join(project_root, "config/settings/app.yaml")
    if os.path.exists(app_config_path):
        with open(app_config_path, "r") as f:
            app_content = f.read()

        if "application_url:" in app_content:
            validations.append("✅ Application URL configuration present")
        else:
            validations.append("❌ Application URL configuration missing")
    else:
        validations.append("❌ Application configuration file not found")

    # Check plugin manager security enhancements
    plugin_manager_path = os.path.join(project_root, "plugins/plugin_manager.py")
    if os.path.exists(plugin_manager_path):
        with open(plugin_manager_path, "r") as f:
            plugin_content = f.read()

        if "Path traversal attempt detected" in plugin_content:
            validations.append("✅ Plugin path traversal protection enabled")
        else:
            validations.append("❌ Plugin path traversal protection missing")

        if "dangerous_prefixes" in plugin_content:
            validations.append("✅ Plugin dangerous module protection enabled")
        else:
            validations.append("❌ Plugin dangerous module protection missing")
    else:
        validations.append("❌ Plugin manager file not found")

    # Print validation results
    for validation in validations:
        if validation.startswith("✅"):
            logger.info(validation)
        else:
            logger.error(validation)

    # Return True if all validations passed
    return all(v.startswith("✅") for v in validations)


def main():
    """Main entry point"""
    logger.info("=" * 60)
    logger.info("TrakBridge Security Validation Suite")
    logger.info("=" * 60)

    # Run configuration validation
    config_valid = validate_security_configurations()

    logger.info("-" * 60)

    # Run security tests
    tests_passed = run_security_tests()

    logger.info("-" * 60)

    # Summary
    if config_valid and tests_passed:
        logger.info("🎉 All security validations and tests passed!")
        logger.info("TrakBridge security fixes are working correctly.")
        return 0
    else:
        logger.error("⚠️  Some security validations or tests failed!")
        logger.error("Please review the output above and fix any issues.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
