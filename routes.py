import os
import stat
import time
import threading
import logging
from flask import request, redirect, url_for, render_template, flash, jsonify, send_from_directory, current_app, Response
from werkzeug.utils import secure_filename
from datetime import datetime, timezone as dt_timezone
import json
from zoneinfo import ZoneInfo
from markupsafe import Markup
from sqlalchemy import select
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# Set up logger for this module
routes_logger = logging.getLogger(__name__)

# Import cleanup and config
from clean_zombies import clean_zombie_entries
from config import (
    UPLOAD_FOLDER, TRANSCRIPT_FOLDER, ALLOWED_EXTENSIONS, 
    AVAILABLE_MODELS, WHISPER_UI_MODELS, DEFAULT_MODEL_KEY, 
    REGISTRATION_ENABLED, DEFAULT_TRANSLATE_TO_EN, MAX_WORKERS,
    DEBUG_MODE
)

# --- Decorators ---
def check_registration_enabled(f):
    """Decorator to block registration if disabled in config."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not REGISTRATION_ENABLED:
            flash("User registration is currently disabled by the administrator.", 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Helpers (Jinja Filters) ---
def format_datetime(value, format_string='%Y-%m-%d %H:%M'):
    """Formats a datetime object to a string. This is registered as a Jinja filter."""
    if value is None:
        return ""
    # Assuming the database stores UTC, this returns the UTC time in the desired format
    return value.strftime(format_string)

def file_size_format(value, suffix='B'):
    """
    Formats a file size (in bytes) to a human-readable string (e.g., 1.2 MB).
    This is registered as a Jinja filter.
    """
    if value is None:
        return 'N/A'
        
    value = float(value)
    
    for unit in ['', 'K', 'M', 'G', 'T', 'P', 'E', 'Z']:
        if abs(value) < 1024.0:
            return f"{value:3.1f} {unit}{suffix}"
        value /= 1024.0
        
    return f"{value:.1f} Y{suffix}"
    

# --- New Filter Definition ---
def word_break_text(value):
    """
    Inserts a zero-width space (&#x200b;) into very long words to allow them 
    to wrap gracefully on small screens without breaking the layout.
    """
    if value is None:
        return ""
    
    # NOTE: You must have 'import re' at the top of routes.py for this to work.
    import re 
    
    # Insert a zero-width space after every 10 non-whitespace characters
    return re.sub(r'(\S{10})(?=\S)', r'\1&#x200b;', str(value), flags=re.MULTILINE)
# --- End New Filter Definition ---


def allowed_file(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- View Functions ---

# /register
def register(db, User):
    if not REGISTRATION_ENABLED:
        # This case is primarily handled by the decorator, but good to have a final check
        flash("User registration is currently disabled.", 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Basic validation
        if not username or not password:
            flash('Both username and password are required.', 'error')
            return redirect(url_for('register'))

        # Check if user already exists
        if db.session.execute(db.select(User).filter_by(username=username)).first():
            flash('Username already taken.', 'error')
            return redirect(url_for('register'))

        # Create new user
        new_user = User(username=username)
        new_user.set_password(password)
        
        # Default first user as admin if table is empty, otherwise regular user
        is_first_user = not db.session.execute(db.select(User)).first()
        if is_first_user:
             new_user.is_admin = True
             routes_logger.warning(f"First user created: {username}. Automatically granted Admin rights.")

        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful. Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            routes_logger.error(f"Database error during registration: {e}")
            flash('A database error occurred during registration.', 'error')
            return redirect(url_for('register'))

    return render_template('register.html', registration_enabled=REGISTRATION_ENABLED)

# /login
def login(db, User):
    if current_user.is_authenticated:
        return redirect(url_for('upload_and_list'))
        
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none()

        if user is None or not user.check_password(password):
            flash('Invalid username or password.', 'error')
            return redirect(url_for('login'))
        
        # Log the user in
        login_user(user)
        routes_logger.info(f"User logged in: {user.username}")
        # Redirect to the page they were trying to access, or the main page
        next_page = request.args.get('next')
        return redirect(next_page or url_for('upload_and_list'))

    return render_template('login.html', registration_enabled=REGISTRATION_ENABLED)

# /logout
@login_required
def logout():
    routes_logger.info(f"User logged out: {current_user.username}")
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))
    
    
# In routes.py
# Make sure you have imported all necessary items at the top, including:
# from config import WHISPER_UI_MODELS 
# from flask_login import current_user, login_required
# from sqlalchemy import select
# from flask import request, redirect, url_for, flash

# In /home/burd/PROJECTS/transcriber2/routes.py

# In /home/burd/PROJECTS/transcriber2/routes.py

@login_required
def re_process(db, Recording, rec_id):
    """
    Resets a recording's status to 'pending' to re-queue it for processing,
    and updates the model/translation settings from the re-process modal.
    """
    routes_logger.info(f"User {current_user.id} requested re-process for Recording ID: {rec_id}")
    
    # 1. Use select() to fetch the recording, ensuring user ownership
    recording = db.session.execute(
        select(Recording).filter_by(id=rec_id, user_id=current_user.id)
    ).scalar_one_or_none()

    if not recording:
        flash("Error: Recording not found or you do not have permission.", 'error')
        return redirect(url_for('upload_and_list'))

    # Check if the file still exists before re-queuing
    input_file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], recording.filename)
    if not os.path.exists(input_file_path):
        flash(f"Error: Original audio file for {recording.original_filename} is missing. Cannot re-process.", 'error')
        if recording.status != 'error':
            recording.status = 'error'
            recording.transcript = "Original audio file missing. Re-process aborted."
            db.session.commit()
        return redirect(url_for('upload_and_list'))

    try:
        # 2. CORRECTED EXTRACTION: Use the actual form field names from the log
        # Raw log shows: ('model', 'base')
        new_model_key = request.form.get('model')
        
        # Raw log shows: ('translate', '1'). We check for key presence.
        new_translate = 'translate' in request.form 
        
        if DEBUG_MODE:
            routes_logger.debug(f"DEBUG: Extracted values (Corrected): model={new_model_key}, translate={new_translate}")

        # 3. Update the database record with new parameters
        # Note: AVAILABLE_MODELS is imported from config.py
        if new_model_key and new_model_key in AVAILABLE_MODELS:
            recording.model_key = new_model_key
        # Else: if the form value is invalid or missing, we keep the existing model_key.
        
        recording.translate_to_en = new_translate 

        # 4. Reset status to re-queue the job
        recording.status = 'pending'
        recording.progress = 0.0
        recording.transcript = None  
        recording.language = None    
        recording.started_at = None  

        db.session.commit()
        
        flash(f"Job for {recording.original_filename} has been successfully re-queued with model: '{recording.model_key}' (Translate: {'Yes' if recording.translate_to_en else 'No'}).", 'success')
    
    except Exception as e:
        db.session.rollback()
        routes_logger.error(f"Failed to re-process recording ID {rec_id}: {e}", exc_info=True)
        flash("Database error during re-processing. Changes were rolled back.", 'error')

    return redirect(url_for('upload_and_list'))


# / (upload and list)
@login_required
def upload_and_list(db, Recording):
    # Only allow uploads via POST request
    if request.method == 'POST':
        # 1. Check if a file part is present
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        
        # 2. Check if filename is empty
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)

        # 3. Check for file extension and max size
        if not allowed_file(file.filename):
            flash(f"File type not allowed. Must be one of: {', '.join(ALLOWED_EXTENSIONS)}", 'error')
            return redirect(request.url)
        
        # Get form data for model/translation settings
        model_key = request.form.get('model_key')
        translate_to_en = bool(request.form.get('translate_to_en')) # Checkbox returns 'on' or None
        
        if model_key not in WHISPER_UI_MODELS:
            flash('Invalid model selected.', 'error')
            return redirect(request.url)
            
        try:
        
            # --- CRITICAL FIX: Define the missing variable ---
            original_filename = file.filename

            # --- CRITICAL MISSING LOGIC START ---
            # 1. Generate a secure and unique filename
            # os.path.splitext splits the file into (name, .ext)
            filename_base, ext = os.path.splitext(secure_filename(file.filename)) 
            timestamp = str(int(time.time()))
            
            # Assuming current_user is available and has an 'id' attribute
            user_id_str = str(current_user.id) 
            
            # Generate a unique hex part (8 characters)
            unique_id = os.urandom(4).hex() 

            # **This line defines safe_filename and was missing:**
            safe_filename = f"{user_id_str}_{timestamp}_{unique_id}{ext.lower()}"
            
            # Define the full path where the file will be saved
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename)

            # 2. Save the file to disk
            file.save(file_path)
            file_size = os.path.getsize(file_path)
            # --- CRITICAL MISSING LOGIC END ---
            
            # 5. Create DB entry
            new_recording = Recording(
                user_id=current_user.id,
                original_filename=file.filename,
                filename=safe_filename,
                filesize=file_size,
                status='pending',
                   # FIX #1: Correctly set created_at as a timezone-aware UTC datetime
                created_at=datetime.now(dt_timezone.utc), 
                 # FIX #2: Correctly set uploaded_at as a timezone-aware UTC datetime
                uploaded_at=datetime.now(dt_timezone.utc),
                model_key=model_key,
                translate_to_en=translate_to_en
            )
            
            db.session.add(new_recording)
            db.session.commit()
            flash(f'File "{original_filename}" uploaded and transcription job created (ID: {new_recording.id}).', 'success')
            routes_logger.info(f"User {current_user.id} uploaded file: {safe_filename} with model {model_key} and translate={translate_to_en}")
            
        except Exception as e:
            db.session.rollback()
            routes_logger.error(f"File upload/DB save failed: {e}")
            flash(f"Failed to process file upload: {e}", 'error')
            
            # Attempt to clean up the file if it was partially saved
            if 'file_path' in locals() and os.path.exists(file_path):
                 try:
                    os.remove(file_path)
                    routes_logger.warning(f"Cleaned up partially saved file: {safe_filename}")
                 except Exception as clean_e:
                    routes_logger.error(f"Failed to cleanup file {safe_filename}: {clean_e}")

        return redirect(url_for('upload_and_list'))

    # GET request: Query and display recordings
    try:
        # Since this function is @login_required, current_user.is_authenticated is implicitly true.
        recordings = db.session.execute(
            db.select(Recording)
            .filter_by(user_id=current_user.id)
            .order_by(Recording.id.desc())
        ).scalars().all()
            
    except Exception as e:
        routes_logger.error(f"Database query failed in upload_and_list: {e}")
        flash("Could not retrieve recordings from the database.", 'error')
        recordings = []

    # Pass the model dictionary and default settings to the template
    return render_template(
        'index.html',
        recordings=recordings,
        available_models=WHISPER_UI_MODELS,
        default_model=DEFAULT_MODEL_KEY,
        whisper_ui_models=WHISPER_UI_MODELS, 
        default_model_key=DEFAULT_MODEL_KEY,
        default_translate_to_en=DEFAULT_TRANSLATE_TO_EN
    )

# /status/<rec_id>
@login_required
def get_status(db, Recording, rec_id):
    """
    Returns the status of a recording as JSON, used for dashboard polling.
    """
    recording = db.session.get(Recording, rec_id)

    # Check if recording exists and belongs to the current user
    if not recording or recording.user_id != current_user.id:
        # Don't give away information about other users' IDs
        return jsonify({'status': 'not_found'}), 404

    if recording:
        # FIX: Added language and language_probability to the JSON response
        return jsonify({
            'id': recording.id,
            'status': recording.status,
            'model_key': recording.model_key,
            'translate_to_en': recording.translate_to_en,
            'progress': recording.progress,
            'created_at': recording.created_at.isoformat(),
            'updated_at': recording.updated_at.isoformat(),
            'language': recording.language, 
            'language_probability': recording.language_probability, 
        })
    
    return jsonify({'status': 'not_found'}), 404


# /transcript/<rec_id>
@login_required
def transcript(db, Recording, rec_id):
    """Displays the full transcript or error message."""
    recording = db.session.get(Recording, rec_id)

    if not recording or recording.user_id != current_user.id:
        flash("Recording not found or you do not have permission to view it.", 'error')
        return redirect(url_for('upload_and_list'))

    # Check if audio file still exists to offer download link
    audio_file_exists = os.path.exists(os.path.join(UPLOAD_FOLDER, recording.filename))
    
    # Format the transcript for display: replace newlines with HTML breaks
    # This prevents the raw text from running together without <br> tags
    transcript_display = Markup(recording.transcript.replace('\n', '<br>') if recording.transcript else "")

    return render_template(
        'transcript.html',
        recording=recording,
        transcript_display=transcript_display,
        audio_file_exists=audio_file_exists,
        WHISPER_UI_MODELS=WHISPER_UI_MODELS
    )


# /audio/<rec_id>
@login_required
def serve_audio(db, Recording, rec_id):
    """Serves the original uploaded audio file."""
    recording = db.session.get(Recording, rec_id)

    if not recording or recording.user_id != current_user.id:
        flash("Audio file not found or you do not have permission to access it.", 'error')
        return redirect(url_for('upload_and_list'))
    
    file_path = os.path.join(UPLOAD_FOLDER, recording.filename)
    if not os.path.exists(file_path):
        flash("Original audio file has been deleted.", 'error')
        return redirect(url_for('upload_and_list'))
        
    try:
        # send_from_directory will handle proper MIME type and chunking
        return send_from_directory(
            UPLOAD_FOLDER, 
            recording.filename, 
            as_attachment=False,
            mimetype=f'audio/{recording.filename.rsplit(".", 1)[1]}' # A guess, may need refinement
        )
    except Exception as e:
        routes_logger.error(f"Error serving audio file {recording.filename}: {e}")
        flash("Could not serve audio file.", 'error')
        return redirect(url_for('upload_and_list'))


# /download/<rec_id>
@login_required
def download_transcript(db, Recording, rec_id):
    """Downloads the transcript as a plain text file."""
    recording = db.session.get(Recording, rec_id)

    if not recording or recording.user_id != current_user.id or recording.status != 'done':
        flash("Transcript not ready or you do not have permission to download it.", 'error')
        return redirect(url_for('upload_and_list'))

    base_filename = os.path.splitext(recording.filename)[0]
    transcript_filename = f"{base_filename}.txt"
    transcript_path = os.path.join(TRANSCRIPT_FOLDER, transcript_filename)
    
    if not os.path.exists(transcript_path):
        # Fallback: create the file on the fly from the DB content if the file is missing but DB status is 'done'
        if recording.transcript:
            return Response(
                recording.transcript,
                mimetype='text/plain',
                headers={'Content-disposition': f'attachment; filename={os.path.splitext(recording.original_filename)[0]}_transcript.txt'}
            )
        else:
            flash("Transcript file not found and no content in database.", 'error')
            return redirect(url_for('upload_and_list'))

    # Serve the file from the disk
    try:
        # send_from_directory handles setting Content-Type and Content-Disposition headers for download
        return send_from_directory(
            TRANSCRIPT_FOLDER, 
            transcript_filename, 
            as_attachment=True,
            download_name=f"{os.path.splitext(recording.original_filename)[0]}_transcript.txt"
        )
    except Exception as e:
        routes_logger.error(f"Error serving transcript file {transcript_filename}: {e}")
        flash("Could not download transcript file.", 'error')
        return redirect(url_for('upload_and_list'))

# In /home/burd/PROJECTS/transcriber2/routes.py

# ... (Insert this function definition here) ...

# In /home/burd/PROJECTS/transcriber2/routes.py

# In /home/burd/PROJECTS/transcriber2/routes.py

@login_required
def delete_recording(db, Recording, rec_id):
    """Deletes a recording, its audio file, and its transcript file."""
    
    # The Debugging steps are now wrapped in an if DEBUG_MODE: block
    if DEBUG_MODE:
        routes_logger.info(f"DEBUG: Entering delete_recording function for REC-ID: {rec_id}")
        routes_logger.debug(f"DEBUG: Request Method is {request.method}")
        routes_logger.debug(f"DEBUG: Received Form Data: {request.form}")
    
    recording = db.session.get(Recording, rec_id)

    if not recording:
        flash("Recording not found.", 'error')
        if DEBUG_MODE:
            routes_logger.warning(f"DEBUG: Delete failed. Recording ID {rec_id} not found.")
        return redirect(url_for('upload_and_list'))
    
    # 1. Check ownership (SECURITY CRITICAL)
    if recording.user_id != current_user.id:
        flash("You do not have permission to delete this file.", 'error')
        if DEBUG_MODE:
            routes_logger.warning(f"DEBUG: Delete failed. User {current_user.id} unauthorized for REC-ID {rec_id}.")
        return redirect(url_for('upload_and_list'))

    # 2. Delete files from the file system
    try:
        audio_path = os.path.join(current_app.config['UPLOAD_FOLDER'], recording.filename)
        transcript_path = os.path.join(current_app.config['TRANSCRIPT_FOLDER'], f"{os.path.splitext(recording.filename)[0]}.txt")

        # Delete audio file
        if os.path.exists(audio_path):
            os.remove(audio_path)
            routes_logger.info(f"Deleted audio file: {audio_path}")

        # Delete transcript file
        if os.path.exists(transcript_path):
            os.remove(transcript_path)
            routes_logger.info(f"Deleted transcript file: {transcript_path}")
        else:
            routes_logger.info(f"Transcript file not found/already deleted: {transcript_path}")

    except Exception as e:
        routes_logger.error(f"Error deleting files for REC-{rec_id}: {e}", exc_info=True)
        # Continue to delete DB record even if files are partially missing/deleted

    # 3. Delete record from database
    try:
        db.session.delete(recording)
        db.session.commit()
        flash(f"Recording '{recording.original_filename}' and associated files successfully deleted.", 'success')
        if DEBUG_MODE:
            routes_logger.info(f"DEBUG: Successfully deleted DB record for REC-ID {rec_id}.")
    except Exception as e:
        db.session.rollback()
        routes_logger.error(f"Error deleting database record for REC-{rec_id}: {e}", exc_info=True)
        flash("Database error during deletion. Please check logs.", 'error')

    return redirect(url_for('upload_and_list'))


# /admin/cleanup (Admin only route for cleanup)
@login_required
def admin_cleanup(app_context, db, Recording):
    """Runs the zombie cleanup function."""
    if not current_user.is_admin:
        flash("Access denied: You must be an administrator to perform this action.", 'error')
        return redirect(url_for('upload_and_list'))
        
    # clean_zombie_entries handles all its own flashing and logging
    clean_count = clean_zombie_entries(app_context, db, Recording, UPLOAD_FOLDER, TRANSCRIPT_FOLDER)
    
    return redirect(url_for('upload_and_list'))


# --- Route Registration Function ---
def register_routes(app, db, User, Recording):
    """Registers all Flask routes and Jinja filters."""
    # 1. Jinja Filters (Must be registered before the app starts handling requests)
    app.jinja_env.filters['format_datetime'] = format_datetime
    app.jinja_env.filters['file_size_format'] = file_size_format
    app.jinja_env.filters['word_break_text'] = word_break_text
    
    # 2. Authentication Routes
    # The register function uses a decorator to check the enabled status
    app.add_url_rule("/register", view_func=check_registration_enabled(lambda: register(db, User)), endpoint="register", methods=['GET', 'POST'])
    app.add_url_rule("/login", view_func=lambda: login(db, User), endpoint="login", methods=['GET', 'POST'])
    app.add_url_rule("/logout", view_func=logout, endpoint="logout")

    # 3. Main Application Routes
    app.add_url_rule(
        "/", 
        view_func=lambda: upload_and_list(db, Recording), 
        endpoint="upload_and_list", 
        methods=['GET', 'POST']
    )
    app.add_url_rule(
        "/reprocess/<int:rec_id>", 
        view_func=login_required(lambda rec_id: re_process(db, Recording, rec_id)), 
        endpoint="re_process", 
        methods=['POST']
    )
    app.add_url_rule(
        "/delete/<int:rec_id>", 
        view_func=login_required(lambda rec_id: delete_recording(db, Recording, rec_id)), 
        endpoint="delete_recording", 
        methods=['POST']
    )
    app.add_url_rule("/status/<int:rec_id>", view_func=lambda rec_id: get_status(db, Recording, rec_id), endpoint="get_status")
    app.add_url_rule("/transcript/<int:rec_id>", view_func=lambda rec_id: transcript(db, Recording, rec_id), endpoint="transcript")
    app.add_url_rule("/audio/<int:rec_id>", view_func=lambda rec_id: serve_audio(db, Recording, rec_id), endpoint="serve_audio")
    app.add_url_rule("/download/<int:rec_id>", view_func=lambda rec_id: download_transcript(db, Recording, rec_id), endpoint="download_transcript")

    # 4. Admin Route
    app.add_url_rule("/admin/cleanup", view_func=lambda: admin_cleanup(app, db, Recording), endpoint="admin_cleanup", methods=['POST'])
