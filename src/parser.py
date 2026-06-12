"""Input parser: reads Excel and YAML files into model objects."""

from typing import Optional
from pathlib import Path

import pandas as pd
import yaml

from .models import (
    Device, DeviceType, Port, PortType, PortDirection,
    Rack, ConnectionRule, ConnectionPattern,
)


# ── Helper: NaN-safe type conversions ────────────────────────────────────

def _safe_int(val, default: int) -> int:
    """Convert value to int, using default if NaN or None."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return int(val)


def _safe_float(val, default: float) -> float:
    """Convert value to float, using default if NaN or None."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return float(val)


# ── Rack layout parsing ─────────────────────────────────────────────────

def parse_rack_layout(filepath: str) -> list[Rack]:
    """Parse rack layout from Excel or YAML file.

    Supports three formats:

    1.  Excel (.xlsx / .xls) — explicit columns:
        rack_id, row, col, x_m, y_m, width_mm, depth_mm, height_u

    2.  YAML (.yaml / .yml) — explicit rack list:
        racks:
          - rack_id: Row01-Rack01
            x_m: 0.0
            y_m: 0.0
            ...

    3.  YAML (.yaml / .yml) — parametric grid config (auto-generates coordinates):
        layout:
          num_rows: 2
          racks_per_row: 8
          col_spacing_m: 0.8
          row_spacing_m: 3.0
          ...

    In the parametric mode, rack_ids are auto-generated as "RowXX-RackXX"
    and x_m / y_m are calculated from the grid parameters.
    """
    path = Path(filepath)

    if path.suffix in (".xlsx", ".xls"):
        return _parse_rack_layout_explicit(filepath)

    if path.suffix in (".yaml", ".yml"):
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if isinstance(data, dict) and "layout" in data:
            return _parse_rack_layout_parametric(data["layout"])
        else:
            return _parse_rack_layout_explicit(filepath)

    raise ValueError(f"Unsupported rack file format: {path.suffix}")


def _parse_rack_layout_explicit(filepath: str) -> list[Rack]:
    """Parse explicit rack layout (Excel or YAML with 'racks' key)."""
    path = Path(filepath)
    if path.suffix in (".xlsx", ".xls"):
        df = pd.read_excel(filepath)
    elif path.suffix in (".yaml", ".yml"):
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        df = pd.DataFrame(data.get("racks", data))
    else:
        raise ValueError(f"Unsupported rack file format: {path.suffix}")

    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_").replace("(", "").replace(")", "")
                  for c in df.columns]

    # Validate required columns
    required = {"rack_id", "x_m", "y_m"}
    actual = set(df.columns)
    if not required.issubset(actual):
        raise ValueError(
            f"Rack layout file is missing required columns: {required - actual}. "
            f"Found columns: {sorted(actual)}. "
            f"Please check that you specified the correct rack layout file."
        )

    racks = []
    for _, row in df.iterrows():
        racks.append(Rack(
            rack_id=str(row.get("rack_id", row.get("rack_name", ""))),
            name=str(row.get("name", row.get("rack_id", ""))),
            row=_safe_int(row.get("row", 0), 0),
            col=_safe_int(row.get("col", 0), 0),
            x_m=_safe_float(row.get("x_m", 0), 0.0),
            y_m=_safe_float(row.get("y_m", 0), 0.0),
            width_mm=_safe_int(row.get("width_mm", 600), 600),
            depth_mm=_safe_int(row.get("depth_mm", 1200), 1200),
            height_u=_safe_int(row.get("height_u", 42), 42),
        ))
    return racks


