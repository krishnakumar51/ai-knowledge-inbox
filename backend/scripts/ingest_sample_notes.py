import asyncio
import json
import os
from pathlib import Path

import httpx


async def main() -> None:
    base_url = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
    dataset = Path(__file__).parents[1] / "testdata" / "sample_notes.json"
    notes = json.loads(dataset.read_text(encoding="utf-8"))
    async with httpx.AsyncClient(timeout=60) as client:
        for note in notes:
            response = await client.post(f"{base_url}/api/v1/ingest", json=note)
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
