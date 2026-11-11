import hashlib
import json
import logging
import os
import time
from collections import Counter, deque

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("uem")
app = FastAPI(title="Jupyter POC UEM Collector", version="0.2.0")
events = deque(maxlen=1000)
API_TOKEN = os.environ["UEM_API_TOKEN"]


class UemEvent(BaseModel):
    schema_version: str = "1.0"
    event: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    session_id: str = Field(min_length=1, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    duration_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    result: str | None = Field(default=None, max_length=32)
    attributes: dict = Field(default_factory=dict)


def subject(authorization: str | None) -> str:
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(401, "invalid collector token")
    return hashlib.sha256(API_TOKEN.encode()).hexdigest()[:12]


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/v1/uem/events", status_code=202)
def ingest(body: UemEvent, authorization: str | None = Header(default=None)):
    authenticated_subject = subject(authorization)
    allowed = {"lab_ready", "notebook_activated", "kernel_start", "kernel_ready", "kernel_restart",
               "kernel_dead", "cell_execute_start", "cell_execute_end", "js_error", "web_vital"}
    if body.event not in allowed:
        raise HTTPException(422, "event is not allowlisted")
    forbidden = {"code", "source", "output", "sql", "token", "cookie", "username", "path"}
    if forbidden.intersection(key.lower() for key in body.attributes):
        raise HTTPException(422, "sensitive attribute is forbidden")
    event = body.model_dump()
    event["subject"] = authenticated_subject
    event["received_at"] = time.time()
    events.append(event)
    log.info(json.dumps({"event": "uem_ingest", "uem_event": body.event,
                         "subject": authenticated_subject, "trace_id": body.trace_id}, separators=(",", ":")))
    return {"accepted": True}


@app.get("/v1/uem/summary")
def summary(authorization: str | None = Header(default=None)):
    subject(authorization)
    return {"total": len(events), "by_event": Counter(event["event"] for event in events)}
