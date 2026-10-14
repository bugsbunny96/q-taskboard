"""In-memory test double for a pyairtable ``Table``.

Behaves like Airtable for the parts the exporter uses:
* ``batch_upsert(records, key_fields, typecast=False)`` - creates or updates rows
  matched on ``key_fields``; rejects more than 10 records per call (422), like the API.
* Failures raise ``requests.HTTPError`` / ``requests.ConnectionError`` carrying a
  real ``requests.Response`` so the exporter's error classification is exercised
  exactly as it would be against pyairtable.

Failure injection:
* ``fail_next(status, times=1, retry_after=None)`` - next N calls fail with ``status``
  (use status=None for a network/connection error).
* ``reject_keys`` - any call containing one of these key values fails with 422
  (models a record Airtable refuses, e.g. an invalid field value).
"""
from __future__ import annotations

import itertools

import requests


def http_error(status: int, message: str = "", retry_after: float | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return requests.HTTPError(f"{status} Client Error: {message or 'mock failure'}", response=response)


class InMemoryAirtableTable:
    MAX_RECORDS_PER_REQUEST = 10

    def __init__(self):
        self.rows: dict[str, dict] = {}       # key value -> {"id": ..., "fields": {...}}
        self.calls: list[list[dict]] = []      # every batch_upsert payload, in order
        self.reject_keys: set[str] = set()
        self._planned_failures: list[tuple[int | None, float | None]] = []
        self._ids = (f"rec{n:014d}" for n in itertools.count(1))

    # -- failure injection ------------------------------------------------- #
    def fail_next(self, status: int | None, times: int = 1, retry_after: float | None = None):
        self._planned_failures.extend([(status, retry_after)] * times)

    # -- pyairtable-compatible API ----------------------------------------- #
    def batch_upsert(self, records, key_fields, replace=False, typecast=False, **_):
        self.calls.append(records)

        if self._planned_failures:
            status, retry_after = self._planned_failures.pop(0)
            if status is None:
                raise requests.ConnectionError("mock connection reset")
            raise http_error(status, "planned failure", retry_after)

        if len(records) > self.MAX_RECORDS_PER_REQUEST:
            raise http_error(422, "INVALID_RECORDS: too many records in one request")

        for record in records:
            key = tuple(record["fields"].get(k) for k in key_fields)
            if any(v in self.reject_keys for v in key):
                raise http_error(422, f"INVALID_VALUE_FOR_COLUMN for record {key}")

        created, updated = [], []
        for record in records:
            key = "|".join(str(record["fields"][k]) for k in key_fields)
            if key in self.rows:
                row = self.rows[key]
                row["fields"] = dict(record["fields"]) if replace else {**row["fields"], **record["fields"]}
                updated.append(row["id"])
            else:
                row = {"id": next(self._ids), "fields": dict(record["fields"])}
                self.rows[key] = row
                created.append(row["id"])
        return {"createdRecords": created, "updatedRecords": updated, "records": list(self.rows.values())}

    def all(self):
        return list(self.rows.values())
