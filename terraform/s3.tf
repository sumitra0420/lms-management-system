resource "aws_s3_bucket" "uploads" {
  bucket = "${var.project_name}-uploads"

  tags = {
    Project = var.project_name
  }
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_cors_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT", "POST", "GET"]
    allowed_origins = ["http://localhost:4200", "https://lms-management-system.pages.dev"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

resource "aws_iam_policy" "s3" {
  name        = "${var.project_name}-s3-policy"
  description = "Allow LMS backend to read/write S3 uploads bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.uploads.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.uploads.arn
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "s3" {
  user       = aws_iam_user.bedrock.name
  policy_arn = aws_iam_policy.s3.arn
}
