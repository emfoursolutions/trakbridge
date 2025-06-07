# =============================================================================
# config.py - Application Configuration (Enhanced for Multi-threading)
# =============================================================================

import os
from urllib.parse import quote_plus


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'

    # Database configuration
    DB_TYPE = os.environ.get('DB_TYPE', 'sqlite').lower()

    if DB_TYPE == 'sqlite':
        SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
                                  'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app.db')

        # SQLite-specific engine options for thread safety
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': True,
            'pool_recycle': 300,
            'connect_args': {
                'check_same_thread': False,  # Allow SQLite to be used across threads
                'timeout': 20
            }
        }

    elif DB_TYPE == 'mysql':
        DB_USER = os.environ.get('DB_USER', 'root')
        DB_PASSWORD = quote_plus(os.environ.get('DB_PASSWORD', ''))
        DB_HOST = os.environ.get('DB_HOST', 'localhost')
        DB_PORT = os.environ.get('DB_PORT', '3306')
        DB_NAME = os.environ.get('DB_NAME', 'gps_tak_app')
        SQLALCHEMY_DATABASE_URI = f'mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4'

        # MySQL-specific engine options
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': True,
            'pool_recycle': 3600,  # Recycle connections every hour
            'pool_size': 20,
            'max_overflow': 30,
            'pool_timeout': 30,
            'connect_args': {
                'connect_timeout': 60,
                'read_timeout': 30,
                'write_timeout': 30
            }
        }

    elif DB_TYPE == 'postgresql':
        DB_USER = os.environ.get('DB_USER', 'postgres')
        DB_PASSWORD = quote_plus(os.environ.get('DB_PASSWORD', ''))
        DB_HOST = os.environ.get('DB_HOST', 'localhost')
        DB_PORT = os.environ.get('DB_PORT', '5432')
        DB_NAME = os.environ.get('DB_NAME', 'gps_tak_app')
        SQLALCHEMY_DATABASE_URI = f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'

        # PostgreSQL-specific engine options
        SQLALCHEMY_ENGINE_OPTIONS = {
            'pool_pre_ping': True,
            'pool_recycle': 3600,  # Recycle connections every hour
            'pool_size': 20,
            'max_overflow': 30,
            'pool_timeout': 30,
            'connect_args': {
                'connect_timeout': 10,
                'application_name': 'GPS_TAK_App'
            }
        }

    # SQLAlchemy general settings
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_RECORD_QUERIES = os.environ.get('SQLALCHEMY_RECORD_QUERIES', 'False').lower() == 'true'

    # Session configuration for thread safety
    SQLALCHEMY_SESSION_OPTIONS = {
        'autoflush': True,
        'autocommit': False,
        'expire_on_commit': True  # Important for cross-thread access
    }

    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'DEBUG')
    LOG_DIR = os.environ.get('LOG_DIR', 'logs')

    # Thread pool configuration
    MAX_WORKER_THREADS = int(os.environ.get('MAX_WORKER_THREADS', '4'))
    ASYNC_TIMEOUT = int(os.environ.get('ASYNC_TIMEOUT', '60'))

    # Stream management settings
    DEFAULT_POLL_INTERVAL = int(os.environ.get('DEFAULT_POLL_INTERVAL', '120'))
    MAX_CONCURRENT_STREAMS = int(os.environ.get('MAX_CONCURRENT_STREAMS', '50'))

    # HTTP client settings for GPS providers
    HTTP_TIMEOUT = int(os.environ.get('HTTP_TIMEOUT', '30'))
    HTTP_MAX_CONNECTIONS = int(os.environ.get('HTTP_MAX_CONNECTIONS', '100'))
    HTTP_MAX_CONNECTIONS_PER_HOST = int(os.environ.get('HTTP_MAX_CONNECTIONS_PER_HOST', '10'))


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_RECORD_QUERIES = True
    LOG_LEVEL = 'DEBUG'


class ProductionConfig(Config):
    DEBUG = False

    # Enhanced production database settings
    if Config.DB_TYPE == 'sqlite':
        # SQLite not recommended for production, but if used:
        SQLALCHEMY_ENGINE_OPTIONS = {
            **Config.SQLALCHEMY_ENGINE_OPTIONS,
            'connect_args': {
                **Config.SQLALCHEMY_ENGINE_OPTIONS['connect_args'],
                'timeout': 30
            }
        }
    else:
        # Enhanced settings for production databases
        SQLALCHEMY_ENGINE_OPTIONS = {
            **Config.SQLALCHEMY_ENGINE_OPTIONS,
            'pool_size': 50,
            'max_overflow': 100,
            'pool_timeout': 60,
        }

    # Production-specific settings
    MAX_WORKER_THREADS = int(os.environ.get('MAX_WORKER_THREADS', '8'))
    MAX_CONCURRENT_STREAMS = int(os.environ.get('MAX_CONCURRENT_STREAMS', '200'))


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

    # Simplified settings for testing
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': False,
        'connect_args': {'check_same_thread': False}
    }

    MAX_WORKER_THREADS = 2
    MAX_CONCURRENT_STREAMS = 5


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}