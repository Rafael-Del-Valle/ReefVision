"""Object-store contract for hosted datasets and collaboration."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ObjectStore(Protocol):
    def put_file(self, local_path: Path, object_key: str) -> str: ...
    def get_file(self, object_key: str, destination: Path) -> Path: ...
    def exists(self, object_key: str) -> bool: ...


class S3ObjectStore:
    def __init__(self, bucket: str, endpoint_url: str | None = None) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url)

    def put_file(self, local_path: Path, object_key: str) -> str:
        self.client.upload_file(str(local_path), self.bucket, object_key)
        return f"s3://{self.bucket}/{object_key}"

    def get_file(self, object_key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, object_key, str(destination))
        return destination

    def exists(self, object_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=object_key)
            return True
        except self.client.exceptions.ClientError:
            return False
