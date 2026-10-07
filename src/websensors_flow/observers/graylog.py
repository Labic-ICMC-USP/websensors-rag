"""Graylog observer implemented with graypy."""

from __future__ import annotations

import json
import logging
import socket
from typing import Any

from websensors_flow.config import GraylogConfig
from websensors_flow.events import PipelineEvent
from websensors_flow.exceptions import ObserverError, PreflightCheckError
from websensors_flow.observers.base import PipelineObserver
from websensors_flow.result import MetricRecord


class GraylogObserver(PipelineObserver):
    """Send pipeline events to Graylog using GELF TCP."""

    name = "graylog"

    def __init__(self, config: GraylogConfig):
        self.config = config
        self._logger: logging.Logger | None = None
        self._handler: logging.Handler | None = None

    def validate_ready(self) -> None:
        try:
            import graypy  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise PreflightCheckError(
                "Graylog preflight failed because the 'graypy' package is not installed."
            ) from exc

        if self.config.protocol != "tcp":
            raise PreflightCheckError("Graylog preflight failed because only GELF TCP is supported.")

        try:
            with socket.create_connection(
                (str(self.config.host), int(self.config.port)),
                timeout=float(self.config.connect_timeout_seconds),
            ):
                pass
        except OSError as exc:
            raise PreflightCheckError(
                "Graylog preflight failed because a TCP connection could not be opened to "
                f"{self.config.host}:{self.config.port}."
            ) from exc

        try:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(float(self.config.connect_timeout_seconds))
            try:
                logger_name = f"websensors_flow.graylog.{id(self)}"
                logger = logging.getLogger(logger_name)
                logger.setLevel(getattr(logging, self.config.level.upper(), logging.INFO))
                logger.propagate = False
                logger.handlers.clear()

                kwargs: dict[str, Any] = {
                    "host": self.config.host,
                    "port": self.config.port,
                    "facility": self.config.facility,
                    "localname": self.config.localname or socket.gethostname(),
                }
                handler = graypy.GELFTCPHandler(**kwargs)
                logger.addHandler(handler)
                self._logger = logger
                self._handler = handler
                self._emit_raw(
                    "websensors_flow_graylog_ready",
                    {
                        "observer": self.name,
                        "graylog_host": self.config.host,
                        "graylog_port": self.config.port,
                        "graylog_protocol": self.config.protocol,
                        "graylog_auth_enabled": self.config.auth.enabled,
                        "graylog_auth_user": self.config.auth.username,
                    },
                )
            finally:
                socket.setdefaulttimeout(old_timeout)
        except Exception as exc:
            raise PreflightCheckError("Graylog preflight failed after the TCP connection succeeded.") from exc

    def preflight_probe(self, event: PipelineEvent) -> None:
        payload = event.as_log_dict()
        payload["graylog_preflight_probe"] = True
        self._emit_raw("websensors_flow_preflight_probe", payload)

    def on_event(self, event: PipelineEvent) -> None:
        self._emit_event(event)
        for index, record in enumerate(event.metric_records, start=1):
            self._emit_metric_record(event, record, index=index)

    def _emit_event(self, event: PipelineEvent) -> None:
        payload = event.as_log_dict()
        payload["event_json"] = event.model_dump(mode="json")
        self._emit_raw(event.event_type, payload)

    def _emit_metric_record(self, event: PipelineEvent, record: MetricRecord, *, index: int) -> None:
        payload: dict[str, Any] = {
            "event_type": "metric_record",
            "pipeline_name": event.pipeline_name,
            "run_id": event.run_id,
            "environment": event.environment,
            "step_name": event.step_name,
            "step_index": event.step_index,
            "record_index": index,
            "record_name": record.name,
            "record_json": record.model_dump(mode="json"),
        }
        for key, value in record.metrics.items():
            payload[f"metric_{key}"] = value
        for key, value in record.params.items():
            payload[f"param_{key}"] = value
        for key, value in record.metadata.items():
            payload[f"metadata_{key}"] = value
        for key, value in record.artifacts.items():
            payload[f"artifact_{key}"] = value
        self._emit_raw("metric_record", payload)

    def _emit_raw(self, message: str, extra: dict[str, Any]) -> None:
        if self._logger is None:
            raise ObserverError("Graylog observer was not initialized.")
        try:
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(float(self.config.connect_timeout_seconds))
            try:
                self._logger.info(message, extra=self._extra_fields(extra))
                if self._handler is not None:
                    self._handler.flush()
            finally:
                socket.setdefaulttimeout(old_timeout)
        except Exception as exc:
            raise ObserverError("Could not send event to Graylog.") from exc

    def _extra_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in payload.items():
            safe_key = self._safe_key(key)
            if isinstance(value, (dict, list, tuple, set)):
                result[f"_{safe_key}"] = json.dumps(value, ensure_ascii=False, default=str)
            else:
                result[f"_{safe_key}"] = value
        return result

    @staticmethod
    def _safe_key(value: str) -> str:
        text = str(value).replace(".", "_").replace("-", "_").replace(" ", "_")
        return "".join(char for char in text if char.isalnum() or char == "_")[:120]

    def close(self, status: str) -> None:
        if self._handler is not None:
            try:
                self._handler.flush()
            finally:
                self._handler.close()
        if self._logger is not None and self._handler is not None:
            self._logger.removeHandler(self._handler)
