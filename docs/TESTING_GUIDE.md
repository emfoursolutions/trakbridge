# TrakBridge Testing Guide

This comprehensive guide covers all testing strategies, requirements, and best practices for the TrakBridge project.

## 🧪 Testing Philosophy

TrakBridge follows a comprehensive testing strategy with multiple layers:

1. **Unit Tests** - Individual component testing
2. **Integration Tests** - Service and database integration
3. **Security Tests** - Vulnerability and compliance validation
4. **End-to-End Tests** - Full application workflow testing
5. **Performance Tests** - Response time and load benchmarks

## 📋 Testing Requirements

### Coverage Requirements

- **Minimum Code Coverage:** 75%
- **Branch Coverage:** Enabled
- **Line Coverage:** Required for all critical paths
- **Function Coverage:** 100% for public APIs

### Quality Gates

All tests must pass these gates before deployment:

- ✅ All test categories must pass
- ✅ Security scans show no critical issues
- ✅ Performance benchmarks meet thresholds
- ✅ Code coverage meets minimum requirements
- ✅ No hardcoded secrets or debug flags in production

## 🏗️ Test Structure

```
tests/
├── unit/                 # Unit tests
│   ├── test_models.py
│   ├── test_services.py
│   └── test_plugins.py
├── integration/          # Integration tests
│   ├── test_database.py
│   ├── test_api.py
│   └── test_streams.py
├── e2e/                  # End-to-end tests
│   ├── test_basic_e2e.py
│   ├── test_user_flows.py
│   └── test_api_workflows.py
├── performance/          # Performance tests
│   ├── test_benchmarks.py
│   └── test_load.py
├── security/             # Security tests
│   ├── test_auth.py
│   ├── test_validation.py
│   └── test_vulnerabilities.py
└── fixtures/             # Test data and fixtures
    ├── sample_data.json
    └── mock_responses.py
```

## 🔬 Unit Testing

### Running Unit Tests

```bash
# Run all unit tests with coverage
pytest tests/unit/ -v --cov=. --cov-report=html --cov-fail-under=75

# Run specific test file
pytest tests/unit/test_models.py -v

# Run tests with detailed coverage
pytest tests/unit/ -v --cov=. --cov-report=term-missing --cov-branch
```

### Unit Test Examples

#### Model Testing

```python
# tests/unit/test_models.py
import pytest
from models.stream import Stream
from models.tak_server import TAKServer

class TestStreamModel:
    def test_stream_creation(self):
        """Test Stream model creation."""
        stream = Stream(
            name="Test Stream",
            plugin_name="garmin_plugin",
            config={"api_key": "test-key"}
        )
        
        assert stream.name == "Test Stream"
        assert stream.plugin_name == "garmin_plugin"
        assert stream.is_active is False
        
    def test_stream_validation(self):
        """Test Stream model validation."""
        with pytest.raises(ValueError):
            Stream(name="", plugin_name="invalid_plugin")
```

#### Service Testing

```python
# tests/unit/test_services.py
import pytest
from unittest.mock import Mock, patch
from services.stream_manager import StreamManager

class TestStreamManager:
    @pytest.fixture
    def stream_manager(self):
        return StreamManager()
    
    @patch('services.stream_manager.get_plugin_class')
    def test_start_stream(self, mock_get_plugin, stream_manager):
        """Test starting a stream."""
        mock_plugin = Mock()
        mock_get_plugin.return_value = mock_plugin
        
        result = stream_manager.start_stream(1)
        
        assert result is True
        mock_plugin.start.assert_called_once()
```

### Unit Test Best Practices

1. **Test One Thing:** Each test should verify one specific behavior
2. **Use Descriptive Names:** Test names should explain what they verify
3. **Arrange-Act-Assert:** Structure tests with clear setup, execution, and verification
4. **Mock External Dependencies:** Isolate units by mocking external services
5. **Test Edge Cases:** Include boundary conditions and error scenarios

## 🔗 Integration Testing

### Running Integration Tests

