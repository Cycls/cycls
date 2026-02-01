# Attachments API

User-scoped file upload and download endpoints. Files are stored at `/workspace/{user_id}/attachments/` and only accessible by the authenticated user.

## Upload

```
POST /attachments
Authorization: Bearer <jwt>
Content-Type: multipart/form-data
```

### Request

```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);

const res = await fetch('/attachments', {
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
  "url": "/attachments/photo.png"
}
```

## Download

```
GET /attachments/{filename}
Authorization: Bearer <jwt>
```

### Request

```javascript
const res = await fetch('/attachments/photo.png', {
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
- Storage location: `/workspace/{user_id}/attachments/`
