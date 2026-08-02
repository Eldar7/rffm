"""HTTP client with retry/backoff, rate limiting, and structured crawl logging.

This is the only place in the codebase that talks to the network. Every
request (success or failure) is appended to an in-memory crawl log that the
pipeline later flushes to crawl_log.csv, so a run's full request history is
always auditable and partial failures never silently disappear.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from rffm_scraper.config import Settings

logger = logging.getLogger("rffm_scraper.http")


@dataclass
class CrawlLogEntry:
    run_id: str
    timestamp: str
    stage: str
    entity_type: str
    entity_id: str
    source_url: str
    http_status: int | None
    success: bool
    retry_count: int
    parser_type: str
    raw_saved_path: str
    message: str
    elapsed_seconds: float | None = None


def _is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        if response is None:
            return True
        # Retry on server errors and rate limiting, not on 4xx client errors
        # (a 404 will never succeed on retry).
        return response.status_code >= 500 or response.status_code == 429
    return isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    )


class RffmClient:
    def __init__(self, settings: Settings, run_id: str | None = None):
        self.settings = settings
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": settings.network.user_agent,
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.5",
            }
        )
        self._last_request_at = 0.0
        self._lock = threading.Lock()
        self.crawl_log: list[CrawlLogEntry] = []

    # -- rate limiting -----------------------------------------------------
    def _throttle(self) -> None:
        with self._lock:
            min_gap = self.settings.network.rate_limit_seconds
            now = time.monotonic()
            wait = self._last_request_at + min_gap - now
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

    # -- logging -------------------------------------------------------------
    def _log(
        self,
        *,
        stage: str,
        entity_type: str,
        entity_id: str,
        url: str,
        status: int | None,
        success: bool,
        retry_count: int,
        parser_type: str,
        raw_saved_path: str = "",
        message: str = "",
        elapsed_seconds: float | None = None,
    ) -> None:
        entry = CrawlLogEntry(
            run_id=self.run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            stage=stage,
            entity_type=entity_type,
            entity_id=entity_id,
            source_url=url,
            http_status=status,
            success=success,
            retry_count=retry_count,
            parser_type=parser_type,
            raw_saved_path=raw_saved_path,
            message=message,
            elapsed_seconds=elapsed_seconds,
        )
        self.crawl_log.append(entry)

    # -- core request --------------------------------------------------------
    def _request_with_retry(self, url: str, params: dict[str, Any] | None):
        max_attempts = self.settings.network.max_retries
        backoff = self.settings.network.retry_backoff_seconds

        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=backoff, min=backoff, max=60),
            retry=retry_if_exception(_is_retryable_http_error),
            reraise=True,
        )
        def _do() -> requests.Response:
            self._throttle()
            resp = self.session.get(
                url,
                params=params,
                timeout=self.settings.network.request_timeout_seconds,
            )
            resp.raise_for_status()
            return resp

        return _do()

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        stage: str = "fetch",
        entity_type: str = "",
        entity_id: str = "",
        parser_type: str = "",
    ) -> requests.Response | None:
        """GET a URL, log the outcome, and return the Response or None on failure.

        Never raises - a single broken page must not abort the whole crawl.
        """
        started = time.monotonic()
        try:
            resp = self._request_with_retry(url, params)
            self._log(
                stage=stage,
                entity_type=entity_type,
                entity_id=entity_id,
                url=resp.url,
                status=resp.status_code,
                success=True,
                retry_count=0,
                parser_type=parser_type,
                elapsed_seconds=time.monotonic() - started,
            )
            return resp
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            logger.warning("HTTP error fetching %s (params=%s): %s", url, params, exc)
            self._log(
                stage=stage,
                entity_type=entity_type,
                entity_id=entity_id,
                url=url,
                status=status,
                success=False,
                retry_count=self.settings.network.max_retries,
                parser_type=parser_type,
                message=str(exc),
                elapsed_seconds=time.monotonic() - started,
            )
            return None
        except requests.exceptions.RequestException as exc:
            logger.warning("Request failed fetching %s (params=%s): %s", url, params, exc)
            self._log(
                stage=stage,
                entity_type=entity_type,
                entity_id=entity_id,
                url=url,
                status=None,
                success=False,
                retry_count=self.settings.network.max_retries,
                parser_type=parser_type,
                message=str(exc),
                elapsed_seconds=time.monotonic() - started,
            )
            return None

    def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        stage: str = "fetch",
        entity_type: str = "",
        entity_id: str = "",
    ) -> Any | None:
        url = self.settings.site.base_url.rstrip("/") + path
        resp = self.get(
            url,
            params=params,
            stage=stage,
            entity_type=entity_type,
            entity_id=entity_id,
            parser_type="json_api",
        )
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError as exc:
            logger.warning("Bad JSON from %s: %s", url, exc)
            self._log(
                stage=stage,
                entity_type=entity_type,
                entity_id=entity_id,
                url=url,
                status=resp.status_code,
                success=False,
                retry_count=0,
                parser_type="json_api",
                message=f"json decode error: {exc}",
            )
            return None

    def get_html(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        stage: str = "fetch",
        entity_type: str = "",
        entity_id: str = "",
    ) -> tuple[str, requests.Response] | None:
        url = self.settings.site.base_url.rstrip("/") + path
        resp = self.get(
            url,
            params=params,
            stage=stage,
            entity_type=entity_type,
            entity_id=entity_id,
            parser_type="html_next_data",
        )
        if resp is None:
            return None
        return resp.text, resp
