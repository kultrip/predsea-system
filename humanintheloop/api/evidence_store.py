import json
import os
from pathlib import Path

import evidence_package


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PREDICTIONS_ROOT = Path(os.environ.get("PREDSEA_PREDICTIONS_ROOT", PROJECT_ROOT / "predictions"))
DEFAULT_GCS_PREFIX = os.environ.get("PREDSEA_GCS_PREFIX", "predictions")


class EvidenceNotFoundError(FileNotFoundError):
    pass


class EvidenceStore:
    def __init__(self, predictions_root=DEFAULT_PREDICTIONS_ROOT):
        self.predictions_root = Path(predictions_root)
        self.storage_backend = "local"

    def available_dates(self):
        if not self.predictions_root.exists():
            return []
        return sorted(
            path.name
            for path in self.predictions_root.iterdir()
            if path.is_dir() and path.name[:4].isdigit()
        )

    def latest_date(self):
        dates = self.available_dates()
        if not dates:
            raise EvidenceNotFoundError(f"No prediction dates found in {self.predictions_root}")
        return dates[-1]

    def resolve_date(self, run_date=None):
        return run_date or self.latest_date()

    def route_ids(self, run_date=None):
        date_text = self.resolve_date(run_date)
        day_dir = self.predictions_root / date_text
        if not day_dir.exists():
            raise EvidenceNotFoundError(f"No predictions found for {date_text}")
        return sorted(
            path.name
            for path in day_dir.iterdir()
            if path.is_dir() and (path / "daily_snapshot.json").exists()
        )

    def load_snapshot(self, route_id, run_date=None):
        date_text = self.resolve_date(run_date)
        evidence_path = self.predictions_root / date_text / route_id / "evidence.json"
        if evidence_path.exists():
            package = json.loads(evidence_path.read_text(encoding="utf-8"))
            return evidence_package.snapshot_from_evidence(package)
        snapshot_path = self.predictions_root / date_text / route_id / "daily_snapshot.json"
        if not snapshot_path.exists():
            raise EvidenceNotFoundError(f"No evidence for route '{route_id}' on {date_text}")
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    def load_text_artifact(self, route_id, artifact_name, run_date=None):
        date_text = self.resolve_date(run_date)
        artifact_path = self.predictions_root / date_text / route_id / artifact_name
        if not artifact_path.exists():
            raise EvidenceNotFoundError(f"No artifact '{artifact_name}' for route '{route_id}' on {date_text}")
        return artifact_path.read_text(encoding="utf-8")


class GcsEvidenceStore:
    def __init__(self, bucket_name, prefix=DEFAULT_GCS_PREFIX, client=None, fallback_store=None):
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        self.fallback_store = fallback_store
        self.storage_backend = "gcs"
        if client is None:
            from google.cloud import storage

            client = storage.Client()
        self.client = client

    def _object_name(self, *parts):
        clean_parts = [str(part).strip("/") for part in parts if str(part).strip("/")]
        if self.prefix:
            return "/".join([self.prefix, *clean_parts])
        return "/".join(clean_parts)

    def _list_blobs(self, prefix, delimiter=None):
        return self.client.list_blobs(self.bucket_name, prefix=prefix, delimiter=delimiter)

    def _download_text(self, object_name):
        bucket = self.client.bucket(self.bucket_name)
        blob = bucket.blob(object_name)
        if not blob.exists():
            raise EvidenceNotFoundError(f"No GCS object found at gs://{self.bucket_name}/{object_name}")
        return blob.download_as_text(encoding="utf-8")

    def available_dates(self):
        root_prefix = f"{self.prefix}/" if self.prefix else ""
        try:
            iterator = self._list_blobs(root_prefix, delimiter="/")
            for _ in iterator:
                pass
            dates = []
            for prefix in iterator.prefixes:
                date_text = prefix.rstrip("/").split("/")[-1]
                if date_text[:4].isdigit():
                    dates.append(date_text)
            if dates:
                return sorted(dates)
        except Exception as error:
            if self.fallback_store is None:
                raise EvidenceNotFoundError(f"Unable to list GCS prediction dates: {error}") from error

        if self.fallback_store is not None:
            return self.fallback_store.available_dates()
        return []

    def latest_date(self):
        dates = self.available_dates()
        if not dates:
            raise EvidenceNotFoundError(f"No prediction dates found in gs://{self.bucket_name}/{self.prefix}")
        return dates[-1]

    def resolve_date(self, run_date=None):
        return run_date or self.latest_date()

    def route_ids(self, run_date=None):
        date_text = self.resolve_date(run_date)
        prefix = self._object_name(date_text)
        if prefix:
            prefix = f"{prefix}/"
        route_ids = set()
        try:
            for blob in self._list_blobs(prefix):
                relative_name = blob.name[len(prefix) :]
                parts = relative_name.split("/")
                if len(parts) == 2 and parts[1] == "daily_snapshot.json":
                    route_ids.add(parts[0])
        except Exception as error:
            if self.fallback_store is None:
                raise EvidenceNotFoundError(f"Unable to list GCS routes for {date_text}: {error}") from error

        if route_ids:
            return sorted(route_ids)
        if self.fallback_store is not None:
            return self.fallback_store.route_ids(date_text)
        raise EvidenceNotFoundError(f"No predictions found for {date_text}")

    def load_snapshot(self, route_id, run_date=None):
        date_text = self.resolve_date(run_date)
        evidence_object_name = self._object_name(date_text, route_id, "evidence.json")
        try:
            return evidence_package.snapshot_from_evidence(json.loads(self._download_text(evidence_object_name)))
        except EvidenceNotFoundError:
            pass

        object_name = self._object_name(date_text, route_id, "daily_snapshot.json")
        try:
            return json.loads(self._download_text(object_name))
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_snapshot(route_id, date_text)
            raise

    def load_text_artifact(self, route_id, artifact_name, run_date=None):
        date_text = self.resolve_date(run_date)
        object_name = self._object_name(date_text, route_id, artifact_name)
        try:
            return self._download_text(object_name)
        except EvidenceNotFoundError:
            if self.fallback_store is not None:
                return self.fallback_store.load_text_artifact(route_id, artifact_name, date_text)
            raise


def create_evidence_store_from_env():
    local_store = EvidenceStore()
    bucket_name = os.environ.get("PREDSEA_GCS_BUCKET")
    if not bucket_name:
        return local_store
    return GcsEvidenceStore(
        bucket_name=bucket_name,
        prefix=os.environ.get("PREDSEA_GCS_PREFIX", DEFAULT_GCS_PREFIX),
        fallback_store=local_store,
    )
