# Codex Pet Dashboard Protocol v1

The dashboard uses one authoritative snapshot per Codex session.

- `session_id` changes when the Codex task changes.
- `sequence` increases for every generated snapshot.
- The device must reject a lower/equal sequence for the same session.
- A different session replaces all title/state fields atomically.
- On RESET the device requests a full snapshot; it never restores a cached title.
- Title/state come from `user_message`, `task_started`, `task_complete`, and
  `turn_aborted`. Token/rate-limit events only update usage fields.

Transport packets will carry the snapshot identity, payload length, and CRC32.
USB HID is the primary transport; the CH340 COM bridge is not used.