def _parse_rack_layout_parametric(config: dict) -> list[Rack]:
    """Generate Rack objects from a parametric grid configuration.

    Required keys:
        num_rows, racks_per_row, col_spacing_m, row_spacing_m

    Optional keys (with defaults):
        rack_width_mm (600), rack_depth_mm (1200), rack_height_u (42),
        origin_x_m (0.0), origin_y_m (0.0), tray_side ("low"),
        tray_offset_m (0.0)

    tray_offset_m is the horizontal distance from each rack center to the
    cable tray centerline in the aisle (applied at both ends of a cable run).

    Rack IDs are auto-generated as "Row{row:02d}-Rack{col:02d}".
    Coordinates are computed as:
        x_m = origin_x_m + (col - 1) * col_spacing_m
        y_m = origin_y_m + (row - 1) * row_spacing_m
    """
    num_rows = config.get("num_rows")
    racks_per_row = config.get("racks_per_row")
    col_spacing_m = config.get("col_spacing_m")
    row_spacing_m = config.get("row_spacing_m")

    # Validate required parameters
    missing = []
    if num_rows is None:
        missing.append("num_rows")
    if racks_per_row is None:
        missing.append("racks_per_row")
    if col_spacing_m is None:
        missing.append("col_spacing_m")
    if row_spacing_m is None:
        missing.append("row_spacing_m")
    if missing:
        raise ValueError(
            f"Parametric rack layout is missing required parameter(s): "
            f"{', '.join(missing)}. "
            f"Required: num_rows, racks_per_row, col_spacing_m, row_spacing_m."
        )

    origin_x_m = float(config.get("origin_x_m", 0.0))
    origin_y_m = float(config.get("origin_y_m", 0.0))
    width_mm = int(config.get("rack_width_mm", 600))
    depth_mm = int(config.get("rack_depth_mm", 1200))
    height_u = int(config.get("rack_height_u", 42))
    tray_side = str(config.get("tray_side", "low"))
    tray_offset_m = float(config.get("tray_offset_m", 0.0))
    tray_height_m = float(config.get("tray_height_m", 0.0))

    racks = []
    for row in range(1, num_rows + 1):
        for col in range(1, racks_per_row + 1):
            rack_id = f"Row{row:02d}-Rack{col:02d}"
            x_m = origin_x_m + (col - 1) * col_spacing_m
            y_m = origin_y_m + (row - 1) * row_spacing_m

            racks.append(Rack(
                rack_id=rack_id,
                name=rack_id,
                row=row,
                col=col,
                x_m=round(x_m, 3),
                y_m=round(y_m, 3),
                width_mm=width_mm,
                depth_mm=depth_mm,
                height_u=height_u,
                tray_side=tray_side,
                tray_offset_m=tray_offset_m,
                tray_height_m=tray_height_m,
            ))

    return racks


# ── Device & port parsing ───────────────────────────────────────────────

def _parse_ports_from_value(ports_value) -> list[Port]:
    """Parse ports from a cell value that can be a JSON string, dict, or list."""
    import json
    import warnings

    if isinstance(ports_value, str):
        try:
            parsed = json.loads(ports_value)
        except json.JSONDecodeError:
            # Try parsing as compact "port_name:type:speed:direction" notation
            result = _parse_ports_compact(ports_value)
            if not result:
                warnings.warn(
                    f"Could not parse port data: value is not valid JSON "
                    f"and not valid compact format. Raw value: "
                    f"'{ports_value[:200]}{'...' if len(ports_value) > 200 else ''}'"
                )
            return result
        ports_value = parsed

    if isinstance(ports_value, dict):
        # {"ports": [...]}
        ports_value = ports_value.get("ports", [ports_value])

    ports = []
    if isinstance(ports_value, list):
        for item in ports_value:
            if isinstance(item, str):
                ports.extend(_parse_ports_compact(item))
            elif isinstance(item, dict):
                ports.append(Port(
                    port_name=str(item.get("port_name", item.get("name", ""))),
                    port_type=PortType(str(item.get("port_type", item.get("type", "QSFP28")))),
                    speed_gbps=int(item.get("speed_gbps", item.get("speed", 100))),
                    direction=PortDirection(str(item.get("direction", "any"))),
                    group=str(item.get("group", "")),
                ))
    return ports


