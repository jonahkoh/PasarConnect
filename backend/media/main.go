// Media Service — presigned S3 upload URL generator.
//
// Single endpoint:
//   POST /presign  { "filename": "photo.jpg", "content_type": "image/jpeg" }
//   → { "upload_url": "https://...presigned...", "public_url": "https://bucket.s3.region.amazonaws.com/listings/..." }
//
// Auth: Kong JWT plugin verifies the RS256 Bearer token before the request reaches this service.
// The service itself trusts Kong and does not re-verify the token.
//
// Upload flow (browser):
//   1. JS calls POST /api/media/presign  (through Vite proxy → Kong → this service)
//   2. JS PUTs the file directly to upload_url  (direct to S3, no traffic through our backend)
//   3. JS stores public_url in the listing form → sent to listing-service on submit

package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// ── Request / Response types ──────────────────────────────────────────────────

type presignRequest struct {
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
}

type presignResponse struct {
	UploadURL string `json:"upload_url"`
	PublicURL string `json:"public_url"`
}

type errorResponse struct {
	Error string `json:"error"`
}

// ── Allowed image MIME types ──────────────────────────────────────────────────

var allowedContentTypes = map[string]bool{
	"image/jpeg": true,
	"image/jpg":  true,
	"image/png":  true,
	"image/webp": true,
	"image/gif":  true,
	"image/heic": true,
	"image/heif": true,
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// ── Main ──────────────────────────────────────────────────────────────────────

func main() {
	bucket    := os.Getenv("AWS_S3_BUCKET")
	region    := os.Getenv("AWS_REGION")
	accessKey := os.Getenv("AWS_ACCESS_KEY_ID")
	secretKey := os.Getenv("AWS_SECRET_ACCESS_KEY")
	port      := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	// Build AWS config from explicit credentials (env-vars injected by Docker).
	cfg, err := config.LoadDefaultConfig(context.Background(),
		config.WithRegion(region),
		config.WithCredentialsProvider(
			credentials.NewStaticCredentialsProvider(accessKey, secretKey, ""),
		),
	)
	if err != nil {
		log.Fatalf("failed to load AWS config: %v", err)
	}

	s3Client      := s3.NewFromConfig(cfg)
	presignClient := s3.NewPresignClient(s3Client)

	mux := http.NewServeMux()

	// ── GET /health ──────────────────────────────────────────────────────────
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})

	// ── POST /presign ─────────────────────────────────────────────────────────
	mux.HandleFunc("/presign", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
			return
		}

		var req presignRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeJSON(w, http.StatusBadRequest, errorResponse{Error: "invalid JSON body"})
			return
		}

		if strings.TrimSpace(req.Filename) == "" {
			writeJSON(w, http.StatusBadRequest, errorResponse{Error: "filename is required"})
			return
		}
		if !allowedContentTypes[req.ContentType] {
			writeJSON(w, http.StatusBadRequest, errorResponse{
				Error: "content_type must be an image (jpeg, png, webp, gif, heic)",
			})
			return
		}

		// Build a safe S3 key: strip directory traversal, normalise spaces.
		safe := filepath.Base(req.Filename)
		safe  = strings.ReplaceAll(safe, " ", "_")
		key  := fmt.Sprintf("listings/%d_%s", time.Now().UnixMilli(), safe)

		// Generate a 5-minute presigned PUT URL.
		result, err := presignClient.PresignPutObject(
			context.Background(),
			&s3.PutObjectInput{
				Bucket:      aws.String(bucket),
				Key:         aws.String(key),
				ContentType: aws.String(req.ContentType),
			},
			func(opts *s3.PresignOptions) {
				opts.Expires = 5 * time.Minute
			},
		)
		if err != nil {
			log.Printf("presign error: %v", err)
			writeJSON(w, http.StatusInternalServerError, errorResponse{Error: "failed to generate upload URL"})
			return
		}

		// Virtual-hosted URL: https://<bucket>.s3.<region>.amazonaws.com/<key>
		publicURL := fmt.Sprintf("https://%s.s3.%s.amazonaws.com/%s", bucket, region, key)

		writeJSON(w, http.StatusOK, presignResponse{
			UploadURL: result.URL,
			PublicURL: publicURL,
		})
	})

	log.Printf("media-service listening on :%s  (bucket: %s, region: %s)", port, bucket, region)
	if err := http.ListenAndServe(":"+port, mux); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
