# TrakBridge Performance Configuration

This document describes TrakBridge's performance configuration system implemented in Phase 1B of the scaling enhancement plan. The system provides configurable parallel processing with automatic fallback mechanisms for optimal performance and reliability.

## Overview

TrakBridge uses a comprehensive performance configuration system that allows fine-tuning of parallel processing behavior, fallback mechanisms, and monitoring capabilities. The system follows a hierarchical configuration approach with file-based settings, environment variable overrides, and runtime hot-reloading.

## Configuration File Structure

### Primary Configuration File
**Location**: `config/settings/performance.yaml`

```yaml
# TrakBridge Performance Configuration
# Phase 1B: Configuration & Fallbacks for Parallel Processing

parallel_processing:
  # Enable or disable parallel processing entirely
  enabled: true
  
  # Minimum number of locations to trigger parallel processing
  # Below this threshold, serial processing will be used
  batch_size_threshold: 10
  
  # Maximum number of concurrent tasks for parallel processing
  # Prevents overwhelming the system with too many simultaneous operations
  max_concurrent_tasks: 50
  
  # Automatically fallback to serial processing if parallel fails
  fallback_on_error: true
  
  # Processing timeout in seconds (0 = no timeout)
  processing_timeout: 30.0
  
  # Enable detailed performance logging
  enable_performance_logging: true

# Circuit breaker configuration for fault tolerance
circuit_breaker:
  # Number of consecutive failures before opening circuit
  failure_threshold: 3
  
  # Time to wait before attempting to close circuit (seconds)
  recovery_timeout: 60.0
  
  # Enable circuit breaker pattern
  enabled: true

# Performance monitoring and statistics
monitoring:
  # Track fallback statistics for alerting
  track_fallback_statistics: true
  
  # Maximum number of statistics entries to keep in memory
  max_statistics_entries: 1000
  
  # Reset statistics after this many seconds (0 = never reset)
  statistics_reset_interval: 3600
```

### Configuration Search Paths

The system searches for configuration files in the following order:

1. `config/settings/performance.yaml` (project default)
2. `/etc/trakbridge/performance.yaml` (system-wide)
3. `~/.trakbridge/performance.yaml` (user-specific)

The first found configuration file is used. If no file is found, sensible defaults are applied.

## Environment Variable Overrides

Configuration values can be overridden using environment variables with the `TRAKBRIDGE_` prefix:

```bash
# Override parallel processing settings
export TRAKBRIDGE_PARALLEL_ENABLED=true
export TRAKBRIDGE_BATCH_SIZE_THRESHOLD=25
export TRAKBRIDGE_MAX_CONCURRENT_TASKS=100
export TRAKBRIDGE_FALLBACK_ON_ERROR=true
export TRAKBRIDGE_PROCESSING_TIMEOUT=45.0

# Override circuit breaker settings
export TRAKBRIDGE_CIRCUIT_BREAKER_ENABLED=true
export TRAKBRIDGE_FAILURE_THRESHOLD=5
export TRAKBRIDGE_RECOVERY_TIMEOUT=120.0
```

Environment variables take precedence over file-based configuration.

## Performance Settings Details

### Parallel Processing Configuration

#### `enabled` (boolean, default: true)
- **Purpose**: Master switch for parallel processing
- **Impact**: When false, all processing uses serial mode regardless of dataset size
- **Use Case**: Disable during troubleshooting or resource constraints

#### `batch_size_threshold` (integer, default: 10)
- **Purpose**: Minimum number of locations required to trigger parallel processing
- **Impact**: Below this threshold, serial processing is used for efficiency
- **Tuning**: Lower values (5-10) for aggressive parallelization, higher values (20-50) for conservative approach

#### `max_concurrent_tasks` (integer, default: 50)
- **Purpose**: Limits simultaneous async operations to prevent resource exhaustion
- **Impact**: Higher values increase parallelism but consume more memory/connections
- **Tuning**: Based on system resources and network capacity

#### `fallback_on_error` (boolean, default: true)
- **Purpose**: Enables automatic fallback to serial processing on parallel failures
- **Impact**: Improves reliability at the cost of performance during failures
- **Use Case**: Disable only for testing or when failure investigation is needed

