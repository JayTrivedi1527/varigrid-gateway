# Varigrid Gateway

Edge agent that polls your data-centre sensors (Modbus TCP, simulators
for now; SNMP / BACnet / MQTT later) and pushes readings to your
[Varigrid](https://varigrid.in) account.

Runs anywhere Python 3.10+ runs — a Raspberry Pi 4, a NUC, a small
Linux VM on existing hardware, or a Docker container.

```
                  Customer OT network
                  ┌─────────────────┐
   MFM (Modbus) ──┤                 ├── HTTPS ──▶  api.varigrid.in
   UPS  (SNMP)  ──┤  varigrid-      │
   CRAC (BACnet)──┤  gateway        │
   ...            │  (this repo)    │
                  └─────────────────┘
```

Open source (Apache 2.0). Customer security teams can read every line.

---

## Quick start (Docker)

```bash
# 1. In Varigrid: Settings → Sensors → Add gateway → copy the API key.
# 2. Save it + your sensor list as gateway_config.yaml (template below).
# 3. Run:

docker run -d --restart=unless-stopped \
  -v $(pwd)/gateway_config.yaml:/etc/varigrid/gateway_config.yaml:ro \
  -v varigrid-buffer:/var/lib/varigrid \
  --network host \
  ghcr.io/varigrid/gateway:latest
```

## Quick start (local Python)

```bash
git clone https://github.com/varigrid/gateway.git
cd gateway
pip install -e .
varigrid-gateway --config gateway_config.yaml
```

---

## `gateway_config.yaml` template

```yaml
gateway:
  api_url: https://api.varigrid.in
  api_key: vrg_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  heartbeat_interval_s: 60
  buffer_path: /var/lib/varigrid/buffer.db   # offline replay
  push_batch_size: 50

sensors:
  # Schneider PM5560 at the IT panel
  - id: 9d3a2cb4-1f6e-4d8e-9a3b-1c2d3e4f5a6b   # the sensor UUID from Varigrid
    kind: modbus_tcp
    poll_interval_s: 30
    config:
      ip: 10.20.1.5
      port: 502
      unit_id: 1
      register: 40012        # holding register
      register_count: 2      # 32-bit float = 2 registers
      data_type: float32     # float32 | int16 | uint16 | int32 | uint32
      byte_order: big        # big | little
      scale: 1.0             # multiply raw → value (use 0.001 for kW from W)

  # No real device handy? Use the simulator to fake a value (great for demos).
  - id: c1f9aa7b-3d4e-5f6a-7b8c-9d0e1f2a3b4c
    kind: simulator
    poll_interval_s: 5
    config:
      pattern: walk          # walk | sine | ramp
      start: 1500
      drift: 5               # max +/- per tick (walk only)
```

### What goes in `id`?

That's the **Sensor UUID** Varigrid gives you when you add a sensor in
Settings → Sensors. The agent uses it to address the right ingest endpoint
(`POST /api/ingest/{sensor_id}`).

---

## What the agent does, in order

1. Loads `gateway_config.yaml` and starts a poll loop per sensor.
2. Sends a heartbeat to `POST /api/gateways/heartbeat` every 60s
   (configurable) so Varigrid knows the agent is alive.
3. For each sensor: reads the value at `poll_interval_s`, then either:
   - **Pushes it** via `POST /api/ingest/{sensor_id}` over HTTPS, or
   - **Buffers it** to a local SQLite file if the push fails. A
     replay task drains the buffer back to Varigrid as soon as
     connectivity returns.

Network drops do not lose data. The buffer caps at 100 000 rows
(~3 days at 50 sensors × 30s) — enough for any realistic outage.

---

## Supported sensor kinds

| `kind`        | What it covers                                        | Status     |
|---------------|------------------------------------------------------|------------|
| `modbus_tcp`  | Modern MFMs (Schneider PM5xxx, Selec MFM384, L&T 5060), modern UPS, gensets, many CRACs | ✅ Stable |
| `modbus_rtu`  | RS-485 serial — older meters, aisle temp probe chains, older chillers | ✅ Stable |
| `snmp`        | UPS (APC, Eaton, Vertiv via UPS-MIB), smart PDUs (Raritan, Geist, APC) — v2c + v3 | ✅ Stable |
| `mqtt`        | Subscribe to a customer's existing MQTT broker (Mosquitto, HiveMQ, EMQX) | ✅ Stable |
| `opcua`       | Industrial standard — SCADA, Wonderware, Ignition, modern BMS/EMS    | ✅ Stable |
| `bacnet`      | BACnet/IP — Honeywell Niagara, Siemens Desigo, Johnson Metasys, BMS-attached CRACs | ✅ Stable |
| `simulator`   | Generates fake values (walk/sine/ramp) for demos      | ✅ Stable  |

Need a vendor-specific REST API (Schneider EcoStruxure, Vertiv Trellis,
custom HTTP source)? Use the **universal HTTPS push** path — any system
that can `POST` JSON can stream readings directly to
`https://api.varigrid.in/api/ingest/{sensor_id}` with the gateway's API
key. See the in-app "Push via webhook" docs (Settings → Sensors → `<>` icon).

## Per-protocol config quick-reference

See `gateway_config.example.yaml` for the full annotated template — one
worked example per protocol, ready to copy and edit.

---

## Security

- The API key is the **only** secret on the gateway. Treat it like a
  password.
- All traffic is HTTPS; the agent will refuse `http://` URLs in
  `gateway.api_url`.
- Per-gateway keys mean a compromised device on one network can be
  revoked from the Varigrid Settings UI without affecting others.
- The buffer file (`buffer_path`) contains raw sensor readings. If
  that's sensitive, encrypt the volume.

Found something? `security@varigrid.in`.

---

## Licence

Apache 2.0 — see `LICENSE`.
