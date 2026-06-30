"""Resume ingestion: text extraction, skill normalization, and the endpoint.

Real file parsing is exercised for DOCX/TXT; the LLM is always faked (no
network, no model). PDF relies on pypdf and isn't synthesized here.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from magpie.config import settings
from magpie.ingest.resume import (
    IngestError,
    SkillExtractor,
    extract_skills_from_upload,
    extract_text,
    is_image,
    normalize_skills,
)
from magpie.web.server import app


class FakeLLM:
    """Records how it was called and returns a canned skills payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls: list = []

    def complete_json(self, prompt, system=None):
        self.calls.append(("text", prompt, system))
        return self.payload

    def complete_vision_json(self, prompt, image_b64, mime, system=None):
        self.calls.append(("vision", image_b64, mime))
        return self.payload


def _docx_bytes(paragraphs: list[str]) -> bytes:
    from docx import Document

    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --- normalize_skills ---
def test_normalize_dedupes_and_drops_empties():
    out = normalize_skills(
        {
            "domains": [
                {"name": "Backend", "skills": ["Python", "python", "FastAPI"]},
                {"name": "backend", "skills": ["dup domain ignored"]},  # dup name
                {"name": "Empty", "skills": []},                        # no skills
                {"skills": ["no name"]},                                # no name
                "junk",                                                 # not a dict
            ]
        }
    )
    assert out == {"domains": [{"name": "Backend", "skills": ["Python", "FastAPI"]}]}


def test_normalize_flat_skills_bucketed_under_general():
    assert normalize_skills({"skills": ["Docker", "K8s"]}) == {
        "domains": [{"name": "General", "skills": ["Docker", "K8s"]}]
    }


def test_normalize_bad_input_is_empty():
    assert normalize_skills("nope") == {"domains": []}
    assert normalize_skills(None) == {"domains": []}


# --- is_image ---
def test_is_image_by_extension_and_content_type():
    assert is_image("photo.PNG")
    assert is_image("whatever", "image/jpeg")
    assert not is_image("cv.pdf")
    assert not is_image("cv.txt", "text/plain")


# --- extract_text ---
def test_extract_text_plain():
    assert "hello world" in extract_text("a.txt", "text/plain", b"hello world")


def test_extract_text_docx_includes_paragraphs():
    data = _docx_bytes(["I know Python", "and Kubernetes"])
    ctype = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    txt = extract_text("cv.docx", ctype, data)
    assert "Python" in txt and "Kubernetes" in txt


def test_extract_text_unsupported_raises():
    with pytest.raises(IngestError):
        extract_text("cv.xyz", "application/octet-stream", b"data")


# --- SkillExtractor / dispatch ---
def test_from_text_empty_raises():
    with pytest.raises(IngestError):
        SkillExtractor(llm=FakeLLM({})).from_text("   ")


def test_dispatch_text_calls_complete_json():
    llm = FakeLLM({"skills": ["Go"]})
    out = extract_skills_from_upload("cv.txt", "text/plain", b"I use Go", llm=llm)
    assert out == {"domains": [{"name": "General", "skills": ["Go"]}]}
    assert llm.calls[0][0] == "text"


def test_dispatch_image_calls_vision_with_mime():
    llm = FakeLLM({"domains": [{"name": "ML", "skills": ["PyTorch"]}]})
    out = extract_skills_from_upload("cv.png", "image/png", b"\x89PNGfake", llm=llm)
    assert out == {"domains": [{"name": "ML", "skills": ["PyTorch"]}]}
    assert llm.calls[0][0] == "vision"
    assert llm.calls[0][2] == "image/png"


def test_empty_upload_raises():
    with pytest.raises(IngestError):
        extract_skills_from_upload("cv.txt", "text/plain", b"", llm=FakeLLM({}))


# --- endpoint wiring (auth + multipart + dispatch) ---
@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "ingest.db"))


def _signup(client: TestClient, email: str = "r@test.local") -> None:
    r = client.post("/api/auth/signup", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text


def test_extract_endpoint_returns_normalized_skills(db, monkeypatch):
    import magpie.ingest.resume as resume

    monkeypatch.setattr(
        resume, "get_llm",
        lambda: FakeLLM({"domains": [{"name": "Backend", "skills": ["Python", "python"]}]}),
    )
    c = TestClient(app)
    _signup(c)
    res = c.post(
        "/api/skills/extract",
        files={"file": ("cv.txt", b"I know Python", "text/plain")},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"domains": [{"name": "Backend", "skills": ["Python"]}]}


def test_extract_endpoint_requires_auth(db):
    res = TestClient(app).post(
        "/api/skills/extract",
        files={"file": ("cv.txt", b"x", "text/plain")},
    )
    assert res.status_code == 401
