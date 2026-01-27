import os
import logging
from logging.handlers import RotatingFileHandler

# --- CORE APPLICATION SETTINGS ---
SERVER_PORT = 8090
SECRET_KEY = 'a-super-secret-key-for-flash' # CHANGE THIS IN PRODUCTION!
MAX_CONTENT_LENGTH = 100 * 1024 * 1024 # 100 MB limit
DATABASE_URI = 'sqlite:///database.db'
DEBUG_MODE = False

# --- SECURITY & USER SETTINGS ---
# Set to True to allow anyone to register. Set to False after creating your admin user.
REGISTRATION_ENABLED = False 
# If True, the "Translate to English" checkbox on the upload form will be checked by default.
DEFAULT_TRANSLATE_TO_EN = True 
# The default model to select on the upload form. Must be a key in WHISPER_UI_MODELS.
DEFAULT_MODEL_KEY = "tiny" # <-- RESTORED THIS LINE

# --- PATHS AND DIRECTORIES ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
TRANSCRIPT_FOLDER = os.path.join(BASE_DIR, 'transcripts')
LOG_FILE = os.path.join(BASE_DIR, 'app_logs.log')

# Allowed file extensions for upload
ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg', 'flac', 'm4a', 'mp4', 'webm', 'aac'}

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TRANSCRIPT_FOLDER, exist_ok=True)

# Assuming your model files are named ggml-{model_key}.bin
# Be sure to download the models using the whisper tool!
MODEL_FILENAMES = {
    "tiny": "ggml-tiny.bin",
    "base": "ggml-base.bin",
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin",
    #"large-v1": "ggml-large-v1.bin",
    "large-v2": "ggml-large-v2.bin"
    #"large-v3": "ggml-large-v3.bin",
    #"large-v3-turbo": "ggml-large-v3-turbo.bin"
}

# Models displayed in the UI
# This and AVAILABLE_MODELS need to match!
WHISPER_UI_MODELS = {
    "tiny": "Tiny (Fastest, Least Accurate)",
    "base": "Base",
    "small": "Small",
    "medium": "Medium",
    #"large-v1": "Large V1",
    "large-v2": "Large V2 (Most Accurate)"
    #"large-v3": "Large V3",
    #"large-v3-turbo": "Large V3 Turbo"
}

# New dictionary mapping model keys to the actual model file base name (e.g., 'base' -> 'base')
# If you have enough machine, you can expand this to large, etc. Be sure to download the proper models you want to use.
# Raspberry PI seriously struggles with medium. It takes a long time with small even.
AVAILABLE_MODELS = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    #"large-v1": "large-v1",
    "large-v2": "large-v2"
    #"large-v3": "large-v3",
    #"large-v3-turbo": "large-v3-turbo"
}

# 1. Define the root of the whisper.cpp project folder. This setting assumes the transcriber directory and the whisper.cpp directory next to each other
# /path/to/directory/transcriber
# /path/to/directory/whisper.cpp
WHISPER_ROOT = os.path.abspath(
    os.path.join(BASE_DIR, os.pardir, 'whisper.cpp')
)

# 2. WHISPER_PATH points to the root for models and the cli utility
WHISPER_PATH = os.path.join(WHISPER_ROOT, 'build', 'bin', 'whisper-cli')

# --- WORKER & EXECUTION SETTINGS ---
# Maximum concurrent worker threads for the queue monitor
MAX_WORKERS = 1 
# Number of CPU threads to use for Whisper processing (--threads)
WHISPER_THREADS = 2
# Number of CPU processors (cores) to use for Whisper processing (-t)
WHISPER_PROCESSORS = 4


def get_model_path(model_key):
    """Returns the full path to the required model .bin file."""
    model_name = AVAILABLE_MODELS.get(model_key)
    if not model_name:
        raise ValueError(f"Unknown model key: {model_key}")
    return os.path.join(WHISPER_ROOT, 'models', f'ggml-{model_name}.bin')


def setup_logging():
    """Initializes logging configuration based on DEBUG_MODE."""
    log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Clear existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # Console Handler (always present)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(threadName)s - %(message)s'
    ))
    logger.addHandler(console_handler)
    
    # File Handler (Rotating)
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1024*1024*5, backupCount=5)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(threadName)s - %(message)s'
    ))
    logger.addHandler(file_handler)

setup_logging()