```bash
# Start test database
docker run -d --name test-postgres \
  -e POSTGRES_DB=test_db \
  -e POSTGRES_USER=test_user \
  -e POSTGRES_PASSWORD=test_password \
  -p 5432:5432 \
  postgres:15-alpine

# Run integration tests
DATABASE_URL=postgresql://test_user:test_password@localhost:5432/test_db \
pytest tests/integration/ -v

# Cleanup
docker stop test-postgres && docker rm test-postgres
```

### Integration Test Examples

#### Database Integration

```python
# tests/integration/test_database.py
import pytest
from database import db
from models.stream import Stream

class TestDatabaseIntegration:
    @pytest.fixture(autouse=True)
    def setup_database(self):
        """Set up test database."""
        db.create_all()
        yield
        db.drop_all()
    
    def test_stream_crud_operations(self):
        """Test complete CRUD operations for Stream."""
        # Create
        stream = Stream(name="Integration Test Stream")
        db.session.add(stream)
        db.session.commit()
        
        # Read
        retrieved = Stream.query.filter_by(name="Integration Test Stream").first()
        assert retrieved is not None
        assert retrieved.name == "Integration Test Stream"
        
        # Update
        retrieved.name = "Updated Stream"
        db.session.commit()
        
        updated = Stream.query.get(retrieved.id)
        assert updated.name == "Updated Stream"
        
        # Delete
        db.session.delete(updated)
        db.session.commit()
        
        deleted = Stream.query.get(retrieved.id)
        assert deleted is None
```

#### API Integration

```python
# tests/integration/test_api.py
import pytest
import requests
from app import create_app

class TestAPIIntegration:
    @pytest.fixture
    def client(self):
        """Create test client."""
        app = create_app('testing')
        return app.test_client()
    
    def test_health_endpoint_integration(self, client):
        """Test health endpoint with database."""
        response = client.get('/api/health/detailed')
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'checks' in data
        assert 'database' in data['checks']
```

## 🌐 End-to-End Testing

### Running E2E Tests

```bash
# Start full application stack
docker-compose up -d

# Wait for services
sleep 30

# Run E2E tests
pytest tests/e2e/ -v --tb=short

# Cleanup
docker-compose down
```

### E2E Test Examples

#### User Workflow Testing

```python
# tests/e2e/test_user_flows.py
import pytest
import requests
import time

class TestUserFlows:
    @pytest.fixture(scope="class")
    def base_url(self):
        return "http://localhost:5000"
    
    def test_complete_stream_setup_flow(self, base_url):
        """Test complete stream setup workflow."""
        # 1. Login (if authentication is enabled)
        login_response = requests.post(f"{base_url}/auth/login", data={
            'username': 'admin',
            'password': 'default-password'
        })
        assert login_response.status_code in [200, 302]
        
        # 2. Create stream
        stream_data = {
            'name': 'E2E Test Stream',
            'plugin_name': 'garmin_plugin',
            'config': '{"api_key": "test-key"}'
        }
        
        create_response = requests.post(
            f"{base_url}/api/streams",
            json=stream_data,
            cookies=login_response.cookies
        )
        assert create_response.status_code == 201
        
        stream_id = create_response.json()['id']
        
        # 3. Start stream
        start_response = requests.post(
            f"{base_url}/api/streams/{stream_id}/start",
            cookies=login_response.cookies
        )
        assert start_response.status_code == 200
        
        # 4. Verify stream status
        time.sleep(5)  # Allow stream to start
        
        status_response = requests.get(
            f"{base_url}/api/streams/{stream_id}",
            cookies=login_response.cookies
        )
        assert status_response.status_code == 200
        
        stream_data = status_response.json()
        assert stream_data['is_active'] is True
        
        # 5. Stop stream
        stop_response = requests.post(
            f"{base_url}/api/streams/{stream_id}/stop",
            cookies=login_response.cookies
        )
        assert stop_response.status_code == 200
        
        # 6. Delete stream
        delete_response = requests.delete(
            f"{base_url}/api/streams/{stream_id}",
            cookies=login_response.cookies
        )
        assert delete_response.status_code == 204
```

