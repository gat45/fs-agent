"""Support cloud pour le scan de fichiers (S3, Azure, GCS).

Dependencies optionnelles:
- boto3 (S3)
- azure-storage-blob (Azure)
- google-cloud-storage (GCS)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, List, Dict

# Essayer d'importer les SDK cloud (optionnels)
try:
    import boto3
    HAS_S3 = True
except ImportError:
    HAS_S3 = False

try:
    from azure.storage.blob import BlobServiceClient
    HAS_AZURE = True
except ImportError:
    HAS_AZURE = False

try:
    from google.cloud import storage as gcs_storage
    HAS_GCS = True
except ImportError:
    HAS_GCS = False


def list_s3_files(bucket: str, prefix: str = "", max_files: int = 100000) -> List[Dict]:
    """Liste les fichiers d'un bucket S3."""
    if not HAS_S3:
        raise ImportError("boto3 non installe. pip install boto3")
    try:
        s3 = boto3.client("s3")
    except Exception as e:
        raise RuntimeError(f"Erreur de connexion S3: {e}")
    files = []
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                files.append({
                    "path": f"s3://{bucket}/{obj['Key']}",
                    "size": obj["Size"],
                    "mtime": obj["LastModified"].timestamp(),
                    "ext": os.path.splitext(obj["Key"])[1].lower(),
                })
                if len(files) >= max_files:
                    return files
    except Exception as e:
        raise RuntimeError(f"Erreur lors du listing S3: {e}")
    return files


def list_azure_files(container_url: str, prefix: str = "", max_files: int = 100000) -> List[Dict]:
    """Liste les fichiers d'un container Azure Blob."""
    if not HAS_AZURE:
        raise ImportError("azure-storage-blob non installe. pip install azure-storage-blob")
    client = BlobServiceClient(account_url=container_url)
    container = client.get_container_client(container_url.split("/")[-1])
    files = []
    for blob in container.list_blobs(name_starts_with=prefix):
        files.append({
            "path": f"azure://{container_url}/{blob.name}",
            "size": blob.size,
            "mtime": blob.last_modified.timestamp() if blob.last_modified else 0,
            "ext": os.path.splitext(blob.name)[1].lower(),
        })
        if len(files) >= max_files:
            return files
    return files


def list_gcs_files(bucket_name: str, prefix: str = "", max_files: int = 100000) -> List[Dict]:
    """Liste les fichiers d'un bucket GCS."""
    if not HAS_GCS:
        raise ImportError("google-cloud-storage non installe. pip install google-cloud-storage")
    client = gcs_storage.Client()
    bucket = client.bucket(bucket_name)
    files = []
    for blob in bucket.list_blobs(prefix=prefix):
        files.append({
            "path": f"gs://{bucket_name}/{blob.name}",
            "size": blob.size,
            "mtime": blob.updated.timestamp() if blob.updated else 0,
            "ext": os.path.splitext(blob.name)[1].lower(),
        })
        if len(files) >= max_files:
            return files
    return files


def available_providers() -> Dict[str, bool]:
    """Retourne les providers cloud disponibles."""
    return {
        "s3": HAS_S3,
        "azure": HAS_AZURE,
        "gcs": HAS_GCS,
    }