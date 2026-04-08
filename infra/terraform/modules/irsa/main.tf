# =============================================================================
# IRSA — IAM Roles for Service Accounts
#
# Creates a scoped IAM role for the media service that allows only:
#   s3:PutObject, s3:GetObject, s3:DeleteObject on the media bucket.
#
# The role is bound to a specific Kubernetes ServiceAccount via the
# OIDC trust relationship, so no other pod can assume it.
#
# How it works:
#   1. Terraform creates IAM role with OIDC trust policy.
#   2. The Kubernetes ServiceAccount is annotated with the role ARN (Batch 3).
#   3. The AWS SDK in the container calls sts:AssumeRoleWithWebIdentity
#      using the projected ServiceAccount token — no static credentials needed.
# =============================================================================

locals {
  name         = "${var.project}-${var.environment}"
  oidc_issuer  = replace(var.cluster_oidc_issuer_url, "https://", "")
}

# ── Media Service — S3 upload/download role ───────────────────────────────────

data "aws_iam_policy_document" "media_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:sub"
      # Scoped to the exact ServiceAccount in the exact namespace — principle of least privilege.
      values   = ["system:serviceaccount:${var.media_service_namespace}:${var.media_service_account_name}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "media_service" {
  name               = "${local.name}-media-service-irsa"
  assume_role_policy = data.aws_iam_policy_document.media_assume.json

  tags = { Name = "${local.name}-media-service-irsa" }
}

resource "aws_iam_role_policy" "media_s3" {
  name = "${local.name}-media-s3-policy"
  role = aws_iam_role.media_service.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "MediaBucketObjectAccess"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
        ]
        # Scoped to the specific bucket — not s3:* on "*".
        Resource = "${var.media_bucket_arn}/*"
      },
      {
        Sid    = "MediaBucketList"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = var.media_bucket_arn
      }
    ]
  })
}

# ── Notification + Auditor Services — Amazon MQ access ───────────────────────
# These services connect to Amazon MQ via AMQPS with username/password
# (stored as Kubernetes Secrets in Batch 3). No additional IRSA needed.
# If you later switch to IAM-based MQ auth, add a role here.

# ── CloudWatch Logs — Fluent Bit DaemonSet ────────────────────────────────────
# Allows aws-for-fluent-bit to ship container logs to CloudWatch without
# embedding static credentials in the DaemonSet.

data "aws_iam_policy_document" "fluent_bit_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:sub"
      values   = ["system:serviceaccount:amazon-cloudwatch:fluent-bit"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fluent_bit" {
  name               = "${local.name}-fluent-bit-irsa"
  assume_role_policy = data.aws_iam_policy_document.fluent_bit_assume.json

  tags = { Name = "${local.name}-fluent-bit-irsa" }
}

resource "aws_iam_role_policy_attachment" "fluent_bit_cw" {
  role       = aws_iam_role.fluent_bit.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}
