# Attachments API

File upload and download endpoints using token-based URLs. Each upload generates a unique, unguessable token that grants access to the file.

## Upload

```
POST /attachments
Authorization: Bearer <jwt>  (if auth enabled)
Content-Type: multipart/form-data
```

### Request

```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);

const res = await fetch('/attachments', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`  // if auth enabled
  },
  body: formData
});
```

### Response

```json
{
  "url": "https://example.com/attachments/E6X2eRE1oeIInSWvqgCrvLxVT5KFIM802Ud8soXcazI/photo.png"
}
```

The URL includes:
- Full base URL (for external services like OpenAI to fetch)
- Unique token (256-bit, unguessable)
- URL-encoded filename

## Download

Use the URL returned from upload directly. No authentication required.

```javascript
const res = await fetch(uploadResponse.url);
const blob = await res.blob();
```

### Errors

| Status | Description |
|--------|-------------|
| 401 | Missing or invalid JWT (upload only, if auth enabled) |
| 404 | File not found or invalid token |

## Notes

- Upload requires auth (if enabled), download does not
- Token-based URLs are shareable with external services (AI providers, CDNs)
- Storage location: `/workspace/attachments/{token}/`
- Filenames are URL-encoded to handle spaces and special characters
