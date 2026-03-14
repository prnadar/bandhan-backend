"""
S3 storage service — pre-signed URLs for photo/video/voice uploads.
All media goes through CloudFront CDN for delivery.
"""
import uuid

import boto3
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
    media_type: str,  # "photo" | "video" | "voice"
    content_type: str,
    file_extension: str,
) -> dict[str, str]:
    """
    Generate a pre-signed PUT URL for direct browser → S3 upload.
    Returns {upload_url, s3_key, cdn_url}
    """
    file_id = uuid.uuid4().hex
    s3_key = f"{tenant_slug}/{user_id}/{media_type}/{file_id}.{file_extension}"

    max_bytes_map = {
        "photo": MAX_PHOTO_SIZE_MB * 1024 * 1024,
        "video": MAX_VIDEO_SIZE_MB * 1024 * 1024,
        "voice": MAX_AUDIO_SIZE_MB * 1024 * 1024,
    }

    try:
        s3 = _s3_client()
        url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.AWS_S3_BUCKET,
                "Key": s3_key,
                "ContentType": content_type,
            },
            ExpiresIn=600,  # 10 minutes
        )
    except ClientError as exc:
        logger.error("s3_presign_failed", error=str(exc), key=s3_key)
        raise RuntimeError("Could not generate upload URL") from exc

    cdn_url = f"{settings.media_base_url}/{s3_key}"
    return {"upload_url": url, "s3_key": s3_key, "cdn_url": cdn_url}


def delete_media(s3_key: str) -> None:
    """Hard-delete a media object from S3."""
    try:
        s3 = _s3_client()
        s3.delete_object(Bucket=settings.AWS_S3_BUCKET, Key=s3_key)
        logger.info("media_deleted", key=s3_key)
    except ClientError as exc:
        logger.error("s3_delete_failed", error=str(exc), key=s3_key)