def _parse_ports_compact(text: str) -> list[Port]:
    """Parse compact port notation like:
        "QSFP28:100:downlink:8"  → 8 ports named Port1-Port8 of QSFP28/100G/downlink
        "Port1:QSFP28:100:any, Port2:QSFP28:100:any"
        "QSFP56:200:uplink:8, SFP28:25:uplink:2, RJ45:1:uplink:1"
          → Port1-8 (QSFP56), Port9-10 (SFP28), Port11 (RJ45)

    Multiple comma-separated count-based entries share a sequential port counter
    so names never overlap: Port1..N, then PortN+1..M, etc.
    """
    import warnings

    ports = []
    text = text.strip()
    if not text:
        return ports

    # ── Single count-based pattern: "TYPE:SPEED:DIR:COUNT" ──
    parts = text.split(":")
    if len(parts) == 4 and parts[3].strip().isdigit():
        port_type_str, speed_str, dir_str, count_str = parts
        count = int(count_str)
        for i in range(1, count + 1):
            ports.append(Port(
                port_name=f"Port{i}",
                port_type=PortType(port_type_str.strip()),
                speed_gbps=int(speed_str.strip()),
                direction=PortDirection(dir_str.strip()),
            ))
        return ports

    # If it has 4 colon-separated parts but the 4th isn't a digit,
    # the user may have intended the count-based format — warn and return empty
    if len(parts) == 4 and not parts[3].strip().isdigit():
        warnings.warn(
            f"Compact port notation '{text}' has 4 colon-separated fields "
            f"but the last field '{parts[3].strip()}' is not a number. "
            f"Expected format: 'TYPE:SPEED:DIR:COUNT' (e.g. 'QSFP28:100:downlink:8'). "
            f"No ports parsed from this entry."
        )
        return []

    # ── Comma-separated: each item may be count-based or individual ──
    # Each count-based group independently starts at Port1 so that ports
    # belonging to different networks have clean per-network numbering.
    # Example: "QSFP56:200:uplink:8, SFP28:25:uplink:2, RJ45:1:uplink:1"
    #   → Port1-8 (QSFP56/200G backend), Port1-2 (SFP28/25G frontend), Port1 (RJ45/mgmt)

    items = text.split(",")
    for item in items:
        pp = item.strip().split(":")
        n_parts = len(pp)

        # Count-based sub-item: "TYPE:SPEED:DIR:COUNT"
        if n_parts == 4 and pp[3].strip().isdigit():
            port_type_str, speed_str, dir_str, count_str = pp
            count = int(count_str)
            port_type = PortType(port_type_str.strip())
            speed = int(speed_str.strip())
            direction = PortDirection(dir_str.strip())
            for i in range(1, count + 1):
                ports.append(Port(
                    port_name=f"Port{i}",
                    port_type=port_type,
                    speed_gbps=speed,
                    direction=direction,
                ))
            continue

        # Individual sub-item: "NAME:TYPE:SPEED[:DIR[:GROUP]]"
        if n_parts >= 3:
            ports.append(Port(
                port_name=pp[0].strip(),
                port_type=PortType(pp[1].strip()),
                speed_gbps=int(pp[2].strip()),
                direction=PortDirection(pp[3].strip() if len(pp) >= 4 else "any"),
                group=pp[4].strip() if len(pp) >= 5 else "",
            ))
        else:
            warnings.warn(
                f"Malformed port entry '{item.strip()}' in '{text}': "
                f"expected 'NAME:TYPE:SPEED[:DIR[:GROUP]]' with at least 3 fields, "
                f"got {n_parts}. Skipping this entry."
            )

    return ports


