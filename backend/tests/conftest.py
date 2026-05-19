import os
import sys
from pathlib import Path

# Ensure ``app`` is importable when pytest is invoked from the backend root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Force dev defaults so tests don't require external services.
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://scc:dev@localhost:5432/scc")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
