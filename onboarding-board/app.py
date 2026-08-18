"""Client Onboarding Board — internal ops dashboard for Excelsior Franchise Solutions.

Tracks every client from onboarding forms through to fully live, fed by a
GoHighLevel webhook. Runs as its own service so it stays separate from anything
client-facing.
"""

import os
import secrets
from datetime import timedelta

from flask import Flask, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

import db
from onboarding import bp as onboarding_bp

app = Flask(__name__)

# Railway terminates TLS at its edge and forwards plain http, so without this
# the app thinks every request is insecure and builds http:// URLs — including
# the webhook URL shown on the board, which carries the shared secret.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Cookies are marked Secure and SameSite=None so the board still works if it is
# ever embedded in an iframe; set DEV_INSECURE_COOKIES=1 to sign in over plain
# http while testing locally.
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
_dev_cookies = os.environ.get('DEV_INSECURE_COOKIES') == '1'
app.config.update(
    SESSION_COOKIE_SAMESITE='Lax' if _dev_cookies else 'None',
    SESSION_COOKIE_SECURE=not _dev_cookies,
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

app.register_blueprint(onboarding_bp)
db.init_db()


@app.route('/')
def home():
    """The board is the whole app here, so the root is just the board."""
    return redirect(url_for('onboarding.dashboard'))


@app.route('/health')
def health():
    return {'ok': True, 'clients': len(db.list_clients(include_archived=True))}


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
