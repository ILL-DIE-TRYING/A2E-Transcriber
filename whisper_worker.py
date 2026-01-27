#!/usr/bin/env python3
import os
import sys
import shutil 
import subprocess
import time
import threading 
import logging
import re 
from datetime import datetime, timedelta, timezone as dt_timezone
from flask import flash 
from sqlalchemy import select 
from sqlalchemy import func

# Make sure your config imports are correct
from config import (
    WHISPER_PATH, UPLOAD_FOLDER, TRANSCRIPT_FOLDER, BASE_DIR, 
    AVAILABLE_MODELS, WHISPER_THREADS, WHISPER_PROCESSORS, DEBUG_MODE,
    get_model_path
)

# Set up logger for this module
worker_logger = logging.getLogger('whisper_worker')

# Extremely Broad Regular Expressions for Language Detection and Probability Extraction
LANGUAGE_AND_PROBABILITY_REGEX_PRIMARY = re.compile(r'language: ([\w\s-]+) \(p = ([\d.]+)\)', re.IGNORECASE) 
LANGUAGE_REGEX_FALLBACK = re.compile(r'lang = ([\w]+)', re.IGNORECASE) 

# --- DIAGNOSTIC HELPER FUNCTION ---
def check_executable(path, name):
    """Checks if a path is an existing, executable file, handling PATH lookups."""
    exists = os.path.exists(path)
    is_file = os.path.isfile(path)
    is_exec = os.access(path, os.X_OK)

    if exists and is_file and is_exec:
        return True, f"OK: {name} found at: {path}"
    else:
        full_path = shutil.which(name)
        if full_path:
            return True, f"OK: {name} found via PATH at: {full_path}"
        else:
            return False, f"ERROR: {name} not found at {path} and not in PATH."

# --- WORKER THREAD FUNCTION ---

