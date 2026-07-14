resource "aws_iam_user" "bedrock" {
  name = "${var.project_name}-bedrock-user"

  tags = {
    Project = var.project_name
  }
}

resource "aws_iam_user_policy_attachment" "bedrock" {
  user       = aws_iam_user.bedrock.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonBedrockFullAccess"
}

resource "aws_iam_access_key" "bedrock" {
  user = aws_iam_user.bedrock.name
}
