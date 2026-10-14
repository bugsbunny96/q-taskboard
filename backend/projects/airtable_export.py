"""Export a project's tasks to an Airtable table.

Design
------
* Idempotent: every write is an upsert keyed on the "Task ID" field, so running
  the export twice updates the same Airtable rows instead of duplicating them.
* Batched: Airtable accepts at most 10 records per write request, so tasks are
  sent in chunks of 10 (~100 requests for a 1,000-task project).
* Transient errors (429, 5xx, timeouts, connection errors) are retried with
  exponential backoff + jitter, honouring ``Retry-After`` when Airtable sends it.
* Permanent errors (other 4xx such as 422 invalid value) are never retried as-is.
  If a whole batch is rejected, its records are re-sent one at a time so a single
  bad record only fails itself, not the other nine in its batch.
* Fatal errors (401/403/404: bad token, no access, wrong base/table) abort the
  export immediately, because every following request would fail the same way.

The table object only needs a pyairtable-compatible
``batch_upsert(records, key_fields, typecast=...)`` method, so tests can pass
the in-memory double from ``airtable_mock.py`` instead of the real API.
"""
from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

import requests

logger = logging.getLogger(__name__)

KEY_FIELD = "Task ID"
BATCH_SIZE = 10
MAX_ATTEMPTS = 4          # 1 try + 3 retries
BASE_DELAY = 1.0          # seconds; doubles each retry
MAX_DELAY = 30.0
MIN_REQUEST_INTERVAL = 0.2  # stay under Airtable's 5 requests/sec per base

TRANSIENT_STATUSES = {408, 429, 500, 502, 503, 504}
FATAL_STATUSES = {401, 403, 404}

_sleep = time.sleep  # module-level so tests can replace it


class AirtableNotConfigured(Exception):
    """Credentials / base / table are not set in the environment."""


class AirtableFatalError(Exception):
    """An error that will affect every request (auth, permissions, wrong base)."""

    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status


@dataclass
class ExportResult:
    total: int = 0
    exported: int = 0
    failed: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"total": self.total, "exported": self.exported, "failed": self.failed}


# --------------------------------------------------------------------------- #
# Table factory
# --------------------------------------------------------------------------- #
def get_table():
    """Build the real pyairtable Table from environment variables.

    pyairtable's own urllib3 retry is disabled (``retry_strategy=False``) so that
    the retry policy lives in one place (below) and is covered by tests.
    """
    api_key = os.environ.get("AIRTABLE_API_KEY")
    base_id = os.environ.get("AIRTABLE_BASE_ID")
    table_name = os.environ.get("AIRTABLE_TABLE_NAME", "Tasks")
    if not api_key or not base_id or not table_name:
        raise AirtableNotConfigured(
            "Airtable is not configured: set AIRTABLE_API_KEY, AIRTABLE_BASE_ID and AIRTABLE_TABLE_NAME"
        )
    from pyairtable import Api

    api = Api(api_key, timeout=(5, 30), retry_strategy=False)
    return api.table(base_id, table_name)


# --------------------------------------------------------------------------- #
# Mapping
# --------------------------------------------------------------------------- #
def task_to_record(task) -> dict:
    assignee = task.assignee
    return {
        "fields": {
            KEY_FIELD: str(task.id),
            "Title": task.title,
            "Description": task.description or "",
            "Status": task.status,
            "Assignee": (assignee.name or assignee.email) if assignee else "",
            "Position": int(task.position),
            "Project": task.project.name,
        }
    }


# --------------------------------------------------------------------------- #
# Error classification
# --------------------------------------------------------------------------- #
def _status_of(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    status = _status_of(exc)
    return status in TRANSIENT_STATUSES


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    value = headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _error_message(exc: Exception) -> str:
    status = _status_of(exc)
    text = str(exc) or exc.__class__.__name__
    text = text.splitlines()[0][:300]
    return f"HTTP {status}: {text}" if status else text


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #
def _upsert_with_retry(table, records: list[dict], sleep: Callable[[float], None]) -> None:
    """Send one batch, retrying transient failures. Raises the last error."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            table.batch_upsert(records, key_fields=[KEY_FIELD], typecast=True)
            return
        except Exception as exc:  # noqa: BLE001 - classified below
            status = _status_of(exc)
            if status in FATAL_STATUSES:
                raise AirtableFatalError(status, _error_message(exc)) from exc
            if not _is_transient(exc) or attempt == MAX_ATTEMPTS:
                raise
            delay = _retry_after(exc)
            if delay is None:
                delay = min(MAX_DELAY, BASE_DELAY * 2 ** (attempt - 1)) + random.uniform(0, 0.25)
            logger.warning(
                "airtable transient error (attempt %s/%s): %s; retrying in %.2fs",
                attempt, MAX_ATTEMPTS, _error_message(exc), delay,
            )
            sleep(delay)


def _failure(record: dict, exc: Exception) -> dict:
    fields = record["fields"]
    return {"taskId": fields[KEY_FIELD], "title": fields.get("Title"), "error": _error_message(exc)}


def export_tasks(tasks: Iterable, table, sleep: Callable[[float], None] | None = None) -> ExportResult:
    """Upsert ``tasks`` into ``table``. Never raises for per-record problems;
    raises ``AirtableFatalError`` only when the whole export cannot work."""
    sleep = sleep or _sleep
    records = [task_to_record(t) for t in tasks]
    result = ExportResult(total=len(records))

    batches = [records[i:i + BATCH_SIZE] for i in range(0, len(records), BATCH_SIZE)]
    for index, batch in enumerate(batches):
        if index:
            sleep(MIN_REQUEST_INTERVAL)
        try:
            _upsert_with_retry(table, batch, sleep)
            result.exported += len(batch)
            continue
        except AirtableFatalError:
            raise
        except Exception as exc:  # noqa: BLE001
            if _is_transient(exc) or len(batch) == 1:
                # Retries exhausted (Airtable is down / throttling hard) or nothing to split:
                # record the failure and move on rather than hammering the API per record.
                result.failed.extend(_failure(r, exc) for r in batch)
                continue
            logger.warning("airtable rejected batch %s (%s); retrying records individually",
                           index, _error_message(exc))

        # Permanent batch rejection: isolate the bad record(s).
        for record in batch:
            sleep(MIN_REQUEST_INTERVAL)
            try:
                _upsert_with_retry(table, [record], sleep)
                result.exported += 1
            except AirtableFatalError:
                raise
            except Exception as exc:  # noqa: BLE001
                result.failed.append(_failure(record, exc))

    logger.info("airtable export finished: %s/%s exported, %s failed",
                result.exported, result.total, len(result.failed))
    return result
