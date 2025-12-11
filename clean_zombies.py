import os
import logging
from flask import flash, current_app 
from sqlalchemy import select

# Set up logger for this module
cleanup_logger = logging.getLogger(__name__)

def clean_zombie_entries(app_context, db_context, Recording_model, UPLOAD_FOLDER, TRANSCRIPT_FOLDER):
    """
    Checks all Recording entries against the filesystem.
    If the primary audio file is missing, the entry is considered a 'zombie'
    and is deleted along with any corresponding transcript file.
    """
    deleted_count = 0
    
    # Must run database operations within the application context
    with app_context.app_context():
        cleanup_logger.info("--- Starting Zombie Cleanup Check ---")
        
        # Query all records
        all_recordings = db_context.session.execute(db_context.select(Recording_model)).scalars().all()
        cleanup_logger.debug(f"Found {len(all_recordings)} total records in DB.")
        
        for item in all_recordings:
            # Check for the main audio file
            audio_path = os.path.join(UPLOAD_FOLDER, item.filename)
            
            # Calculate the expected transcript path
            base_filename = os.path.splitext(item.filename)[0]
            transcript_path = os.path.join(TRANSCRIPT_FOLDER, base_filename + ".txt")

            # The record is a zombie if the main audio file is missing (it should only be deleted after 'done' status)
            # OR if the status is 'done' but the transcript file is missing (indicating potential failure/corruption)
            is_zombie = not os.path.exists(audio_path)
            
            if is_zombie:
                cleanup_logger.warning(f"ZOMBIE FOUND: ID {item.id}, Filename {item.filename}. Audio file missing.")
                
                # 1. Delete Transcript File (if it exists)
                if os.path.exists(transcript_path):
                    try:
                        os.remove(transcript_path)
                        cleanup_logger.debug(f"  -> Deleted transcript file: {transcript_path}")
                    except Exception as e:
                        cleanup_logger.error(f"  -> ERROR: Failed to delete transcript file {os.path.basename(transcript_path)}: {e}")
                
                # 2. Delete database entry
                try:
                    db_context.session.delete(item)
                    deleted_count += 1
                except Exception as e:
                    cleanup_logger.error(f"  -> ERROR: Failed to delete DB entry ID {item.id}: {e}")
        
        # Commit all deletions in one go
        try:
            db_context.session.commit()
            cleanup_logger.info(f"--- Zombie Cleanup Complete: {deleted_count} entries deleted ---")
        except Exception as e:
            db_context.session.rollback()
            cleanup_logger.critical(f"ERROR: Failed to commit zombie cleanup changes: {e}")
            # Use current_app.with_test_request_context() if flashing outside a request is needed
            # For simplicity, we assume this is called inside a request context via the route
            flash("Database error during cleanup. Changes were rolled back.", 'error')
            return 0
        
        # Use Flask's flash message for feedback on the web interface
        if deleted_count > 0:
            flash(f"Cleanup successful: {deleted_count} orphaned database entries and associated files were deleted.", 'warning')
        else:
            flash("Cleanup successful: No orphaned database entries were found.", 'info')

        return deleted_count
