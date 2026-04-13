"""
Media storage helpers.
Cloudinary is the primary provider for photo uploads.
Legacy S3 helpers remain available for voice/video migration paths if needed later.
"""
from __future__ import annotations

import uuid

import boto3
import cloudinary
import cloudinary.api
import cloudinary.uploader
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime"}
ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/ogg", "audio/webm", "audio/mp4"}

MAX_PHOTO_SIZE_MB = 10
MAX_VIDEO_SIZE_MB = 100
MAX_AUDIO_SIZE_MB = 5


_cloudinary_configured = False


def _configure_cloudinary() -> None:
    global _cloudinary_configured
    if _cloudinary_configured:
        return

    if not (
        settings.CLOUDINARY_CLOUD_NAME
        and settings.CLOUDINARY_API_KEY
        and settings.CLOUDINARY_API_SECRET
    ):
        raise RuntimeError("Cloudinary is not configured")

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    _cloudinary_configured = True


def generate_photo_upload_signature(
    tenant_slug: str,
    user_id: str,
    file_extension: str,
) -> dict[str, str | int]:
    """
    Generate signed upload parameters for direct client -> Cloudinary photo upload.
    Returns the data the client needs to POST multipart/form-data to Cloudinary.
    """
    _configure_cloudinary()

    timestamp = cloudinary.utils.now()
    file_id = uuid.uuid4().hex
    folder = f"{settings.CLOUDINARY_UPLOAD_FOLDER}/{tenant_slug}/{user_id}/photos"
    public_id = f"{folder}/{file_id}"

    params_to_sign = {
        "folder": folder,
        "public_id": public_id,
        "timestamp": timestamp,
        "overwrite": False,
        "resource_type": "image",
    }
    signature = cloudinary.utils.api_sign_request(params_to_sign, settings.CLOUDINARY_API_SECRET)
    secure_url = cloudinary.CloudinaryImage(public_id).build_url(secure=True, format=file_extension)

    return {
        "upload_url": f"https://api.cloudinary.com/v1_1/{settings.CLOUDINARY_CLOUD_NAME}/image/upload",
        "api_key": settings.CLOUDINARY_API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "folder": folder,
        "public_id": public_id,
        "cloud_name": settings.CLOUDINARY_CLOUD_NAME,
        "resource_type": "image",
        "url": secure_url,
        "key": public_id,
    }


def delete_photo(key: str) -> None:
    _configure_cloudinary()
    try:
        cloudinary.uploader.destroy(key, resource_type="image", invalidate=True)
        logger.info("cloudinary_photo_deleted", key=key)
    except Exception as exc:
        logger.error("cloudinary_delete_failed", error=str(exc), key=key)
        raise RuntimeError("Could not delete photo") from exc


# Legacy S3 helpers kept for non-photo flows during migration.
def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


def generate_upload_url(
    tenant_slug: str,
    user_id: str,
    media_type: str,
    content_type: str,
    file_extension: str,
) -> dict[str, str]:
    file_id = uuid.uuid4().hex
    s3_key = f"{tenant_slug}/{user_id}/{media_type}/{file_id}.{file_extension}"

    try:
        s3 = _s3_client()
        url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.AWS_S3_BUCKET,
                "Key": s3_key,
                "ContentType": content_type,
            },
            ExpiresIn=600,
        )
    except ClientError as exc:
        logger.error("s3_presign_failed", error=str(exc), key=s3_key)
        raise RuntimeError("Could not generate upload URL") from exc

    cdn_url = f"{settings.media_base_url}/{s3_key}"
    return {"upload_url": url, "s3_key": s3_key, "cdn_url": cdn_url}


def delete_media(s3_key: str) -> None:
    try:
        s3 = _s3_client()
        s3.delete_object(Bucket=settings.AWS_S3_BUCKET, Key=s3_key)
        logger.info("media_deleted", key=s3_key)
    except ClientError as exc:
        logger.error("s3_delete_failed", error=str(exc), key=s3_key)