def parse_devices(filepath: str) -> list[Device]:
    """Parse devices from Excel or YAML file.

    Excel columns expected:
        name, device_type, rack_id, ru_start, ru_height, ports

    The 'ports' column can be:
        - JSON string: '[{"port_name":"Port1","port_type":"QSFP28",...}]'
        - Compact notation: 'QSFP28:100:downlink:8'
    """
    path = Path(filepath)
    if path.suffix in (".xlsx", ".xls"):
        df = pd.read_excel(filepath)
    elif path.suffix in (".yaml", ".yml"):
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        df = pd.DataFrame(data.get("devices", data))
    else:
        raise ValueError(f"Unsupported device file format: {path.suffix}")

    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Validate required columns
    required = {"name", "device_type", "rack_id", "ru_start", "ports"}
    actual = set(df.columns)
    if not required.issubset(actual):
        raise ValueError(
            f"Device file is missing required columns: {required - actual}. "
            f"Found columns: {sorted(actual)}. "
            f"Please check that you specified the correct device inventory file."
        )

    devices = []
    for _, row in df.iterrows():
        ports = _parse_ports_from_value(row.get("ports", ""))

        devices.append(Device(
            name=str(row["name"]),
            device_type=DeviceType(str(row["device_type"])),
            rack_id=str(row["rack_id"]),
            ru_start=_safe_int(row["ru_start"], 1),
            ru_height=_safe_int(row.get("ru_height", 4), 4),
            ports=ports,
        ))
    return devices


# ── Connection rules parsing ────────────────────────────────────────────

def parse_connection_rules(filepath: str) -> list[ConnectionRule]:
    """Parse connection rules from a YAML file.

    Example YAML:
    ```yaml
    rules:
      - name: "GPU → RDMA Switch"
        src_device_type: gpu_server
        src_port_type: QSFP56
        src_direction: downlink
        dst_device_type: rdma_switch
        dst_port_type: QSFP56
        dst_direction: uplink
        pattern: many_to_one
        ports_per_group: 8
        priority: 0
    ```
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Parse YAML structure: supports both bare lists and dicts with "rules" key
    if isinstance(data, list):
        rules_data = data
    elif isinstance(data, dict):
        rules_data = data.get("rules")
        if rules_data is None:
            raise ValueError(
                f"Connection rules file does not contain a 'rules' key. "
                f"Found keys: {sorted(data.keys())}. "
                f"Please check that you specified the correct connection rules YAML file."
            )
    else:
        raise ValueError(
            f"Connection rules must be a YAML list (under a 'rules' key or bare). "
            f"Please check that you specified the correct file."
        )

    if not isinstance(rules_data, list):
        raise ValueError(
            f"Connection rules 'rules' value must be a list. "
            f"Got {type(rules_data).__name__}."
        )

    rules = []
    for item in rules_data:
        rules.append(ConnectionRule(
            name=str(item.get("name", "Unnamed Rule")),
            src_device_type=DeviceType(str(item["src_device_type"])),
            src_port_type=PortType(str(item["src_port_type"])),
            dst_device_type=DeviceType(str(item["dst_device_type"])),
            dst_port_type=PortType(str(item["dst_port_type"])),
            pattern=ConnectionPattern(str(item.get("pattern", "one_to_one"))),
            src_direction=PortDirection(str(item.get("src_direction", "downlink"))),
            dst_direction=PortDirection(str(item.get("dst_direction", "uplink"))),
            ports_per_group=int(item.get("ports_per_group", 1)),
            priority=int(item.get("priority", 0)),
            allow_same_rack=bool(item.get("allow_same_rack", True)),
            max_distance_m=float(item["max_distance_m"]) if "max_distance_m" in item else None,
            cable_preference=str(item.get("cable_preference", "auto")),
        ))
    return rules


# ── Combined config loading ─────────────────────────────────────────────

def load_batch_config(filepath: str) -> dict:
    """Load a batch configuration file that references all inputs.

    Example YAML:
    ```yaml
    rack_layout: config/rack_layout.xlsx
    devices: config/devices.xlsx
    connection_rules: config/rules.yaml
    tray_height_m: 2.6
    slack_factor: 1.15
    output: output/mapping.xlsx
    ```
    """
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
