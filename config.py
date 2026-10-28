import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://pvz-h-tools.onrender.com").rstrip("/")
    # No endpoint reads uploads. Keep a small bound for accidentally submitted bodies.
    MAX_CONTENT_LENGTH = 16 * 1024
    MAX_FORM_MEMORY_SIZE = 16 * 1024
    MAX_FORM_PARTS = 8
