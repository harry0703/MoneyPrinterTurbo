# Inspect artifact metadata

The artifact endpoints accept `HEAD` as well as `GET`:

```sh
curl --head http://localhost:8080/api/v1/stream/TASK_ID/final-1.mp4
curl --head http://localhost:8080/api/v1/download/TASK_ID/final-1.mp4
```

HEAD returns the full artifact's content length and media type without sending
its bytes. Downloads also return the existing attachment filename and file
metadata headers. Supply the same authentication as GET when an API key is
configured. Missing files and paths outside task storage retain their existing
error statuses. Range and If-Range do not select partial representations for
HEAD; send GET with Range to retrieve part of a stream. An empty artifact has
length zero. A successful metadata request does not validate video decoding or
guarantee that a subsequent request will see the same file.
