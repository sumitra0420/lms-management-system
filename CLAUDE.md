# requirement/

This directory contains the current system architechture design. The diagram might be changes. Please build the system based on this requirement.

# data/

This directory contains reference projects only. Do not modify, build upon, or treat as part of the LMS management system implementation.

## Contents

- `customer-tech-enquiry-analysis/` — Sample Angular app used as a reference for patterns and structure.
- `LearningManagementSystem/` — Reference project for LMS domain concepts.

## Usage

These projects exist for reading and learning from. When building the actual LMS system, refer to `frontend/` and `backend/` in the repo root instead.

## AWS Accounts

Account ID: `150105759741`

| Profile     | IAM User                    | Purpose                              |
|-------------|-----------------------------|--------------------------------------|
| `lms-admin` | `lms-admin`                 | Terraform only (AdministratorAccess) |
| `lms`       | `lms-management-bedrock-user` | App runtime (Bedrock + S3)         |

Terraform uses `lms-admin` profile. FastAPI backend uses `.env` keys directly (not CLI profile).

## Git Commit
When finishing a task, provide git comment in details (max 4 lines)
