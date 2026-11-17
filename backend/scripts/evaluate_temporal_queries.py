"""Run the checked-in temporal query set against a live AI Knowledge Inbox API."""

import argparse
import getpass
import json
from pathlib import Path

import httpx


def score_result(expected_sources: list[str], source_ids: list[str], expected_facts: list[str], answer: str) -> dict:
    found = set(source_ids)
    expected = set(expected_sources)
    source_recall = len(found & expected) / len(expected) if expected else 1.0
    normalized = answer.casefold()
    matched_facts = [fact for fact in expected_facts if fact.casefold() in normalized]
    return {
        "source_recall": source_recall,
        "matched_sources": sorted(found & expected),
        "missing_sources": sorted(expected - found),
        "matched_facts": matched_facts,
        "facts_match": len(matched_facts) == len(expected_facts),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--dataset", type=Path, default=Path(__file__).parents[1] / "testdata" / "temporal_queries.json"
    )
    parser.add_argument("--email", default="test-user@example.com")
    args = parser.parse_args()
    try:
        payload = json.loads(args.dataset.read_text(encoding="utf-8"))
        password = getpass.getpass("Account password: ")
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=60.0) as client:
            response = client.post("/api/v1/auth/login", json={"email": args.email, "password": password})
            response.raise_for_status()
            client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
            items_response = client.get("/api/v1/items", params={"limit": 200})
            items_response.raise_for_status()
            external_by_id = {
                item["id"]: item.get("external_id") for item in items_response.json()["items"]
            }
            rows = []
            for query in payload["queries"]:
                result = client.post("/api/v1/query", json={"question": query["question"]})
                if result.is_error:
                    rows.append({"id": query["id"], "status": result.status_code, "error": result.json()})
                    continue
                body = result.json()
                source_ids = [
                    external_by_id[source["item_id"]]
                    for source in body.get("sources", [])
                    if source.get("item_id") in external_by_id
                    and external_by_id[source["item_id"]] is not None
                ]
                score = score_result(
                    query["expected_source_external_ids"],
                    source_ids,
                    query.get("expected_facts", []),
                    body.get("answer", ""),
                )
                rows.append({"id": query["id"], "status": "ok", **score})
            print(json.dumps({"dataset_id": payload["dataset_id"], "results": rows}, indent=2))
            return 1 if any(row["status"] != "ok" or row["source_recall"] < 1 or not row["facts_match"] for row in rows) else 0
    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
