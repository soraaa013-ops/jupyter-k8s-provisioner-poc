import hashlib
import json
import logging
import os
import re
import time
import uuid
from collections import Counter, deque
from contextlib import contextmanager

import httpx
import psycopg
import pymysql
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("audit")
app = FastAPI(title="Jupyter POC Data Gateway", version="0.1.0")
uem_events = deque(maxlen=1000)

API_TOKEN = os.environ["GATEWAY_API_TOKEN"]
MAX_ROWS = int(os.getenv("MAX_ROWS", "100"))
READ_ONLY = re.compile(r"^\s*(select|show|explain|with)\b", re.I)
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|copy|call|do)\b", re.I)


class SqlRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10000)
    params: list = Field(default_factory=list)


class MongoFindRequest(BaseModel):
    collection: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    filter: dict = Field(default_factory=dict)
    projection: dict | None = None
    limit: int = Field(default=50, ge=1, le=100)


class ElasticSearchRequest(BaseModel):
    index: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,127}$")
    query: dict = Field(default_factory=lambda: {"match_all": {}})
    size: int = Field(default=20, ge=1, le=100)


class UemEvent(BaseModel):
    schema_version: str = "1.0"
    event: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    session_id: str = Field(min_length=1, max_length=128)
    trace_id: str | None = Field(default=None, max_length=128)
    duration_ms: float | None = Field(default=None, ge=0, le=3_600_000)
    result: str | None = Field(default=None, max_length=32)
    attributes: dict = Field(default_factory=dict)


def authorize(value: str | None) -> str:
    if value != f"Bearer {API_TOKEN}":
        raise HTTPException(401, "invalid gateway token")
    return hashlib.sha256(API_TOKEN.encode()).hexdigest()[:12]


def validate_sql(sql: str) -> None:
    stripped = sql.strip().rstrip(";")
    if ";" in stripped or not READ_ONLY.search(stripped) or FORBIDDEN.search(stripped):
        raise HTTPException(403, "only one read-only statement is allowed")


