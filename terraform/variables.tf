variable "aws_region" {
  description = "AWS region"
  default     = "ap-southeast-2"
}

variable "aws_profile" {
  description = "AWS CLI profile to use"
  default     = "lms-admin"
}

variable "project_name" {
  description = "Project name prefix for all resources"
  default     = "lms-management"
}
