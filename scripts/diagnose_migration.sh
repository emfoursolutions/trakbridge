#!/bin/bash
# Migration Diagnostic Script for Docker

echo "=== TrakBridge Migration Diagnostic ==="
echo ""

echo "1. Checking local migration files..."
echo "   Migrations directory:"
ls -la migrations/versions/*.py | tail -5

echo ""
echo "2. Current Alembic head:"
python -c "
from alembic.config import Config
from alembic.script import ScriptDirectory

cfg = Config()
cfg.set_main_option('script_location', 'migrations')
script_dir = ScriptDirectory.from_config(cfg)
print(f'   HEAD: {script_dir.get_current_head()}')
"

echo ""
echo "3. Team member migration status:"
if [ -f "migrations/versions/add_team_member_fields_to_callsign_mappings.py" ]; then
    echo "   ✅ Migration file exists locally"
    grep "revision =" migrations/versions/add_team_member_fields_to_callsign_mappings.py | head -1
else
    echo "   ❌ Migration file NOT found locally"
fi

echo ""
echo "4. Checking if migration is in Docker image..."
echo "   Run this command to check inside running container:"
echo "   docker exec <container_name> ls -la /app/migrations/versions/add_team_member*"

echo ""
echo "5. Check database current revision..."
echo "   Run this to see current DB revision:"
echo "   docker exec <container_name> flask db current"

echo ""
echo "6. Check migration history:"
echo "   docker exec <container_name> flask db history | head -20"

echo ""
echo "=== Recommendations ==="
echo ""
echo "If migration file is missing from Docker image:"
echo "  1. Check .dockerignore doesn't exclude migrations/"
echo "  2. Rebuild Docker image: docker build -t emfoursolutions/trakbridge:v1.1.0 ."
echo "  3. Push to registry: docker push emfoursolutions/trakbridge:v1.1.0"
echo ""
echo "If migration file exists but not applied:"
echo "  1. Check current revision: docker exec <container> flask db current"
echo "  2. Run upgrade: docker exec <container> flask db upgrade"
echo "  3. Or restart container (migrations run on startup)"