#### `processing_timeout` (float, default: 30.0)
- **Purpose**: Maximum time to wait for parallel processing completion
- **Impact**: Prevents indefinite blocking on slow operations
- **Tuning**: Adjust based on typical dataset sizes and network conditions

#### `enable_performance_logging` (boolean, default: true)
- **Purpose**: Controls detailed logging of performance metrics
- **Impact**: Provides insights but may impact performance with high verbosity
- **Use Case**: Enable during optimization, disable in production for performance

### Circuit Breaker Configuration

#### `enabled` (boolean, default: true)
- **Purpose**: Activates circuit breaker pattern for fault tolerance
- **Impact**: Prevents repeated attempts to failing parallel processing
- **Behavior**: Opens circuit after threshold failures, attempts recovery after timeout

#### `failure_threshold` (integer, default: 3)
- **Purpose**: Number of consecutive failures before opening circuit
- **Impact**: Lower values increase sensitivity, higher values tolerate more failures
- **Tuning**: Balance between responsiveness and tolerance

#### `recovery_timeout` (float, default: 60.0)
- **Purpose**: Time to wait before attempting to close circuit (seconds)
- **Impact**: Affects how quickly system attempts to recover from failures
- **Tuning**: Match to typical recovery times for infrastructure

### Monitoring Configuration

#### `track_fallback_statistics` (boolean, default: true)
- **Purpose**: Enables collection of fallback and performance statistics
- **Impact**: Provides monitoring data for alerting and analysis
- **Storage**: Statistics kept in memory, reset based on `statistics_reset_interval`

#### `max_statistics_entries` (integer, default: 1000)
- **Purpose**: Limits memory usage for statistics storage
- **Impact**: Older entries are discarded when limit is exceeded
- **Tuning**: Balance between memory usage and historical data retention

#### `statistics_reset_interval` (integer, default: 3600)
- **Purpose**: Automatic reset of statistics after specified seconds (0 = never reset)
- **Impact**: Prevents indefinite memory growth and provides fresh statistics
- **Use Case**: Set to 0 for long-running analysis, use intervals for operational monitoring

## Implementation Details

### Configuration Loading

The configuration system is implemented in `services/cot_service.py` within the `EnhancedCOTService` class:

```python
class EnhancedCOTService:
    def __init__(self, use_pytak: bool = True):
        # Initialize with default configuration
        self.parallel_config = self._get_default_performance_config()
        self.circuit_breaker_state = "closed"
        self.fallback_statistics = self._initialize_statistics()
        
        # Load configuration from file and environment
        self._load_performance_config()
```

### Configuration Methods

#### Loading Configuration
- `load_performance_config(config_path)`: Load from specific file
- `_load_performance_config()`: Load from search paths with environment overrides
- `load_performance_config_with_env_override()`: Apply environment variables
- `reload_performance_config(config_path)`: Hot reload configuration

#### Validation and Defaults
- `_get_default_performance_config()`: Provides sensible defaults
- `validate_performance_config(config)`: Validates and sanitizes configuration
- `get_config_file_search_paths()`: Returns configuration file search paths

#### Runtime Configuration
- `_choose_processing_method(locations)`: Decides between serial and parallel based on configuration
- `should_log_performance()`: Checks if performance logging is enabled

### Processing Decision Logic

```python
def _choose_processing_method(self, locations: List[Dict[str, Any]]) -> str:
    """Choose between serial and parallel processing based on configuration"""
    if not self.parallel_config.get('enabled', True):
        return "serial"
    
    if len(locations) < self.parallel_config.get('batch_size_threshold', 10):
        return "serial"
    
    if self.is_circuit_breaker_open():
        return "serial"
    
    return "parallel"
```

### Fallback Implementation

The fallback mechanism is implemented in `create_cot_events_with_fallback()`:

