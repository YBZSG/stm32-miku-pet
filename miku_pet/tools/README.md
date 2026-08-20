# Miku pet asset converter

`convert_pet.py` converts a Codex v2 8x11 pet atlas into an RGB565 RLE package
that can be streamed from the board's W25Q64 flash to the ILI9341 LCD.

The generated package starts with an `MPET` header, followed by one frame-table
entry per animation frame and the compressed frame payloads. Transparent pixels
are composited onto `#F5F7FA` before encoding, matching the firmware background.

`codex_pet_bridge.ps1` maps Codex activity and the explicit runtime state file to
USART animation commands. The local session-log follower is a compatibility
integration, not a public OpenAI event API. Writing `idle`, `working`, `waiting`,
`review`, `failed`, `wave`, or `jump` to `runtime/codex_pet_state.txt` provides a
stable explicit override.
