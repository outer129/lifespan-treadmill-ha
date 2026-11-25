# LifeSpan Treadmill (SC110 / Omni console) for Home Assistant

Custom integration that reads a LifeSpan treadmill console over Bluetooth LE using
Home Assistant's own Bluetooth stack, so it works through a local adapter **or an
ESPHome Bluetooth proxy** (the proxy must have `active: true`).

## Entities
| Entity | Notes |
|---|---|
| Status | standby / running / paused / summary |
| Running (binary) | on while the belt is moving |
| Speed | mph or km/h (whatever the console displays); 0 when not running |
| Distance | current session, mi or km |
| Steps | current session |
| Session time | current session |
| Calories | current session (kcal) |
| Session (event) | fires `session_completed` with started, ended, duration_s, steps, distance, calories, average_speed |
| Last session ended / duration / steps / distance / calories / average speed | values from the most recent completed session; kept across restarts |
| Connectivity (diagnostic) | whether HA holds the BLE link; `adapter` attribute names the proxy in use |
| Signal strength (diagnostic) | RSSI, disabled by default |

The device's firmware, hardware and serial number come from the console's standard
Device Information Service, if it has one. **Download diagnostics** on the integration page dumps the
current state, which is useful when reporting a decoding issue.

Each sensor also has a `raw_frame` attribute with the last reply from the console, which helps check the decoding.

**Read-only.** Nobody has found a way to start, stop or set the speed over BLE.

The console accepts only **one** Bluetooth connection, so the LifeSpan Fit app
can't connect while Home Assistant holds the connection. To use the app, disable the integration entry first.

## Sessions and history
- Steps, distance, calories and session time are the console's **per-session** counters,
  marked `total_increasing`. When a new session resets them, HA's long-term statistics
  treat the drop as a meter reset, so lifetime sums and Utility Meter helpers
  (daily, weekly, monthly) keep adding up correctly.
- **Glitch guard:** the console's replies don't name the request they answer, so a late reply
  could be read as the wrong field. Late replies are dropped after a timeout. A counter
  *dropping* is accepted only once two reads in a row agree, so one bad read can't look
  like a reset and double-count a session.
- **Session tracking:** a session opens when *running* is read twice in a row and stays open
  through pauses. It closes on *summary* or *standby*, when a new session is seen after a
  reconnect, or after 15 minutes without a connection. Sessions under 30 s with no steps are
  ignored. If HA joins mid-session, the start time is backdated using the console's session timer.
- Sessions run while the LifeSpan app holds the connection, or while the console is out of range,
  are not seen.

## Install
Copy `custom_components/lifespan_treadmill` to `/config/custom_components/` (or add this
repo to HACS as a custom integration repository), then restart Home Assistant. Turn the
treadmill console on and the device appears under **Settings → Devices & services →
Discovered**. You can also add it with **Add integration → LifeSpan Treadmill**.

## Protocol
Service `FFF0`. Write `A1 <op> 00 00 00 00` to `FFF2` and read the reply `A1 AA b2 b3 b4 b5` from `FFF1`.
Opcodes: `82` speed, `85` distance, `87` calories, `88` steps, `89` time (h,m,s), `91` status.
Credit: [blak3r/treadspan](https://github.com/blak3r/treadspan) and
[marcuspuchalla/trot](https://github.com/marcuspuchalla/trot).

## Development
`pytest` (with `pytest-homeassistant-custom-component`) runs `tests/`.
