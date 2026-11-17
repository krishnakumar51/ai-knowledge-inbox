import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.item import SourceType
from app.schemas.ingest import IngestRequest
from app.services.chunking import chunk_text


def test_ingest_note_requires_content():
    with pytest.raises(ValidationError):
        IngestRequest(source_type=SourceType.note)


def test_ingest_note_accepts_content():
    payload = IngestRequest(source_type=SourceType.note, content="A useful note")
    assert payload.content == "A useful note"


def test_url_ingest_accepts_short_url_field_alias():
    payload = IngestRequest(source_type=SourceType.url, url="https://example.com/article")
    assert str(payload.source_url) == "https://example.com/article"


def test_sample_note_dataset_contains_six_valid_notes():
    dataset = Path(__file__).parents[1] / "testdata" / "sample_notes.json"
    payloads = json.loads(dataset.read_text(encoding="utf-8"))
    assert len(payloads) == 6
    assert all(IngestRequest.model_validate(payload).source_type == SourceType.note for payload in payloads)


def test_chunking_respects_size_and_overlap():
    text = " ".join(f"word{i}" for i in range(120))
    chunks = chunk_text(text, chunk_size=80, overlap=12)
    assert len(chunks) > 1
    assert all(len(chunk) <= 80 for chunk in chunks)


def test_chunking_rejects_invalid_overlap():
    with pytest.raises(ValueError):
        chunk_text("text", chunk_size=10, overlap=10)
