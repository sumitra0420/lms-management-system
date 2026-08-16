import os
import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()


def _s3():
    region = os.getenv("AWS_REGION", "ap-southeast-2")
    endpoint_url = os.getenv("S3_ENDPOINT_URL") or None
    return boto3.client(
        "s3",
        region_name=region,
        endpoint_url=endpoint_url,
        config=Config(
            signature_version="s3v4",
             s3={"addressing_style": "path" if endpoint_url else "virtual"},
        ),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def generate_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    return _s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket":      os.getenv("S3_BUCKET"),
            "Key":         s3_key,
            "ContentType": "application/octet-stream",
        },
        ExpiresIn=expires_in,
    )


def download_file(s3_key: str) -> bytes:
    response = _s3().get_object(Bucket=os.getenv("S3_BUCKET"), Key=s3_key)
    return response["Body"].read()
