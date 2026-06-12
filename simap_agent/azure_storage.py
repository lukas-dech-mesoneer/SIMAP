"""Azure Storage helpers used by the SIMAP workflow."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings, BlobSasPermissions, generate_blob_sas


def connection_string() -> str:
    value = os.getenv("AzureWebJobsStorage")
    if not value:
        raise RuntimeError("AzureWebJobsStorage is required")
    return value


def append_jsonl(container: str, blob_name: str, record: dict[str, Any]) -> None:
    """Append a JSON line to an append blob."""
    blob = _blob_service().get_blob_client(container=container, blob=blob_name)
    _ensure_container(container)
    try:
        blob.create_append_blob()
    except ResourceExistsError:
        pass

    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    blob.append_block(line.encode("utf-8"))


def put_json_blob(container: str, blob_name: str, data: dict[str, Any]) -> None:
    """Write JSON data to a block blob."""
    _ensure_container(container)
    blob = _blob_service().get_blob_client(container=container, blob=blob_name)
    blob.upload_blob(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
        overwrite=True,
        content_type="application/json",
    )


def put_blob_bytes(container: str, blob_name: str, data: bytes, content_type: str) -> str:
    """Write bytes to a block blob and return its URL."""
    _ensure_container(container)
    blob = _blob_service().get_blob_client(container=container, blob=blob_name)
    blob.upload_blob(
        data,
        overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )
    return blob.url


def blob_read_url(container: str, blob_name: str, expiry_hours: int = 24 * 30) -> str:
    """Return a temporary read URL for a blob when the storage key is available."""
    service = _blob_service()
    blob = service.get_blob_client(container=container, blob=blob_name)
    values = _connection_string_values()
    account_name = values.get("AccountName")
    account_key = values.get("AccountKey")
    if not account_name or not account_key:
        return blob.url

    sas = generate_blob_sas(
        account_name=account_name,
        container_name=container,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
    )
    return f"{blob.url}?{sas}"


def get_json_blob(container: str, blob_name: str) -> dict[str, Any] | None:
    """Read JSON data from a block blob."""
    blob = _blob_service().get_blob_client(container=container, blob=blob_name)
    try:
        data = blob.download_blob().readall()
    except ResourceNotFoundError:
        return None
    return json.loads(data.decode("utf-8"))


def _blob_service() -> BlobServiceClient:
    return BlobServiceClient.from_connection_string(connection_string())


def _ensure_container(container: str) -> None:
    service = _blob_service()
    try:
        service.create_container(container)
    except ResourceExistsError:
        pass


def _connection_string_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for part in connection_string().split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values[key] = value
    return values
