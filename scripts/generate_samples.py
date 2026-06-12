"""Generate sample config files for testing.

Creates:
  config/sample_rack_layout.yaml      — parametric grid rack layout
  config/sample_devices.xlsx          — device inventory (compact port notation)
"""
from pathlib import Path

import pandas as pd
import yaml

config_dir = Path(__file__).parent.parent / "config"
config_dir.mkdir(parents=True, exist_ok=True)


def rack_id(row: int, col: int) -> str:
    return f"Row{row:02d}-Rack{col:02d}"


# ── Sample Rack Layout (YAML parametric format) ──
layout = {
    "layout": {
        "num_rows": 2,
        "racks_per_row": 8,
        "rack_width_mm": 600,
        "rack_depth_mm": 1200,
        "rack_height_u": 42,
        "col_spacing_m": 0.8,
        "row_spacing_m": 3.0,
        "tray_height_m": 2.6,
        "tray_side": "low",
        "tray_offset_m": 0.6,    # horizontal distance from rack center to aisle tray
        "origin_x_m": 0.0,
        "origin_y_m": 0.0,
    }
}

with open(str(config_dir / "sample_rack_layout.yaml"), "w", encoding="utf-8") as f:
    yaml.dump(layout, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
print(f"Rack layout: {layout['layout']['num_rows']} rows × {layout['layout']['racks_per_row']} cols = {layout['layout']['num_rows'] * layout['layout']['racks_per_row']} racks")

# ── Sample Devices ──
# Port notation: "TYPE:SPEED:DIRECTION:COUNT"
# Multiple entries separated by commas; port numbering is sequential.

devices = []

# 8 GPU servers — 8× QSFP56 200G uplink + 2× SFP28 25G uplink + 1× RJ45 1G uplink
# Placed one per rack in Row 1, Cols 1-8
for col in range(1, 9):
    devices.append({
        "name": f"GPU-Server-{col:02d}",
        "device_type": "gpu_server",
        "rack_id": rack_id(1, col),
        "ru_start": 20,
        "ru_height": 4,
        "ports": "QSFP56:200:uplink:8, SFP28:25:uplink:2, RJ45:1:uplink:1",
    })

# 2 Backend Leaf switches (face GPU servers)
# 32x QSFP56 200G downlink (to servers) + 8x QSFP56 200G uplink (to spine)
# Placed in Row 1, Cols 1,3
for i, col in enumerate([1, 3]):
    devices.append({
        "name": f"Backend-Leaf-{i+1:02d}",
        "device_type": "backend_leaf",
        "rack_id": rack_id(1, col),
        "ru_start": 30,
        "ru_height": 1,
        "ports": "QSFP56:200:downlink:32, QSFP56:200:uplink:8",
    })

# 2 Backend Spine switches (interconnect leaf switches)
# 32x QSFP56 200G downlink (to leaves) + 0 uplink (top of fabric)
# Placed in Row 1, Cols 5,7
for i, col in enumerate([5, 7]):
    devices.append({
        "name": f"Backend-Spine-{i+1:02d}",
        "device_type": "backend_spine",
        "rack_id": rack_id(1, col),
        "ru_start": 30,
        "ru_height": 1,
        "ports": "QSFP56:200:downlink:32",
    })

# 1 Frontend Leaf switch (faces servers)
# 24x SFP28 25G downlink + 8x QSFP28 100G uplink (to spine)
# Placed in Row 2, Col 1
devices.append({
    "name": "Frontend-Leaf-01",
    "device_type": "frontend_leaf",
    "rack_id": rack_id(2, 1),
    "ru_start": 35,
    "ru_height": 1,
    "ports": "SFP28:25:downlink:24, QSFP28:100:uplink:8",
})

# 1 Frontend Spine switch (interconnects leaf, uplink to core)
# 16x QSFP28 100G downlink (to leaves) + 4x QSFP28 100G uplink (to core)
# Placed in Row 2, Col 5
devices.append({
    "name": "Frontend-Spine-01",
    "device_type": "frontend_spine",
    "rack_id": rack_id(2, 5),
    "ru_start": 35,
    "ru_height": 1,
    "ports": "QSFP28:100:downlink:16, QSFP28:100:uplink:4",
})

# 2 Out-of-band Management switches — 48x RJ45 1G downlink
# Placed in Row 2, Cols 3,7
for i, col in enumerate([3, 7]):
    devices.append({
        "name": f"Mgmt-Switch-{i+1:02d}",
        "device_type": "mgmt_switch",
        "rack_id": rack_id(2, col),
        "ru_start": 38,
        "ru_height": 1,
        "ports": "RJ45:1:downlink:48",
    })

# 2 In-band Management switches (optional — uncomment to enable)
# 24x SFP28 25G downlink + 4x QSFP28 100G uplink
# Placed in Row 2, Cols 4,8
# for i, col in enumerate([4, 8]):
#     devices.append({
#         "name": f"Inband-Switch-{i+1:02d}",
#         "device_type": "inband_switch",
#         "rack_id": rack_id(2, col),
#         "ru_start": 39,
#         "ru_height": 1,
#         "ports": "SFP28:25:downlink:24, QSFP28:100:uplink:4",
#     })

df_devices = pd.DataFrame(devices)
df_devices.to_excel(str(config_dir / "sample_devices.xlsx"), index=False)
print(f"Devices: {len(devices)} devices")

# Count total ports from compact notation
total_ports = 0
for _, row in df_devices.iterrows():
    ports_str = str(row["ports"])
    for item in ports_str.split(","):
        parts = item.strip().split(":")
        if len(parts) == 4 and parts[3].strip().isdigit():
            total_ports += int(parts[3].strip())
        elif len(parts) >= 3:
            total_ports += 1
print(f"Total ports: {total_ports}")
print("Done!")
