# wsgi.py - This file should be at the same level as your app.py
import os

# Force early monkey patching before ANY other imports
if os.environ.get('GUNICORN_WORKER_CLASS', 'gevent') == 'gevent':
    from gevent import monkey
    monkey.patch_all(ssl=True, socket=True, dns=True, time=True, select=True, thread=True, os=True, signal=True, subprocess=True, sys=False, builtins=True, aggressive=True)

# Now import your app
from app import app  # noqa: E402

# Export for gunicorn
application = app

if __name__ == "__main__":
    app.run()