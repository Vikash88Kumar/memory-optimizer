"""Create MEMORA collections, regular + TTL indexes, Atlas Vector Search indexes, and the demo account.

Usage (from the repository root, with .env filled in):
    pip install -r backend/requirements.txt
    python scripts/setup_db.py                 # everything
    python scripts/setup_db.py --print-index   # just print the Vector Search index JSON for the Atlas UI
"""
import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
os.chdir(ROOT)  # so pydantic-settings reads ./.env

from app.core.config import get_settings  # noqa: E402
from app.database import mongo  # noqa: E402
from app.database.indexes import (change_streams_available, ensure_collections, ensure_regular_indexes,  # noqa: E402
                                  ensure_vector_indexes, vector_index_definitions)


async def main(print_only: bool) -> None:
    s = get_settings()
    defs = vector_index_definitions(s)
    if print_only:
        print(json.dumps(defs, indent=2))
        return
    db = await mongo.connect(s)
    await ensure_collections(db)
    await ensure_regular_indexes(db, s)
    print("Collections and regular/TTL indexes: ok")
    if s.vector_backend == "mongodb":
        try:
            created = await ensure_vector_indexes(db, s)
            print(f"Vector Search indexes: {'created ' + ', '.join(created) if created else 'already present'}")
            print("Atlas builds new indexes in the background; wait until their status is READY before demoing.")
        except Exception as exc:  # noqa: BLE001
            print(f"Could not create Vector Search indexes automatically ({exc}).")
            print("Create them in the Atlas UI (Search & Vector Search > Create index > JSON editor) using:")
            print(json.dumps(defs, indent=2))
    else:
        print("VECTOR_BACKEND=local: skipping Vector Search indexes (development fallback).")
    print(f"Change streams available: {await change_streams_available(db)}")
    if s.enable_demo_tools:
        from app.demo.seed import ensure_demo_user
        from app.llm.embeddings import get_embedder

        user = await ensure_demo_user(db, get_embedder())
        print(f"Demo account ready: {user['username']} / (DEMO_PASSWORD)")
    await mongo.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--print-index", action="store_true")
    asyncio.run(main(parser.parse_args().print_index))
