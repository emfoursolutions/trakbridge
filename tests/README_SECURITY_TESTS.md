# TrakBridge Security Tests

This directory contains security-specific tests that validate the security fixes implemented in response to the Semgrep security analysis conducted on 2025-07-28.

## Security Test Files

### `test_security_fixes.py`
Comprehensive security tests covering:

1. **Host Header Injection Prevention**
   - Tests APPLICATION_URL configuration
   - Validates OIDC callback URL security
   - Ensures malicious host headers are ignored

2. **Dynamic Import Security** 
   - Path traversal prevention tests
   - Invalid character validation
   - Dangerous module blocking
   - Input type validation
   - Error handling verification

3. **Nginx H2C Request Smuggling Prevention**
   - Configuration validation tests
   - WebSocket functionality preservation
   - Security pattern verification

4. **Security Configuration Integration**
   - End-to-end configuration tests
   - Logging validation
   - Flask integration tests

### `run_security_tests.py`
Automated test runner that:
- Executes all security tests
- Validates security configurations
- Provides summary reporting
- Returns appropriate exit codes for CI/CD

## Running the Tests

### Quick Security Validation
```bash
# Run all security tests and validations
python tests/run_security_tests.py
```

### Individual Test Categories
```bash
# Run only the security fix tests
pytest tests/test_security_fixes.py -v

# Run specific test class
pytest tests/test_security_fixes.py::TestHostHeaderInjectionPrevention -v

# Run with detailed output
pytest tests/test_security_fixes.py -v -s --tb=long
```

### CI/CD Integration
```bash
# For CI/CD pipelines - returns proper exit codes
python tests/run_security_tests.py
echo $?  # 0 = success, 1 = failure
```

## Test Coverage

The security tests provide coverage for:

- ✅ **Critical Vulnerabilities**: HTTP Request Smuggling, Host Header Injection
- ✅ **Medium Risk Issues**: Dynamic Import Security Enhancement  
- ✅ **Configuration Validation**: Security settings verification
- ✅ **Integration Testing**: End-to-end security flow validation
- ✅ **Regression Prevention**: Ensures fixes remain in place

## Security Test Categories

### Unit Tests
Test individual security functions and methods in isolation.

### Integration Tests  
Test security features working together across components.

### Configuration Tests
Validate that security configurations are properly applied.

### Regression Tests
Ensure that security fixes don't break existing functionality.

## Expected Results

When all security tests pass, you should see output similar to:
```
✅ Nginx H2C protection enabled
✅ Nginx WebSocket support maintained  
✅ Application URL configuration present
✅ Plugin path traversal protection enabled
✅ Plugin dangerous module protection enabled
✅ Security tests passed: tests/test_security_fixes.py
🎉 All security validations and tests passed!
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure you're running from the project root directory
2. **Configuration Missing**: Check that security fixes are properly applied
3. **Test Failures**: Review the specific test output for details

### Debugging Tests
```bash
# Run with maximum verbosity
pytest tests/test_security_fixes.py -vvv --tb=long

# Run single test with debugging
pytest tests/test_security_fixes.py::TestDynamicImportSecurity::test_module_name_validation_path_traversal -vvv -s
```

## Continuous Integration

These tests should be run:
- ✅ Before every deployment
- ✅ After any security-related code changes  
- ✅ As part of regular security testing cycles
- ✅ When updating dependencies that could affect security

## Security Test Maintenance

When adding new security features:
1. Add corresponding tests to `test_security_fixes.py`
2. Update the test runner if needed
3. Update this README with new test information
4. Ensure CI/CD pipeline includes the new tests

## Related Documentation

- [`docs/SECURITY_ANALYSIS.md`](../docs/SECURITY_ANALYSIS.md) - Detailed security analysis report
- [`docs/DOCKER_SECURITY.md`](../docs/DOCKER_SECURITY.md) - Container security documentation
- [`docs/JSON_VALIDATION_SECURITY.md`](../docs/JSON_VALIDATION_SECURITY.md) - Input validation security

## Security Contact

For security-related questions about these tests or to report security issues, please follow the security reporting guidelines in the main project documentation.