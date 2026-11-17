"""Storage backends (Section 8): StorageBackend interface, LocalStorage default,
optional S3Storage."""
import os


class StorageBackend:
    def save(self, data: bytes, key: str) -> None:
        raise NotImplementedError

    def open(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    """Store files under a root directory outside the static folder."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def _path(self, key: str) -> str:
        # key is like "2026/01/<uuid>.jpg"; defend against traversal
        clean = os.path.normpath(key).replace("\\", "/").lstrip("/").replace("..", "")
        return os.path.join(self.root, clean)

    def save(self, data: bytes, key: str) -> None:
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def open(self, key: str) -> bytes:
        with open(self._path(key), "rb") as f:
            return f.read()

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass


class S3Storage(StorageBackend):
    """S3-compatible object storage (Issue 5): boto3, private bucket, files
    served only through the authorised /api/v1/images/{id} endpoints.
    Works with AWS S3 and any S3-compatible provider (Cloudflare R2,
    Backblaze B2, …) via S3_ENDPOINT_URL."""

    def __init__(self, bucket: str, prefix: str = "", endpoint_url: str = None,
                 region: str = None, access_key: str = None, secret_key: str = None):
        import boto3  # lazy import
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}".lstrip("/")

    def save(self, data: bytes, key: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data)

    def open(self, key: str) -> bytes:
        resp = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        return resp["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))


_backend = None


def get_storage(app=None) -> StorageBackend:
    """Return the configured storage backend (singleton)."""
    global _backend
    if _backend is None:
        if app is None:
            from flask import current_app
            try:
                app = current_app._get_current_object()
            except RuntimeError:
                app = None
        backend_kind = (app.config["STORAGE_BACKEND"] if app
                        else "local")
        if backend_kind == "s3":
            _backend = S3Storage(
                app.config.get("S3_BUCKET", ""),
                app.config.get("S3_PREFIX", ""),
                endpoint_url=app.config.get("S3_ENDPOINT_URL"),
                region=app.config.get("S3_REGION"),
                access_key=app.config.get("S3_ACCESS_KEY_ID"),
                secret_key=app.config.get("S3_SECRET_ACCESS_KEY"),
            )
        else:
            _backend = LocalStorage(app.config["UPLOAD_DIR"] if app else "./instance/uploads")
    return _backend


def reset_storage():
    """Reset singleton (used by tests)."""
    global _backend
    _backend = None
