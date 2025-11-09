#!/usr/bin/env python
"""Debug script to check migration status in Docker container"""

import sys
sys.path.insert(0, '/app')

from database import db
from config.environments import get_config
from flask import Flask
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

app = Flask(__name__)
config = get_config()
app.config.from_object(config)
db.init_app(app)

with app.app_context():
    with db.engine.connect() as connection:
        # Get current revision from database
        migration_ctx = MigrationContext.configure(connection)
        current_rev = migration_ctx.get_current_revision()

        # Get latest revision from migration files
        alembic_cfg = Config()
        alembic_cfg.set_main_option('script_location', 'migrations')
        script_dir = ScriptDirectory.from_config(alembic_cfg)
        latest_rev = script_dir.get_current_head()

        print("="*60)
        print("MIGRATION STATUS DEBUG")
        print("="*60)
        print(f"Database current revision: {current_rev}")
        print(f"Migration files HEAD:      {latest_rev}")
        print(f"Match:                     {current_rev == latest_rev}")
        print("="*60)

        if current_rev != latest_rev:
            print("\n⚠️  DATABASE NEEDS UPGRADE!")
            print(f"Need to upgrade from {current_rev} to {latest_rev}")
        else:
            print("\n✅ Database is up to date")
