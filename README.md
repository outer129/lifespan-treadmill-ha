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

Each sensor also has a `raw_frame` attribute with the last reply from the console, which helps check the decoding.

**Read-only.** Nobody has found a way to start, stop or set the speed over BLE.

The console accepts only **one** Bluetooth connection, so the LifeSpan Fit app
can't connect while Home Assistant holds the connection. To use the app, disable the integration entry first.

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
