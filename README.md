# AI Data Center Port Mapping Generator

A Python tool that automatically generates data center port mapping tables
for GPU clusters. Given rack layouts, device inventories, and connection rules,
it calculates cable lengths and matches cable types (DAC / AOC / Fiber / Copper),
with correct Leaf↔Spine pairing for Spine-Leaf topologies.

## Features

- **Parametric rack layout**: Specify rows, columns, spacing, and tray parameters
  once — rack coordinates and IDs are auto-generated
- **Device parsing**: GPU servers, backend/frontend Leaf/Spine switches,
  in-band/OOB management switches
- **Compact port notation**: `QSFP56:200:uplink:8, SFP28:25:uplink:2` defines
  all ports in a single cell with sequential auto-naming
- **Distance calculation**: Overhead cable tray model with Manhattan distance
  and `tray_offset` — distinguishes same-row direct routing from cross-row aisle routing
- **Cable matching**: QSFP112 (400G) through RJ45 (1G), auto-selects DAC/AOC/Fiber
  by distance, with breakout compatibility checks
- **Connection patterns**: One-to-one, many-to-one (aggregation), mesh (Spine-Leaf)
  with hard Leaf↔Spine isolation
- **Tri-lingual Excel output**: Chinese / Japanese / English with port mapping,
  per-length cable BOM, transceiver summary, and device statistics

## Quick Start

### Install

```bash
pip install -r requirements.txt
```

### Generate sample data

```bash
python scripts/generate_samples.py
```

### Run

```bash
# Parametric YAML rack layout (recommended)
python -m src.main \
    --racks config/sample_rack_layout.yaml \
    --devices config/sample_devices.xlsx \
    --rules config/sample_connection_rules.yaml \
    --tray-height 2.6 \
    --output output/port_mapping.xlsx
```

### Run tests

```bash
python -m pytest tests/ -v
```

## Input File Formats

### 1. Rack Layout (YAML parametric format, recommended)

```yaml
layout:
  num_rows: 2
  racks_per_row: 8
  col_spacing_m: 0.8       # center-to-center distance between adjacent racks (x)
  row_spacing_m: 3.0       # distance between rows (y)
  rack_width_mm: 600
  rack_depth_mm: 1200
  rack_height_u: 42
  tray_height_m: 2.6       # cable tray height from floor
  tray_side: low           # tray position: low / high
  tray_offset_m: 0.6       # horizontal distance from rack center to aisle tray
  origin_x_m: 0.0
  origin_y_m: 0.0
```

Coordinates are auto-calculated: `x = origin_x + (col-1) × col_spacing`,
`y = origin_y + (row-1) × row_spacing`.
Rack IDs are auto-generated as `RowXX-RackXX`.

An explicit Excel format (one row per rack with rack_id, x_m, y_m columns) is also supported.

### 2. Device Inventory (Excel)

| name | device_type | rack_id | ru_start | ru_height | ports |
|------|-------------|---------|----------|-----------|-------|
| GPU-Server-01 | gpu_server | Row01-Rack01 | 20 | 4 | `QSFP56:200:uplink:8, SFP28:25:uplink:2, RJ45:1:uplink:1` |

**Supported device types:**

| Type | Description |
|------|-------------|
| `gpu_server` | GPU server |
| `backend_leaf` | Backend leaf switch (faces GPU servers) |
| `backend_spine` | Backend spine switch (interconnects leaves) |
| `frontend_leaf` | Frontend leaf switch (storage/service LAN) |
| `frontend_spine` | Frontend spine switch |
| `mgmt_switch` | Out-of-band management switch (BMC/IPMI) |
| `inband_switch` | In-band management switch |
| `backend_switch` | Generic backend (matches both leaf and spine) |
| `frontend_switch` | Generic frontend |
| `rdma_switch` / `eth_switch` | Legacy names (backward compatible) |

**Compact port notation:**

A single cell defines all ports, comma-separated, with mixed styles:

- **Count-based**: `QSFP56:200:uplink:8` → generates Port1–Port8 of QSFP56/200G/uplink
- **Named**: `Mgmt:RJ45:1:uplink:bond0` → single named port
- **Mixed**: `QSFP56:200:uplink:8, SFP28:25:uplink:2, Mgmt:RJ45:1:uplink`

Multiple count-based entries share a sequential counter (Port1–8, then Port9–10, etc.).

JSON format is also supported: `'[{"port_name":"Port1","port_type":"QSFP56",...}]'`

### 3. Connection Rules (YAML)

