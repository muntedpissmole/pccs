from gevent import monkey
monkey.patch_all()

from app import app, socketio, start_app

# Run your initialization once
start_app()

# This is what gunicorn will use
application = app