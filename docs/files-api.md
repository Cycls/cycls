# Files API

User-scoped file upload and download endpoints. Files are stored at `/workspace/{user_id}/files/` and only accessible by the authenticated user.

## Upload

```
POST /files
Authorization: Bearer <jwt>
Content-Type: multipart/form-data
```

### Request

```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);

const res = await fetch('/files', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`
  },
  body: formData
});
```

### Response

```json
{
  "url": "/files/photo.png"
}
```

## Download

```
GET /files/{filename}
Authorization: Bearer <jwt>
```

### Request

```javascript
const res = await fetch('/files/photo.png', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
});

const blob = await res.blob();
const url = URL.createObjectURL(blob);
```

### Errors

| Status | Description |
|--------|-------------|
| 401 | Missing or invalid JWT |
| 404 | File not found |

## Notes

- Files are scoped to the authenticated user (extracted from JWT)
- The returned URL requires the same JWT to access
- Storage location: `/workspace/{user_id}/files/`