## ⚡ Performance Testing

### Running Performance Tests

```bash
# Install performance testing dependencies
pip install pytest-benchmark locust

# Run benchmark tests
pytest tests/performance/ -v --benchmark-only --benchmark-min-rounds=5

# Run load tests
locust -f tests/performance/load_tests.py --host=http://localhost:5000
```

### Performance Test Examples

#### Response Time Benchmarks

```python
# tests/performance/test_benchmarks.py
import pytest
import requests
import time

class TestPerformanceBenchmarks:
    @pytest.fixture
    def base_url(self):
        return "http://localhost:5000"
    
    def test_health_endpoint_performance(self, benchmark, base_url):
        """Benchmark health endpoint response time."""
        def health_check():
            response = requests.get(f"{base_url}/api/health")
            assert response.status_code == 200
            return response
        
        result = benchmark(health_check)
        
        # Assert response time is under 100ms
        assert benchmark.stats.mean < 0.1
    
    def test_api_endpoint_performance(self, benchmark, base_url):
        """Benchmark API endpoint performance."""
        def api_call():
            response = requests.get(f"{base_url}/api/streams")
            assert response.status_code in [200, 401]  # 401 if auth required
            return response
        
        result = benchmark(api_call)
        
        # Assert response time is under 500ms
        assert benchmark.stats.mean < 0.5
```

#### Load Testing

```python
# tests/performance/load_tests.py
from locust import HttpUser, task, between

class TrakBridgeUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        """Login if authentication is required."""
        response = self.client.post("/auth/login", data={
            "username": "admin",
            "password": "default-password"
        })
        
    @task(3)
    def health_check(self):
        """Test health endpoint load."""
        self.client.get("/api/health")
    
    @task(2)
    def list_streams(self):
        """Test stream listing load."""
        self.client.get("/api/streams")
    
    @task(1)
    def detailed_health(self):
        """Test detailed health endpoint load."""
        self.client.get("/api/health/detailed")
```

## 🔒 Security Testing

### Running Security Tests

```bash
# Run security tests
pytest tests/security/ -v

# Run comprehensive security scan
python tests/run_security_tests.py
```

### Security Test Examples

#### Authentication Testing

```python
# tests/security/test_auth.py
import pytest
import requests

class TestAuthenticationSecurity:
    @pytest.fixture
    def base_url(self):
        return "http://localhost:5000"
    
    def test_protected_endpoints_require_auth(self, base_url):
        """Test that protected endpoints require authentication."""
        protected_endpoints = [
            "/api/streams",
            "/api/tak-servers",
            "/admin"
        ]
        
        for endpoint in protected_endpoints:
            response = requests.get(f"{base_url}{endpoint}")
            assert response.status_code in [401, 302]  # Unauthorized or redirect
    
    def test_password_brute_force_protection(self, base_url):
        """Test protection against password brute force attacks."""
        # Attempt multiple failed logins
        for _ in range(10):
            response = requests.post(f"{base_url}/auth/login", data={
                'username': 'admin',
                'password': 'wrong-password'
            })
            
        # After multiple failures, should be rate limited
        final_response = requests.post(f"{base_url}/auth/login", data={
            'username': 'admin',
            'password': 'wrong-password'
        })
        
        assert final_response.status_code == 429  # Too Many Requests
```

#### Input Validation Testing

```python
# tests/security/test_validation.py
import pytest
import requests
import json

class TestInputValidation:
    @pytest.fixture
    def base_url(self):
        return "http://localhost:5000"
    
    def test_json_input_validation(self, base_url):
        """Test JSON input validation against injection attacks."""
        malicious_payloads = [
            '{"name": "test", "config": {"eval": "import os; os.system(\'rm -rf /\')"}}',
            '{"name": "' + 'A' * 10000 + '"}',  # Large input
            '{"name": "<script>alert(\'xss\')</script>"}',  # XSS attempt
        ]
        
        for payload in malicious_payloads:
            response = requests.post(
                f"{base_url}/api/streams",
                data=payload,
                headers={'Content-Type': 'application/json'}
            )
            
            # Should be rejected with 400 Bad Request
            assert response.status_code == 400
```