```python
async def create_cot_events_with_fallback(self, locations, cot_type, stale_time, cot_type_mode):
    """Create COT events with automatic fallback to serial processing"""
    if self._choose_processing_method(locations) == "serial":
        return await self._create_pytak_events(locations, cot_type, stale_time, cot_type_mode)
    
    try:
        # Attempt parallel processing with timeout
        timeout = self.parallel_config.get('processing_timeout', 30.0)
        if timeout > 0:
            result = await asyncio.wait_for(
                self._create_parallel_pytak_events(locations, cot_type, stale_time, cot_type_mode),
                timeout=timeout
            )
        else:
            result = await self._create_parallel_pytak_events(locations, cot_type, stale_time, cot_type_mode)
        
        # Record successful parallel processing
        self.record_successful_parallel_processing()
        return result
        
    except Exception as e:
        if not self.parallel_config.get('fallback_on_error', True):
            raise  # Re-raise if fallback is disabled
        
        # Record failure and attempt fallback
        error_type = "timeout" if isinstance(e, asyncio.TimeoutError) else "parallel_error"
        self.record_fallback_event(error_type, str(e))
        
        logger.warning(f"Parallel processing failed ({error_type}), falling back to serial processing: {e}")
        
        # Fallback to serial processing
        return await self._create_pytak_events(locations, cot_type, stale_time, cot_type_mode)
```

### Circuit Breaker Pattern

```python
def record_fallback_event(self, reason: str, error_message: str):
    """Record a fallback event for monitoring and circuit breaker logic"""
    self.fallback_statistics['total_fallbacks'] += 1
    self.fallback_statistics['consecutive_failures'] += 1
    self.fallback_statistics['last_failure_time'] = time.time()
    
    # Update circuit breaker state
    failure_threshold = self.parallel_config.get('circuit_breaker', {}).get('failure_threshold', 3)
    if self.fallback_statistics['consecutive_failures'] >= failure_threshold:
        self.circuit_breaker_state = "open"
        self.circuit_breaker_opened_time = time.time()
        logger.warning(f"Circuit breaker opened after {failure_threshold} consecutive failures")

def is_circuit_breaker_open(self) -> bool:
    """Check if circuit breaker is currently open"""
    if self.circuit_breaker_state != "open":
        return False
    
    # Check if recovery timeout has elapsed
    recovery_timeout = self.parallel_config.get('circuit_breaker', {}).get('recovery_timeout', 60.0)
    if time.time() - self.circuit_breaker_opened_time >= recovery_timeout:
        self.circuit_breaker_state = "half_open"
        logger.info("Circuit breaker entering half-open state for recovery attempt")
    
    return self.circuit_breaker_state == "open"
```

## Performance Monitoring

### Statistics Collection

The system tracks comprehensive statistics for monitoring and alerting:

```python
def _initialize_statistics(self) -> Dict[str, Any]:
    """Initialize performance statistics tracking"""
    return {
        'total_fallbacks': 0,
        'consecutive_failures': 0,
        'consecutive_successes': 0,
        'last_failure_time': 0,
        'last_success_time': 0,
        'fallback_reasons': {},
        'processing_times': [],
        'parallel_processing_healthy': True
    }

def get_fallback_statistics(self) -> Dict[str, Any]:
    """Get current fallback statistics for monitoring"""
    total_attempts = (self.fallback_statistics['total_fallbacks'] + 
                     self.fallback_statistics.get('total_successes', 0))
    
    fallback_rate = (self.fallback_statistics['total_fallbacks'] / total_attempts 
                    if total_attempts > 0 else 0.0)
    
    return {
        'total_fallbacks': self.fallback_statistics['total_fallbacks'],
        'fallback_rate': fallback_rate,
        'consecutive_failures': self.fallback_statistics['consecutive_failures'],
        'fallback_reasons': dict(self.fallback_statistics['fallback_reasons']),
        'circuit_breaker_state': self.circuit_breaker_state,
        'parallel_processing_healthy': self.is_parallel_processing_healthy()
    }
```

### Health Monitoring

```python
def is_parallel_processing_healthy(self) -> bool:
    """Determine if parallel processing is healthy based on recent statistics"""
    # Consider healthy if recent success rate is above threshold
    recent_failures = self.fallback_statistics['consecutive_failures']
    return recent_failures < self.parallel_config.get('circuit_breaker', {}).get('failure_threshold', 3)
```

## Performance Tuning Guidelines

### Small Datasets (1-10 locations)
```yaml
parallel_processing:
  enabled: true
  batch_size_threshold: 20  # Higher threshold to prefer serial for small datasets
  max_concurrent_tasks: 10  # Lower concurrency
```

