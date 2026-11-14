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
    """Optional S3 backend, only imported when configured (boto3 optional)."""

    def __init__(self, bucket: str, prefix: str = ""):
        import boto3  # lazy import
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = boto3.client("s3")

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
        backend_kind = app.config["STORAGE_BACKEND"] if app else "local"
        if backend_kind == "s3":
            _backend = S3Storage(
                app.config.get("S3_BUCKET", ""),
                app.config.get("S3_PREFIX", ""),
            )
        else:
            _backend = LocalStorage(app.config["UPLOAD_DIR"] if app else "./instance/uploads")
    return _backend


def reset_storage():
    """Reset singleton (used by tests)."""
    global _backend
    _backend = None
