# Files API — Frontend Guide

Upload, view, and manage files through the `/files` API. All endpoints are JWT-authenticated and user-scoped — files live in `/workspace/{user_id}` (or `/workspace/{org_id}`).

## Upload

```js
async function upload(file, token) {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`/files/${file.name}`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });
  return res.json(); // { ok: true }
}
```

Subdirectories work too — `PUT /files/images/photo.jpg` creates the `images/` folder automatically.

## Send in chat

After uploading, reference the file by name in the message content:

```js
const message = {
  role: "user",
  content: [
    { type: "text", text: "What's in this image?" },
    { type: "image", image: "photo.jpg" },
  ],
};
```

For non-image files:

```js
{ type: "file", file: "report.pdf" }
```

The backend reads the file directly from the user's workspace — no extra copying or token resolution.

## View

`GET /files/{path}` returns the raw file with the correct `Content-Type`, so the browser handles rendering natively.

### Images

```js
async function imageURL(path, token) {
  const res = await fetch(`/files/${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

// Usage
const url = await imageURL("photo.jpg", token);
img.src = url;
```

### PDFs

```js
const url = await imageURL("report.pdf", token);
// <iframe src={url} /> or <embed src={url} />
```

### Video / Audio

```js
const url = await imageURL("demo.mp4", token);
// <video src={url} controls />

const audioUrl = await imageURL("clip.mp3", token);
// <audio src={audioUrl} controls />
```

### Any file (download)

Add `?download` to trigger a `Content-Disposition: attachment` header:

```js
window.open(`/files/data.csv?download`);
```

## List files

```js
const res = await fetch("/files?path=images", {
  headers: { Authorization: `Bearer ${token}` },
});
const items = await res.json();
// [{ name: "photo.jpg", type: "file", size: 204800, modified: "..." }, ...]
```

Omit `?path=` to list the workspace root. Hidden files (dotfiles) are excluded.

## Other operations

| Operation | Method | Path |
|-----------|--------|------|
| Create directory | `POST` | `/files/{path}` |
| Rename / move | `PATCH` | `/files/{path}` with `{ "to": "new/path" }` |
| Delete | `DELETE` | `/files/{path}` |

## Cleanup

Revoke blob URLs when no longer needed to free memory:

```js
URL.revokeObjectURL(url);
```
