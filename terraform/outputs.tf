output "aws_access_key_id" {
  description = "Copy this into backend/.env as AWS_ACCESS_KEY_ID"
  value       = aws_iam_access_key.bedrock.id
}

output "aws_secret_access_key" {
  description = "Copy this into backend/.env as AWS_SECRET_ACCESS_KEY"
  value       = aws_iam_access_key.bedrock.secret
  sensitive   = true
}
