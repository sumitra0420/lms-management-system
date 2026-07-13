resource "aws_iam_user" "bedrock" {
  name = "${var.project_name}-bedrock-user"

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_policy" "bedrock" {
  name        = "${var.project_name}-bedrock-policy"
  description = "Allow LMS backend to invoke Bedrock models"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_user_policy_attachment" "bedrock" {
  user       = aws_iam_user.bedrock.name
  policy_arn = aws_iam_policy.bedrock.arn
}

resource "aws_iam_access_key" "bedrock" {
  user = aws_iam_user.bedrock.name
}
