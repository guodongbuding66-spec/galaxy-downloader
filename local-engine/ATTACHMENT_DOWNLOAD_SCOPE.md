# Course attachment download trust boundary

This internal note documents the backend boundary introduced for authorized course attachments.

- Public callers supply only the local `attachmentId` and a bounded browser-cookie source (`none`, `edge`, `chrome`, `firefox`, `brave`).
- Provider course, lecture, and asset identifiers remain internal Learning state.
- The provider download URL is resolved only for the active job, validated as public HTTP(S), and is never persisted or returned by Headless APIs.
- Files are streamed into a `.part` file under the Galaxy download root, capped at 2 GiB, fsynced, and atomically renamed only after success.
- Cancellation removes partial files.
- Public Learning reads expose only `downloaded` and `sizeBytes`; local paths and provider identities remain private.
- DRM bypass is not implemented.
