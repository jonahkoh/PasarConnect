# =============================================================================
# S3 — Media bucket for food listing images
# - Public access blocked at bucket level (images served via pre-signed URLs)
# - Versioning enabled for accidental-deletion recovery
# - Server-side encryption with AWS-managed keys (SSE-S3)
# - CORS configured for direct browser uploads via pre-signed POST
# =============================================================================

locals {
  name = "${var.project}-${var.environment}"
}

resource "aws_s3_bucket" "media" {
  bucket = var.media_bucket_name

  tags = { Name = var.media_bucket_name }
}

# Block ALL public access — images are accessed via pre-signed URLs only.
resource "aws_s3_bucket_public_access_block" "media" {
  bucket = aws_s3_bucket.media.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "media" {
  bucket = aws_s3_bucket.media.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# CORS: allow the frontend (Vercel) to PUT objects directly using pre-signed URLs.
resource "aws_s3_bucket_cors_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST"]
    allowed_origins = ["https://*.vercel.app", "http://localhost:5173"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# Lifecycle: move objects older than 90 days to S3 Intelligent-Tiering to reduce cost.
resource "aws_s3_bucket_lifecycle_configuration" "media" {
  bucket = aws_s3_bucket.media.id

  rule {
    id     = "intelligent-tiering"
    status = "Enabled"

    filter {}

    transition {
      days          = 90
      storage_class = "INTELLIGENT_TIERING"
    }
  }
}
