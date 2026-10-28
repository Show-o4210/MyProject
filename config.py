import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://pvz-h-tools.onrender.com").rstrip("/")
    # No endpoint reads uploads. Keep a small bound for accidentally submitted bodies.
    MAX_CONTENT_LENGTH = 16 * 1024
    MAX_FORM_MEMORY_SIZE = 16 * 1024
    MAX_FORM_PARTS = 8
    REQUEST_LIMIT_PER_IP = os.environ.get("REQUEST_LIMIT_PER_IP", "10/second;120/minute")
    REQUEST_LIMIT_GLOBAL = os.environ.get("REQUEST_LIMIT_GLOBAL", "120/second;1200/minute")
    # Default to the actual peer for local/direct deployments. Render explicitly
    # opts into its Cloudflare ingress contract in render.yaml.
    TRUST_CLOUDFLARE_CLIENT_IP = os.environ.get("TRUST_CLOUDFLARE_CLIENT_IP", "false").lower() == "true"
