"""FastAPI dependencies for the sports-data-admin API."""

from app.dependencies.auth import verify_api_key
from app.dependencies.consumer_auth import verify_consumer_api_key

__all__ = ["verify_api_key", "verify_consumer_api_key"]