### Medium Datasets (10-100 locations)
```yaml
parallel_processing:
  enabled: true
  batch_size_threshold: 10  # Standard threshold
  max_concurrent_tasks: 50  # Balanced concurrency
```

### Large Datasets (100+ locations)
```yaml
parallel_processing:
  enabled: true
  batch_size_threshold: 5   # Aggressive parallelization
  max_concurrent_tasks: 100 # High concurrency for throughput
  processing_timeout: 60.0  # Longer timeout for large datasets
```

### Production Environment
```yaml
parallel_processing:
  enabled: true
  enable_performance_logging: false  # Reduce log verbosity
  
circuit_breaker:
  failure_threshold: 5      # More tolerant of transient failures
  recovery_timeout: 300.0   # Longer recovery time
  
monitoring:
  statistics_reset_interval: 1800  # Reset every 30 minutes
```

### Development Environment
```yaml
parallel_processing:
  enabled: true
  enable_performance_logging: true   # Detailed logging for development
  
circuit_breaker:
  failure_threshold: 2       # Quick failure detection
  recovery_timeout: 30.0     # Fast recovery for testing
  
monitoring:
  statistics_reset_interval: 300  # Reset every 5 minutes for testing
```

## Troubleshooting

### Common Issues

#### Parallel Processing Not Activating
1. Check `enabled: true` in configuration
2. Verify dataset size exceeds `batch_size_threshold`
3. Check if circuit breaker is open: `is_circuit_breaker_open()`
4. Review logs for configuration loading errors

#### High Fallback Rate
1. Review `fallback_reasons` in statistics
2. Check network connectivity and latency
3. Adjust `processing_timeout` for slow operations
4. Consider reducing `max_concurrent_tasks`

#### Circuit Breaker Stuck Open
1. Check `recovery_timeout` setting (may be too long)
2. Review underlying infrastructure issues
3. Manually reset via configuration reload
4. Check `failure_threshold` (may be too sensitive)

### Diagnostic Commands

```bash
# Check current configuration
python -c "
from services.cot_service import EnhancedCOTService
service = EnhancedCOTService()
print('Configuration:', service.parallel_config)
print('Statistics:', service.get_fallback_statistics())
"

# Test configuration loading
python -c "
from services.cot_service import EnhancedCOTService
service = EnhancedCOTService()
config = service.load_performance_config('config/settings/performance.yaml')
print('Loaded config:', config)
"

# Validate environment overrides
python -c "
import os
os.environ['TRAKBRIDGE_PARALLEL_ENABLED'] = 'false'
from services.cot_service import EnhancedCOTService
service = EnhancedCOTService()
print('Parallel enabled:', service.parallel_config['enabled'])
"
```

## Migration and Upgrades

### Upgrading from Phase 1A to Phase 1B

Phase 1B is fully backward compatible with Phase 1A. No code changes are required, but you can optionally:

1. Create `config/settings/performance.yaml` to customize behavior
2. Set environment variables for specific deployments
3. Enable performance monitoring in production

### Configuration Validation

The system automatically validates configuration and provides defaults for missing values:

```python
def validate_performance_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and sanitize performance configuration"""
    defaults = self._get_default_performance_config()
    validated = defaults.copy()
    
    if isinstance(config.get('enabled'), bool):
        validated['enabled'] = config['enabled']
    
    if isinstance(config.get('batch_size_threshold'), int) and config['batch_size_threshold'] > 0:
        validated['batch_size_threshold'] = config['batch_size_threshold']
    
    # Additional validation...
    return validated
```

## Security Considerations

### Configuration File Security
- Ensure configuration files have appropriate permissions (644 or restrictive)
- Store sensitive settings in environment variables rather than files
- Use Docker Secrets for container deployments

### Environment Variable Security
- Prefix all variables with `TRAKBRIDGE_` to avoid conflicts
- Document all environment variables for deployment teams
- Use secure methods for setting environment variables in production

### Performance Impact Security
- `max_concurrent_tasks` prevents resource exhaustion attacks
- `processing_timeout` prevents indefinite resource consumption
- Circuit breaker prevents cascade failures

