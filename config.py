import os
import logging
from logging.handlers import RotatingFileHandler

# --- CORE APPLICATION SETTINGS ---
SERVER_PORT = 8090 # Port this application listens on
SECRET_KEY = 'a-super-secret-key-for-flash' # CHANGE THIS IN PRODUCTION!
MAX_CONTENT_LENGTH = 100 * 1024 * 1024 # 100 MB limit
DATABASE_URI = 'sqlite:///database.db' # Database setup

## DISABLE THIS ONCE YOU GET GOING
## Set to "True" it will show all kinds of debugging information in the terminal
DEBUG_MODE = True

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
# You can add larger models if your computer can handle them
MODEL_FILENAMES = {
    "tiny": "ggml-tiny.bin",
    "base": "ggml-base.bin",
    "small": "ggml-small.bin",
    "medium": "ggml-medium.bin"
}

# Models displayed in the UI
# This and MODEL_FILENAMES and AVAILABLE_MODELS need to match (Not text but models)!
WHISPER_UI_MODELS = {
    "tiny": "Tiny (Fastest, Least Accurate)",
    "base": "Base",
    "small": "Small",
    "medium": "Medium (Most Accurate)"
}

# New dictionary mapping model keys to the actual model file base name (e.g., 'base' -> 'base')
# If you have enough machine, you can expand this to large, etc. Be sure to download the proper models you want to use. (See README)
# Raspberry PI seriously struggles with medium. It takes a long time with small even.
AVAILABLE_MODELS = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium"
}

# 1. Define the root of the whisper.cpp project folder. This setting assumes the transcriber directory and the whisper.cpp directory next to each other
# /path/to/directory/transcriber
# /path/to/directory/whisper.cpp
WHISPER_ROOT = os.path.abspath(
    os.path.join(BASE_DIR, os.pardir, 'whisper.cpp')
)

# 2. WHISPER_PATH points to the root for models and the cli utility (Whisper Version 1.8.1
WHISPER_PATH = os.path.join(WHISPER_ROOT, 'build', 'bin', 'whisper-cli')

# --- WORKER & EXECUTION SETTINGS ---
# This is where you can tune how agressive Whisper.cpp is on your CPU.
# I used the intial setting with a Intel(R) Core(TM) i7-4770 CPU @ 3.40GHz

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