def process_job(app, db, Recording, recording_id):
    """
    The main worker function to process a single recording.
    Runs inside its own application context and database session.
    """
    job_id = f"REC-{recording_id}"
    worker_logger.info(f"Worker {job_id}: Starting new job.")

    # 1. Acquire app and DB context for this thread
    with app.app_context():
        # Get a fresh database session for this thread
        
        # 2. Fetch the Recording record
        recording = db.session.get(Recording, recording_id)

        if not recording:
            worker_logger.error(f"Worker {job_id}: Recording ID not found in database. Exiting.")
            return

        try:
            # 3. Pre-process setup - Record start time
            start_time = datetime.now(dt_timezone.utc)
            recording.status = 'processing'
            recording.processing_started_at = start_time
            recording.progress = 0.05 # Initial progress
            recording.updated_at = func.now()
            db.session.commit()
            worker_logger.info(f"Worker {job_id}: Set status to 'processing'.")
            
            # Construct file paths
            input_file_path = os.path.join(UPLOAD_FOLDER, recording.filename)
            base_filename = os.path.splitext(recording.filename)[0]
            # Output file will be placed in TRANSCRIPT_FOLDER with the name of the base_filename
            output_file_path = os.path.join(TRANSCRIPT_FOLDER, base_filename + ".txt") 
            
            if not os.path.exists(input_file_path):
                raise FileNotFoundError(f"Input file not found on disk: {input_file_path}")

            # 4. Construct Whisper command
            try:
                # Use the helper function to get the full absolute path to the model file
                model_path = get_model_path(recording.model_key) 
            except ValueError as e:
                # This handles the case if the model key doesn't exist in AVAILABLE_MODELS
                raise e
                
            command = [
                WHISPER_PATH,
                # Input file
                "-f", input_file_path,
                # Model to use
                "-m", model_path,
                # Output directory (where the .txt will go)
                "-of", TRANSCRIPT_FOLDER + os.sep + base_filename, # whisper cli will append .txt
                # Output format: text only for now
                "-otxt",
                # Threads and processors
                "-p", str(WHISPER_PROCESSORS),
                "-t", str(WHISPER_THREADS),
                # Language: Set explicitly to 'auto' to avoid the AttributeError.
                "-l", "auto"
            ]

            # Translation flag
            if recording.translate_to_en:
                command.append("-tr") # Add the translate flag

            worker_logger.info(f"Worker {job_id}: Executing command: {' '.join(command)}")

            # 5. Execute Whisper CLI
            # Using Popen to capture both stdout and stderr
            process = subprocess.Popen(
                command, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                cwd=BASE_DIR
            )
            
            # Wait for completion and capture all output
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                full_output = stdout + stderr
                worker_logger.error(f"Whisper CLI failed for {job_id}. Return code: {process.returncode}. Output:\n{full_output}")
                raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)

            # Combine stdout and stderr for full inspection
            full_output = stdout + stderr
            if DEBUG_MODE:
                worker_logger.debug(f"Worker {job_id}: Full Whisper output:\n{full_output}")

            # 6. Post-process and save
            if os.path.exists(output_file_path):
                worker_logger.info(f"Worker {job_id}: Reading transcript from {os.path.basename(output_file_path)}")
                
                # Use os.path.getsize(output_file_path) > 0 for sanity check
                if os.path.getsize(output_file_path) == 0:
                    raise Exception("Transcription file created but is empty.")
                    
                transcript_content = open(output_file_path, 'r', encoding='utf-8').read()

                # Extract and save language/probability
                language = None
                language_probability = None
                
                # Use the primary regex for both language name and probability
                match = LANGUAGE_AND_PROBABILITY_REGEX_PRIMARY.search(full_output)
                if match:
                    language = match.group(1).strip()
                    try:
                        language_probability = float(match.group(2))
                    except ValueError:
                        worker_logger.warning(f"Worker {job_id}: Could not parse language probability from: {match.group(2)}")
                else:
                    # Fallback for older or less verbose output
                    match_fallback = LANGUAGE_REGEX_FALLBACK.search(full_output)
                    if match_fallback:
                        language = match_fallback.group(1).strip()

                # Update DB record with transcript, status, and new fields
                recording.transcript = transcript_content
                recording.status = 'done'
                recording.progress = 1.0 # Completed
                
                # Calculate processing duration
                end_time = datetime.now(dt_timezone.utc)
                if recording.processing_started_at:
                    # Force the DB timestamp to be UTC-aware so math works with end_time
                    duration = (end_time - recording.processing_started_at.replace(tzinfo=dt_timezone.utc)).total_seconds()
                    #duration = (end_time - recording.processing_started_at).total_seconds()
                    recording.processing_duration = duration
                    worker_logger.info(f"Worker {job_id}: Processing took {duration:.2f} seconds")
                
                # Set the language fields
                recording.language = language
                recording.language_probability = language_probability
                
                recording.updated_at = func.now()
                db.session.commit()
                worker_logger.info(f"Worker {job_id}: Transcription complete and DB updated.")
                
            else:
                # FAILED PATH: Transcription file was not created
                raise Exception(f"Transcription file was not created by whisper-cli. Whisper output:\n{full_output}")

        except subprocess.CalledProcessError as e:
            error_message = f"Transcription failed (Whisper CLI error). Return code {e.returncode}. Stderr: {e.stderr}"
            recording.transcript = error_message
            recording.status = 'error'
            recording.updated_at = func.now()
            db.session.commit()
            worker_logger.error(f"Worker {job_id}: {error_message}")
            
        except Exception as e:
            # ERROR PATH: Update DB record with error status
            error_message = f"Transcription failed. Error: {e}"
            recording.transcript = error_message
            recording.status = 'error'
            recording.updated_at = func.now()
            db.session.commit()
            
            worker_logger.error(f"Worker {job_id}: {error_message}")
            
        finally:
            # Clean up the database session after the thread is finished.
            db.session.remove() 


# --- MONITOR FUNCTION ---

# Global tracking for active workers
active_workers = []
workers_lock = threading.Lock()

def queue_monitor(app, db, Recording, MAX_WORKERS):
    """
    Periodically checks the database for 'pending' jobs and starts worker threads.
    """
    worker_logger.info(f"Queue monitor started. Max workers: {MAX_WORKERS}")

    while True:
        try:
            with app.app_context():
                # 1. Clean up finished threads from tracking list
                with workers_lock:
                    global active_workers
                    active_workers = [t for t in active_workers if t.is_alive()]
                    current_workers = len(active_workers)
                
                # 2. Only start new jobs if we have available slots
                workers_needed = MAX_WORKERS - current_workers

                if workers_needed > 0:
                    # 3. Fetch pending jobs (only what we have capacity for)
                    try:
                        pending_jobs = db.session.execute(
                            select(Recording.id)
                            .filter_by(status='pending')
                            .order_by(Recording.id.asc())
                            .limit(workers_needed)
                        ).scalars().all()
                        
                    except Exception as e:
                        worker_logger.error(f"Database query error in monitor: {e}")
                        pending_jobs = []

                    # 4. Start new threads for pending jobs
                    for rec_id in pending_jobs:
                        thread = threading.Thread(
                            target=process_job,
                            args=(app, db, Recording, rec_id),
                            daemon=True,
                            name=f"WorkerThread-{rec_id}"
                        )
                        thread.start()
                        
                        with workers_lock:
                            active_workers.append(thread)
                        
                        worker_logger.info(f"Monitor: Started thread for Recording ID: {rec_id}")

        except Exception as e:
            worker_logger.error(f"Queue monitor error: {e}", exc_info=True)
        
        # Sleep for a short interval before checking again
        time.sleep(5)
