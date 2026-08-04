"""Non-mutating URL inspection for controlled internet asset imports."""

from collections.abc import Mapping
from typing import Any

import requests

from .models import LinkInspectionResult
from .policy import InternetDownloadPolicy, InternetPolicyError, validate_asset_url

INSPECTION_CHUNK_SIZE = 1024 * 1024


def inspect_asset_url(
    url: str,
    *,
    policy: InternetDownloadPolicy,
    session: Any | None = None,
) -> LinkInspectionResult:
    extension = validate_asset_url(url, policy=policy)
    active_session = session or requests.Session()
    try:
        response = active_session.get(
            url,
            stream=True,
            timeout=policy.timeout_seconds,
            allow_redirects=True,
        )
    except requests.exceptions.RequestException as exc:
        raise InternetPolicyError(
            "Asset URL inspection failed before receiving a response."
        ) from exc

    try:
        response.raise_for_status()
        final_url = _response_url(response, fallback=url)
        final_extension = validate_asset_url(final_url, policy=policy)
        redirect_chain = _redirect_chain(response)
        if len(redirect_chain) > policy.max_redirects:
            raise InternetPolicyError("Asset URL followed too many redirects.")

        headers = _response_headers(response)
        header_size = _content_length(headers)
        if header_size is not None and header_size > policy.max_asset_size_bytes:
            raise InternetPolicyError(
                f"Asset URL is larger than {policy.max_asset_size_bytes} bytes."
            )

        bytes_read = 0
        for chunk in response.iter_content(chunk_size=INSPECTION_CHUNK_SIZE):
            if not chunk:
                continue
            bytes_read += len(chunk)
            if bytes_read > policy.max_asset_size_bytes:
                raise InternetPolicyError(
                    f"Asset URL is larger than {policy.max_asset_size_bytes} bytes."
                )

        size_bytes = header_size if header_size is not None else bytes_read
        if size_bytes == 0:
            raise InternetPolicyError("Asset URL returned an empty file.")

        return LinkInspectionResult(
            allowed=True,
            requested_url=url,
            final_url=final_url,
            extension=final_extension or extension,
            size_bytes=size_bytes,
            redirect_chain=redirect_chain,
            warnings=(),
        )
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _response_url(response: Any, *, fallback: str) -> str:
    url = getattr(response, "url", fallback)
    return url if isinstance(url, str) and url else fallback


def _response_headers(response: Any) -> Mapping[str, str]:
    headers = getattr(response, "headers", {})
    return headers if isinstance(headers, Mapping) else {}


def _content_length(headers: Mapping[str, str]) -> int | None:
    for key, value in headers.items():
        if key.lower() != "content-length":
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None
    return None


def _redirect_chain(response: Any) -> tuple[str, ...]:
    history = getattr(response, "history", ())
    if not isinstance(history, tuple | list):
        return ()
    urls: list[str] = []
    for item in history:
        item_url = getattr(item, "url", None)
        if isinstance(item_url, str) and item_url:
            urls.append(item_url)
    return tuple(urls)