def fingerprint(statement: str) -> str:
    normalized = re.sub(r"'(?:''|[^'])*'|\b\d+(?:\.\d+)?\b", "?", statement.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def validate_document_query(value, depth=0):
    if depth > 8:
        raise HTTPException(422, "query nesting is too deep")
    forbidden = {"$where", "$function", "$accumulator", "script", "script_score", "runtime_mappings"}
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in forbidden:
                raise HTTPException(403, "executable query features are forbidden")
            validate_document_query(nested, depth + 1)
    elif isinstance(value, list):
        for nested in value:
            validate_document_query(nested, depth + 1)


def audit(request: Request, backend: str, operation: str, started: float, result: str, rows=0, fp=None):
    event = {
        "event": "data_gateway_request",
        "trace_id": request.headers.get("x-trace-id") or str(uuid.uuid4()),
        "subject": request.state.subject,
        "backend": backend,
        "operation": operation,
        "fingerprint": fp,
        "result": result,
        "rows": rows,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
    }
    log.info(json.dumps(event, separators=(",", ":")))


@app.middleware("http")
async def auth_and_audit_context(request: Request, call_next):
    if request.url.path in ("/healthz", "/docs", "/openapi.json"):
        return await call_next(request)
    request.state.subject = authorize(request.headers.get("authorization"))
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/v1/uem/events", status_code=202)
def ingest_uem(body: UemEvent, request: Request):
    allowed = {"lab_ready", "notebook_activated", "kernel_start", "kernel_ready", "kernel_restart",
               "kernel_dead", "cell_execute_start", "cell_execute_end", "js_error", "web_vital"}
    if body.event not in allowed:
        raise HTTPException(422, "event is not allowlisted")
    forbidden = {"code", "source", "output", "sql", "token", "cookie", "username", "path"}
    if forbidden.intersection(k.lower() for k in body.attributes):
        raise HTTPException(422, "sensitive attribute is forbidden")
    event = body.model_dump()
    event["subject"] = request.state.subject
    event["received_at"] = time.time()
    uem_events.append(event)
    log.info(json.dumps({"event": "uem_ingest", "uem_event": body.event,
                         "subject": request.state.subject, "trace_id": body.trace_id}, separators=(",", ":")))
    return {"accepted": True}


@app.get("/v1/uem/summary")
def uem_summary():
    return {"total": len(uem_events), "by_event": Counter(event["event"] for event in uem_events)}


def rows_to_json(cursor):
    names = [item.name if hasattr(item, "name") else item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchmany(MAX_ROWS)]


@app.post("/v1/sql/postgres")
def postgres_query(body: SqlRequest, request: Request):
    started = time.monotonic()
    validate_sql(body.sql)
    try:
        with psycopg.connect(host=os.environ["POSTGRES_HOST"], dbname=os.environ["POSTGRES_DATABASE"],
                             user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
                             options="-c statement_timeout=5000", connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(body.sql, body.params)
                rows = rows_to_json(cur)
        audit(request, "postgres", "query", started, "ok", len(rows), fingerprint(body.sql))
        return {"rows": rows, "truncated_at": MAX_ROWS}
    except HTTPException:
        raise
    except Exception as exc:
        audit(request, "postgres", "query", started, "error", fp=fingerprint(body.sql))
        raise HTTPException(502, f"postgres query failed: {type(exc).__name__}")


@app.post("/v1/sql/mysql")
def mysql_query(body: SqlRequest, request: Request):
    started = time.monotonic()
    validate_sql(body.sql)
    try:
        conn = pymysql.connect(host=os.environ["MYSQL_HOST"], user=os.environ["MYSQL_USER"],
                               password=os.environ["MYSQL_PASSWORD"], database=os.environ["MYSQL_DATABASE"],
                               connect_timeout=3, read_timeout=5, cursorclass=pymysql.cursors.DictCursor)
        try:
            with conn.cursor() as cur:
                cur.execute(body.sql, body.params)
                rows = cur.fetchmany(MAX_ROWS)
        finally:
            conn.close()
        audit(request, "mysql", "query", started, "ok", len(rows), fingerprint(body.sql))
        return {"rows": rows, "truncated_at": MAX_ROWS}
    except Exception as exc:
        audit(request, "mysql", "query", started, "error", fp=fingerprint(body.sql))
        raise HTTPException(502, f"mysql query failed: {type(exc).__name__}")


@app.post("/v1/document/mongo/find")
def mongo_find(body: MongoFindRequest, request: Request):
    started = time.monotonic()
    validate_document_query(body.filter)
    validate_document_query(body.projection)
    try:
        client = MongoClient(host=os.environ["MONGO_HOST"], username=os.environ["MONGO_USER"],
                             password=os.environ["MONGO_PASSWORD"], authSource="admin",
                             serverSelectionTimeoutMS=3000)
        docs = list(client[os.environ["MONGO_DATABASE"]][body.collection]
                    .find(body.filter, body.projection).limit(body.limit))
        for doc in docs:
            doc["_id"] = str(doc["_id"])
        audit(request, "mongo", "find", started, "ok", len(docs), fingerprint(json.dumps(body.filter, sort_keys=True)))
        return {"documents": docs}
    except Exception as exc:
        audit(request, "mongo", "find", started, "error")
        raise HTTPException(502, f"mongo find failed: {type(exc).__name__}")


@app.post("/v1/search/elasticsearch")
def elastic_search(body: ElasticSearchRequest, request: Request):
    started = time.monotonic()
    validate_document_query(body.query)
    try:
        response = httpx.post(f"{os.environ['ELASTIC_URL']}/{body.index}/_search",
                              json={"query": body.query, "size": body.size}, timeout=5)
        response.raise_for_status()
        payload = response.json()
        hits = [{"_id": hit.get("_id"), "_source": hit.get("_source")} for hit in payload["hits"]["hits"]]
        audit(request, "elasticsearch", "search", started, "ok", len(hits),
              fingerprint(json.dumps(body.query, sort_keys=True)))
        return {"hits": hits}
    except Exception as exc:
        audit(request, "elasticsearch", "search", started, "error")
        raise HTTPException(502, f"elasticsearch search failed: {type(exc).__name__}")
