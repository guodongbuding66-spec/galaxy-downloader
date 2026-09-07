# Learning progress sync contract

The Web Learning player persists only the public course-item ID, playback position, and completion state through the existing authenticated Learning progress endpoint.

Behavior:

- ordinary playback updates are throttled to 10-second movement intervals;
- seek and pause force a save;
- lesson completion is persisted before the player advances to the next resume target;
- a failed completion save does not falsely advance the course;
- course/view changes flush the current position;
- hidden-page and unload flushes use authenticated `fetch(..., keepalive: true)` rather than `sendBeacon`;
- no local filesystem path, provider credential, cookie path, or bearer token is placed in a media URL.
