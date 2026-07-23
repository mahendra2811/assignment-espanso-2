"""Application configuration, read from environment variables with sane local defaults."""
import os
from pathlib import Path

# Postgres (via docker-compose) is the default. Any SQLAlchemy URL works, e.g.
# DATABASE_URL=sqlite:///./evernine.db for a zero-dependency local run.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://evernine:evernine@localhost:5432/evernine",
)

# Directory containing orders.json and customers.csv (repo-root /data by default).
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