```yaml
rules:
  - name: "GPU → Backend Leaf (Compute Fabric)"
    src_device_type: gpu_server
    src_port_type: QSFP56
    src_direction: uplink
    dst_device_type: backend_leaf
    dst_port_type: QSFP56
    dst_direction: downlink
    pattern: one_to_one
    priority: 0
    cable_preference: fiber     # auto / dac / aoc / fiber
    allow_same_rack: true
    max_distance_m: null        # optional max cable distance

  - name: "Backend Leaf → Backend Spine"
    src_device_type: backend_leaf
    src_port_type: QSFP56
    src_direction: uplink
    dst_device_type: backend_spine
    dst_port_type: QSFP56
    dst_direction: downlink
    pattern: mesh               # evenly distributes across spines
    allow_same_rack: false
    priority: 3
    cable_preference: fiber
```

**Connection patterns:**

| Pattern | Description |
|---------|-------------|
| `one_to_one` | Pair ports by index order |
| `many_to_one` | N source ports → 1 destination port (`ports_per_group`) |
| `mesh` | Spine-Leaf full mesh with round-robin distribution across spines |

**Leaf/Spine isolation:** Backend and frontend networks enforce that Leaf↔Leaf
and Spine↔Spine connections are never created, even with misconfigured generic rules.

## Cable Routing Model

Overhead cable tray routing with two cases:

```
Same row:
  Device A ──up──→ direct row routing (no aisle tray) ──→ ──down──→ Device B
  Horizontal = Manhattan distance only (no tray_offset)

Cross row:
  Device A ──up──→ tray_offset into aisle tray ──→ along tray ──→ tray_offset out ──→ ──down──→ Device B
  Horizontal = Manhattan distance + tray_offset × 2

Total = (horizontal + vertical_A + vertical_B) / 1000 × slack_factor (1.15)
```

- Manhattan distance = `|x₁ − x₂| + |y₁ − y₂|` (orthogonal aisle routing)
- Vertical = `tray_height − device_midpoint_height` (≥ 0)

## Cable Matching Rules

| Port | Speed | Short | Medium | Long |
|------|-------|-------|--------|------|
| QSFP112 | 400G | DAC (≤3m) | AOC (3–30m) | QSFP112 SR4 Fiber |
| OSFP | 800G | DAC (≤3m) | AOC (3–30m) | OSFP 800G SR8 Fiber |
| QSFP56-DD | 400G | DAC (≤5m) | AOC (5–30m) | QSFP56-DD SR8 Fiber |
| QSFP56 | 200G | DAC (≤5m) | AOC (5–30m) | QSFP56 SR4 Fiber |
| QSFP28 | 100G | DAC (≤5m) | AOC (5–30m) | QSFP28 SR4 Fiber |
| SFP28 | 25G | DAC (≤5m) | AOC (5–30m) | SFP28 SR Fiber |
| RJ45 | 1G/10G | Cat6/Cat6a (≤100m) | — | — |

Lengths are snapped up to the nearest standard length (customizable via `config/sample_cable_lengths.yaml`).

## Output Files

Each run produces **three language variants** ( `_zh` / `_ja` / `_en` suffixes),
each containing 4 sheets:

| Sheet | Content |
|-------|---------|
| Port Mapping | Source/dest device, rack, RU, port, cable type, standard & calculated length, transceiver |
| Cable BOM | Per-length breakdown (e.g. QSFP56 SR4: 5m×20 + 10m×60), subtotals, grand total |
| Transceiver Summary | Transceiver type, quantity, connections served |
| Device Connection Summary | Per-device total/uplink/downlink counts and port types used |

## Project Structure

```
ai-dc-port-mapper/
├── README.md
├── README_zh.md                         # Chinese README
├── requirements.txt
├── config/
│   ├── sample_rack_layout.yaml          # Parametric rack layout
│   ├── sample_devices.xlsx              # Device inventory
│   ├── sample_connection_rules.yaml     # Connection rules
│   └── sample_cable_lengths.yaml        # Custom cable standard lengths (optional)
├── src/
│   ├── models.py                        # Data models
│   ├── parser.py                        # Input parsers (Excel/YAML + parametric layout)
│   ├── distance.py                      # Cable length calculation
│   ├── cable_matcher.py                 # Cable type matching (QSFP112/OSFP)
│   ├── mapper.py                        # Port mapping engine
│   ├── writer.py                        # Multi-language Excel output
│   ├── i18n.py                          # Chinese / Japanese / English strings
│   └── main.py                          # CLI entry point
├── tests/
│   ├── test_parser.py                   # Parser tests (parametric layout + backward compat)
│   ├── test_distance.py                 # Distance calculation tests
│   ├── test_cable_matcher.py            # Cable matching tests (QSFP112/OSFP + breakout)
│   └── test_integration.py             # Integration tests (Leaf/Spine isolation + mesh distribution)
└── scripts/
    └── generate_samples.py              # Sample config generator
```
