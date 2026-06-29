# config.py
import os
from dotenv import load_dotenv
load_dotenv()

class Config:
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024