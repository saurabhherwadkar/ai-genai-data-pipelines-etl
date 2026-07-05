"""Loaders: target destination writers for processed data."""

from .base import BaseLoader
from .json_loader import JSONFileLoader
from .database_loader import DatabaseLoader
from .api_loader import APILoader

__all__ = ["APILoader", "BaseLoader", "DatabaseLoader", "JSONFileLoader"]
