from __future__ import annotations

from io import BytesIO
from urllib.parse import urlparse

from websensors_flow_rag.config import MinIOSettings


class MinIOClient:
    def __init__(self, settings: MinIOSettings):
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("A dependência minio não está instalada.") from exc

        parsed = urlparse(settings.endpoint if "://" in settings.endpoint else f"http://{settings.endpoint}")
        endpoint = parsed.netloc or parsed.path
        secure = settings.secure if parsed.scheme not in {"http", "https"} else parsed.scheme == "https"
        self.settings = settings
        from urllib3 import PoolManager, Timeout
        from urllib3.util.retry import Retry

        timeout = float(settings.timeout_seconds)
        http_client = PoolManager(
            timeout=Timeout(connect=min(5, timeout), read=timeout),
            retries=Retry(total=0),
        )
        self.client = Minio(
            endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=secure,
            region=settings.region,
            http_client=http_client,
        )

    def ensure_bucket(self, bucket: str) -> None:
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def get_bytes(self, bucket: str, key: str) -> bytes:
        response = self.client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.ensure_bucket(bucket)
        stream = BytesIO(data)
        self.client.put_object(
            bucket,
            key,
            stream,
            length=len(data),
            content_type=content_type,
        )

    def put_text(self, bucket: str, key: str, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        self.put_bytes(bucket, key, text.encode("utf-8"), content_type)
