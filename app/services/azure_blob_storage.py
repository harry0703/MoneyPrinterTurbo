"""
Azure Blob Storage integration for offloading generated video files.

When enabled, final (and optionally combined) videos are uploaded to Azure
Blob Storage immediately after creation and the local copies are deleted to
free disk space.  The public/SAS-signed blob URL is returned so downstream
callers can access the video without keeping it on disk.
"""
import os
from typing import Optional

from loguru import logger

try:
    from azure.storage.blob import BlobServiceClient, ContentSettings
    _AZURE_BLOB_AVAILABLE = True
except ImportError:
    _AZURE_BLOB_AVAILABLE = False

from app.config import config


class AzureBlobStorageService:
    def __init__(self):
        cfg = config.azure_blob
        self.enabled: bool = cfg.get("enabled", False)
        self.connection_string: str = cfg.get("connection_string", "")
        self.container_name: str = cfg.get("container_name", "moneyprinter-videos")
        self.delete_local_after_upload: bool = cfg.get("delete_local_after_upload", True)
        self.upload_combined_videos: bool = cfg.get("upload_combined_videos", False)
        self._client: Optional["BlobServiceClient"] = None

    def is_configured(self) -> bool:
        return bool(self.enabled and self.connection_string and self.container_name)

    def _get_client(self) -> "BlobServiceClient":
        if self._client is None:
            if not _AZURE_BLOB_AVAILABLE:
                raise ImportError(
                    "azure-storage-blob is not installed. "
                    "Run: pip install azure-storage-blob"
                )
            self._client = BlobServiceClient.from_connection_string(self.connection_string)
        return self._client

    def upload_file(self, local_path: str, blob_name: str) -> Optional[str]:
        """Upload a local file to Azure Blob Storage and return its URL."""
        if not self.is_configured():
            return None

        if not os.path.exists(local_path):
            logger.error(f"File not found for Azure upload: {local_path}")
            return None

        try:
            client = self._get_client()
            container_client = client.get_container_client(self.container_name)

            try:
                container_client.get_container_properties()
            except Exception:
                container_client.create_container()
                logger.info(f"Created Azure Blob container: {self.container_name}")

            blob_client = container_client.get_blob_client(blob_name)
            content_settings = ContentSettings(content_type="video/mp4")

            file_size = os.path.getsize(local_path)
            logger.info(
                f"Uploading {os.path.basename(local_path)} "
                f"({file_size / 1024 / 1024:.1f} MB) → "
                f"azure://{self.container_name}/{blob_name}"
            )

            with open(local_path, "rb") as data:
                blob_client.upload_blob(
                    data,
                    overwrite=True,
                    content_settings=content_settings,
                )

            url = blob_client.url
            logger.success(f"Uploaded to Azure Blob Storage: {url}")
            return url

        except Exception as e:
            logger.error(f"Failed to upload {local_path} to Azure Blob Storage: {e}")
            return None

    def upload_task_videos(
        self,
        task_id: str,
        final_video_paths: list[str],
        combined_video_paths: list[str],
    ) -> dict[str, list[str]]:
        """
        Upload generated videos to Azure Blob Storage.

        Returns a dict with 'final_urls' and 'combined_urls' lists.
        Local files are deleted after a successful upload when
        delete_local_after_upload is enabled.
        """
        if not self.is_configured():
            return {"final_urls": [], "combined_urls": []}

        final_urls: list[str] = []
        combined_urls: list[str] = []

        def _upload_and_optionally_delete(local_path: str, blob_name: str) -> Optional[str]:
            url = self.upload_file(local_path, blob_name)
            if url and self.delete_local_after_upload:
                try:
                    os.remove(local_path)
                    logger.debug(f"Deleted local file after upload: {local_path}")
                except OSError as e:
                    logger.warning(f"Could not delete local file {local_path}: {e}")
            return url

        for path in final_video_paths:
            filename = os.path.basename(path)
            blob_name = f"{task_id}/{filename}"
            url = _upload_and_optionally_delete(path, blob_name)
            if url:
                final_urls.append(url)

        if self.upload_combined_videos:
            for path in combined_video_paths:
                filename = os.path.basename(path)
                blob_name = f"{task_id}/{filename}"
                url = _upload_and_optionally_delete(path, blob_name)
                if url:
                    combined_urls.append(url)

        return {"final_urls": final_urls, "combined_urls": combined_urls}


azure_blob_storage_service = AzureBlobStorageService()