## 📊 Test Reporting

### Coverage Reports

```bash
# Generate HTML coverage report
pytest tests/ --cov=. --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Test Results

```bash
# Generate JUnit XML report
pytest tests/ --junitxml=test-results.xml

# Generate test summary
pytest tests/ --tb=line --q
```

### Continuous Integration

The CI/CD pipeline automatically:

1. Runs all test categories
2. Generates coverage reports
3. Creates test summaries
4. Comments results on pull requests
5. Fails builds if quality gates aren't met

## 🚀 Running Tests Locally

### Quick Test Run

```bash
# Run all tests with coverage
make test

# Or manually:
pytest tests/ -v --cov=. --cov-report=term-missing --cov-fail-under=75
```

### Development Testing

```bash
# Run tests in watch mode (requires pytest-watch)
ptw tests/ -- --cov=.

# Run specific test category
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest tests/e2e/ -v
```

### Docker Testing

```bash
# Run tests in Docker environment
docker-compose -f docker-compose.test.yml up --abort-on-container-exit

# Run specific test suite
docker-compose -f docker-compose.test.yml run --rm app pytest tests/unit/ -v
```

## 🔧 Test Configuration

### pytest.ini

```ini
[tool:pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = 
    --strict-markers
    --strict-config
    --verbose
    --tb=short
    --cov=app
    --cov=models
    --cov=services
    --cov-report=term-missing
    --cov-fail-under=75
markers =
    unit: Unit tests
    integration: Integration tests
    e2e: End-to-end tests
    performance: Performance tests
    security: Security tests
    slow: Slow running tests
```

### Environment Variables

```bash
# Test environment configuration
export FLASK_ENV=testing
export DATABASE_URL=sqlite:///:memory:
export SECRET_KEY=test-secret-key
export TRAKBRIDGE_ENCRYPTION_KEY=test-encryption-key-12345
```

## 📝 Test Writing Guidelines

### 1. Test Naming Convention

```python
def test_should_return_success_when_valid_input():
    """Test should clearly describe the expected behavior."""
    pass

def test_should_raise_exception_when_invalid_input():
    """Test should specify what exception is expected."""
    pass
```

### 2. Test Structure

```python
def test_example():
    # Arrange - Set up test data and conditions
    user = User(name="Test User")
    
    # Act - Execute the behavior being tested
    result = user.get_display_name()
    
    # Assert - Verify the expected outcome
    assert result == "Test User"
```

### 3. Test Data Management

```python
# Use fixtures for common test data
@pytest.fixture
def sample_stream():
    return Stream(
        name="Test Stream",
        plugin_name="test_plugin",
        config={"test": "value"}
    )

def test_with_fixture(sample_stream):
    assert sample_stream.name == "Test Stream"
```

### 4. Error Testing

```python
def test_should_handle_database_error():
    with pytest.raises(DatabaseError) as exc_info:
        service.create_invalid_record()
    
    assert "constraint violation" in str(exc_info.value)
```

## 🎯 Quality Metrics

### Coverage Targets

- **Overall Coverage:** 75% minimum
- **Critical Paths:** 90% minimum
- **New Code:** 80% minimum
- **Public APIs:** 100% required

### Performance Targets

- **Health Endpoint:** < 100ms response time
- **API Endpoints:** < 500ms response time
- **Database Queries:** < 200ms execution time
- **Page Load Time:** < 2 seconds

### Security Requirements

- **No Critical Vulnerabilities:** CVSS 9.0+ not allowed
- **Authentication:** All protected endpoints must require auth
- **Input Validation:** All user inputs must be validated
- **Secret Management:** No hardcoded secrets allowed

---

*For additional testing support, see the [Testing Best Practices](https://docs.pytest.org/en/stable/how.html) and [Flask Testing Documentation](https://flask.palletsprojects.com/en/2.0.x/testing/).*