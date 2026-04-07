/**
 * Media Service API client.
 *
 * Upload flow for a vendor listing photo:
 *   1. Call getPresignedUrl(file.name, file.type, token)
 *      → backend generates a 5-min presigned S3 PUT URL and the final public URL.
 *   2. Call uploadToS3(file, uploadUrl, onProgress)
 *      → browser PUTs the file directly to S3 (no traffic through our backend).
 *   3. Use publicUrl as the listing image_url.
 */

/**
 * Ask the media service for a presigned S3 PUT URL.
 * @param {string} filename      Original filename (e.g. "photo.jpg")
 * @param {string} contentType   MIME type (e.g. "image/jpeg")
 * @param {string} token         Bearer JWT from sessionStorage
 * @returns {Promise<{ upload_url: string, public_url: string }>}
 */
export async function getPresignedUrl(filename, contentType, token) {
  const res = await fetch("/api/media/presign", {
    method: "POST",
    headers: {
      "Content-Type":  "application/json",
      "Authorization": `Bearer ${token}`,
    },
    body: JSON.stringify({ filename, content_type: contentType }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Presign request failed (${res.status})`);
  }

  return res.json();
}

/**
 * Upload a File directly to S3 using a presigned PUT URL.
 * Uses XMLHttpRequest so upload progress can be tracked.
 *
 * @param {File}     file          The image File object from the browser input
 * @param {string}   uploadUrl     Presigned PUT URL from getPresignedUrl()
 * @param {Function} [onProgress]  Called with 0–100 as bytes upload
 * @returns {Promise<void>}
 */
export function uploadToS3(file, uploadUrl, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", uploadUrl);
    // Content-Type must exactly match the value used when presigning.
    xhr.setRequestHeader("Content-Type", file.type);

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
    }

    xhr.onload = () => {
      // S3 returns 200 on a successful presigned PUT.
      if (xhr.status === 200) {
        resolve();
      } else {
        reject(new Error(`S3 upload failed (HTTP ${xhr.status})`));
      }
    };

    xhr.onerror = () => reject(new Error("Upload network error — check your connection."));
    xhr.ontimeout = () => reject(new Error("Upload timed out."));
    xhr.timeout = 60_000; // 60 s max

    xhr.send(file);
  });
}
