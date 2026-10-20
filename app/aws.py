"""AWS integration: S3 (storage) and SNS (notifications).

Credentials are never stored in code. On EC2 boto3 picks them up
automatically from the IAM role attached to the instance; on a laptop
it uses `aws configure`. If S3_BUCKET / SNS_TOPIC_ARN are not set the
app still works locally and these functions simply do nothing.
"""

import logging
import os

log = logging.getLogger(__name__)


def _region():
    return os.getenv("AWS_REGION", "ap-southeast-2")


def _client(service):
    import boto3
    return boto3.client(service, region_name=_region())


def s3_enabled() -> bool:
    return bool(os.getenv("S3_BUCKET"))


def sns_enabled() -> bool:
    return bool(os.getenv("SNS_TOPIC_ARN"))


def split_s3_url(url: str):
    """'s3://bucket/path/file.csv' -> ('bucket', 'path/file.csv')"""
    rest = url[len("s3://"):]
    bucket, _, key = rest.partition("/")
    return bucket, key


def read_s3_bytes(url: str) -> bytes:
    bucket, key = split_s3_url(url)
    return _client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()


def upload_bytes(key: str, data: bytes, content_type: str = "text/csv"):
    """Store a file in the project bucket. Returns the key, or None if S3 is off/failed."""
    if not s3_enabled():
        return None
    try:
        _client("s3").put_object(Bucket=os.environ["S3_BUCKET"], Key=key, Body=data,
                                 ContentType=content_type, ServerSideEncryption="AES256")
        return key
    except Exception:
        log.exception("S3 upload failed for %s", key)
        return None


def download_bytes(key: str):
    if not s3_enabled():
        return None
    try:
        return _client("s3").get_object(Bucket=os.environ["S3_BUCKET"], Key=key)["Body"].read()
    except Exception:
        log.exception("S3 download failed for %s", key)
        return None


def notify(subject: str, message: str) -> bool:
    """Publish to the SNS topic (recruiters subscribed by email get it). Returns True if sent."""
    if not sns_enabled():
        return False
    try:
        _client("sns").publish(TopicArn=os.environ["SNS_TOPIC_ARN"],
                               Subject=subject[:100], Message=message)
        return True
    except Exception:
        log.exception("SNS publish failed")
        return False
