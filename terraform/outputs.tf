output "aws_access_key_id" {
  description = "Copy into backend/.env as AWS_ACCESS_KEY_ID"
  value       = aws_iam_access_key.bedrock.id
}

output "aws_secret_access_key" {
  description = "Copy into backend/.env as AWS_SECRET_ACCESS_KEY"
  value       = aws_iam_access_key.bedrock.secret
  sensitive   = true
}

output "s3_bucket_name" {
  description = "Copy into backend/.env as S3_BUCKET"
  value       = aws_s3_bucket.uploads.bucket
}
