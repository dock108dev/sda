"""Shared password hashing — single CryptContext for the entire app."""

from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
