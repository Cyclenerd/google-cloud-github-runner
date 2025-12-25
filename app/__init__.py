"""
Flask application factory and root routes.
"""
import logging
import os
import secrets
from flask import Flask, render_template, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60 per hour"],
    storage_uri='memory://',
    headers_enabled=True,  # Return X-RateLimit-* headers
)


def create_app():
    """Application factory pattern for creating Flask app."""
    app = Flask(__name__, template_folder='templates')

    # Configure secret key for sessions
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))

    # Disable debug mode in production
    app.config['DEBUG'] = False
    app.config['TESTING'] = False

    # Security configurations
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour
    app.config['MAX_CONTENT_LENGTH'] = 64 * 1024  # 64 KB

    # Initialize rate limiter
    limiter.init_app(app)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Root route
    @app.route('/')
    def index():
        """Serve the index page."""
        return render_template('index.html')

    @app.route('/robots.txt')
    def robots():
        """Serve robots.txt file."""
        return send_from_directory(os.path.join(app.root_path, 'static'), 'robots.txt', mimetype='text/plain')

    @app.route('/favicon.ico')
    def favicon():
        """Serve favicon.ico file."""
        icon_path = os.path.join(app.root_path, 'static', 'img')
        return send_from_directory(icon_path, 'favicon.ico', mimetype='image/vnd.microsoft.icon')

    # Register blueprints
    from app.routes.setup import setup_bp
    from app.routes.webhook import webhook_bp

    app.register_blueprint(setup_bp)
    app.register_blueprint(webhook_bp)

    return app
