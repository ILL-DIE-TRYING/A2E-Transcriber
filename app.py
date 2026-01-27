from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager, login_required, current_user
import os
import logging
from datetime import datetime
import threading 
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import select
from sqlalchemy.orm import relationship 
from sqlalchemy import func

# Import all settings from the centralized config file
from config import (
    UPLOAD_FOLDER, TRANSCRIPT_FOLDER, REGISTRATION_ENABLED, 
    SECRET_KEY, DATABASE_URI, MAX_CONTENT_LENGTH, SERVER_PORT,
    DEBUG_MODE, MAX_WORKERS, DEFAULT_TRANSLATE_TO_EN
)

# Import routes and worker/cleanup functions
from routes import register_routes 

# Set up logger for this module
app_logger = logging.getLogger(__name__)

# --- App & DB Setup ---
app = Flask(__name__)

# --- Configuration (From config.py) ---
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['TRANSCRIPT_FOLDER'] = TRANSCRIPT_FOLDER
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SECRET_KEY'] = SECRET_KEY
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# 2. FLASK-LOGIN SETUP
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 
login_manager.login_message = "Please log in to access this page."


@login_manager.user_loader
def load_user(user_id):
    """Callback for Flask-Login to load a user from the ID."""
    return db.session.get(User, int(user_id))

# --- Database Models ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    
    # 1:M relationship with recordings
    recordings = relationship('Recording', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Recording(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # File-related fields
    original_filename = db.Column(db.String(255), nullable=False)
    filename = db.Column(db.String(255), unique=True, nullable=False)
    filesize = db.Column(db.Integer, nullable=False) 
    
    # Whisper configuration fields
    model_key = db.Column(db.String(50), nullable=False)
    translate_to_en = db.Column(db.Boolean, default=False)
    
    # Language detection fields
    language = db.Column(db.String(50), nullable=True, default=None)
    language_probability = db.Column(db.Float, nullable=True, default=None)

    # Status fields
    status = db.Column(db.String(50), default='pending', nullable=False)
    progress = db.Column(db.Float, default=0.0)
    transcript = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)
    uploaded_at = db.Column(db.DateTime(timezone=True), default=func.now(), nullable=False)
    
    # Processing time tracking
    processing_started_at = db.Column(db.DateTime(timezone=True), nullable=True, default=None)
    processing_duration = db.Column(db.Float, nullable=True, default=None)  # Duration in seconds
    
    def __repr__(self):
        return f'<Recording {self.id} - {self.status}>'

# --- Application Initialization ---

# 4. Register Routes
register_routes(app, db, User, Recording)
app_logger.debug("Routes registration complete.")


with app.app_context():
    app_logger.info("Checking database schema and creating tables if necessary...")
    db.create_all() 
    app_logger.info("Database initialization complete.")
    
    # 6. Import worker monitor and start the thread
    try:
        from whisper_worker import queue_monitor
        
        app_logger.info("Starting worker queue monitor thread...")
        monitor_thread = threading.Thread(
            target=queue_monitor, 
            args=(app, db, Recording, MAX_WORKERS),
            daemon=True,
            name="QueueMonitorThread"
        )
        monitor_thread.start()
        app_logger.info(f"Worker queue monitor started with max_workers={MAX_WORKERS}.")
        
    except ImportError:
        app_logger.error("Could not import queue_monitor from whisper_worker. Check whisper_worker.py.")
    except Exception as e:
        app_logger.critical(f"Failed to start queue monitor thread: {e}")


if __name__ == '__main__':
    app_logger.info(f"Starting Flask app on http://0.0.0.0:{SERVER_PORT}")
    app.run(host='0.0.0.0', port=SERVER_PORT, debug=DEBUG_MODE, use_reloader=False)
