"""Tests for input parser module."""
import json
import tempfile
from pathlib import Path

import pytest
import yaml
import pandas as pd

from src.parser import (
    _parse_ports_compact,
    _parse_ports_from_value,
    parse_rack_layout,
    parse_devices,
    parse_connection_rules,
    load_batch_config,
)
from src.models import Port, PortType, PortDirection, DeviceType


# ── _parse_ports_compact ──────────────────────────────────────────────────

class TestParsePortsCompact:
    def test_count_based_pattern(self):
        """QSFP28:100:downlink:4 → 4 ports named Port1-Port4."""
        ports = _parse_ports_compact("QSFP28:100:downlink:4")
        assert len(ports) == 4
        assert ports[0].port_name == "Port1"
        assert ports[0].port_type == PortType.QSFP28
        assert ports[0].speed_gbps == 100
        assert ports[0].direction == PortDirection.DOWNLINK
        assert ports[3].port_name == "Port4"

    def test_count_based_with_spaces(self):
        """Whitespace around fields is stripped."""
        ports = _parse_ports_compact(" QSFP56 : 200 : uplink : 3 ")
        assert len(ports) == 3
        assert ports[0].port_name == "Port1"
        assert ports[0].port_type == PortType.QSFP56
        assert ports[0].direction == PortDirection.UPLINK

    def test_comma_separated_ports(self):
        """Comma-separated individual port specs."""
        ports = _parse_ports_compact(
            "Port1:QSFP28:100:downlink, Port2:QSFP28:100:uplink"
        )
        assert len(ports) == 2
        assert ports[0].port_name == "Port1"
        assert ports[0].direction == PortDirection.DOWNLINK
        assert ports[1].port_name == "Port2"
        assert ports[1].direction == PortDirection.UPLINK

    def test_comma_separated_no_direction(self):
        """Default direction is 'any' when omitted."""
        ports = _parse_ports_compact("Port1:QSFP28:100")
        assert len(ports) == 1
        assert ports[0].direction == PortDirection.ANY

    def test_comma_separated_with_group(self):
        """5th field is group."""
        ports = _parse_ports_compact("Port1:QSFP56:200:downlink:bond0")
        assert len(ports) == 1
        assert ports[0].group == "bond0"

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert _parse_ports_compact("") == []
        assert _parse_ports_compact("   ") == []

    def test_mixed_count_based_per_group(self):
        """Each comma-separated group independently starts at Port1."""
        ports = _parse_ports_compact(
            "QSFP56:200:uplink:3, SFP28:25:uplink:2, RJ45:1:downlink:1"
        )
        assert len(ports) == 6
        # Group 1: Port1-3 (QSFP56/200G)
        assert ports[0].port_name == "Port1"
        assert ports[0].port_type == PortType.QSFP56
        assert ports[2].port_name == "Port3"
        # Group 2: Port1-2 (SFP28/25G)
        assert ports[3].port_name == "Port1"
        assert ports[3].port_type == PortType.SFP28
        assert ports[4].port_name == "Port2"
        # Group 3: Port1 (RJ45/1G)
        assert ports[5].port_name == "Port1"
        assert ports[5].port_type == PortType.RJ45

    def test_mixed_individual_and_count_based(self):
        """Individual named port + count-based; count-based restarts at Port1."""
        ports = _parse_ports_compact(
            "Mgmt:QSFP56:200:uplink, SFP28:25:downlink:2"
        )
        assert len(ports) == 3
        assert ports[0].port_name == "Mgmt"
        assert ports[0].port_type == PortType.QSFP56
        assert ports[1].port_name == "Port1"
        assert ports[1].port_type == PortType.SFP28
        assert ports[2].port_name == "Port2"

    def test_malformed_entry_warns(self):
        """Too few fields emits a warning."""
        with pytest.warns(UserWarning, match="Malformed port entry"):
            ports = _parse_ports_compact("bad-entry:only-two")
        assert len(ports) == 0

    def test_ambiguous_count_format_warns(self):
        """4 colon fields but last is not a digit — emits warning."""
        with pytest.warns(UserWarning, match="not a number"):
            ports = _parse_ports_compact("QSFP28:100:downlink:abc")
        # Falls back to comma parsing, which also fails because it has no commas
        assert len(ports) == 0


# ── _parse_ports_from_value ───────────────────────────────────────────────

class TestParsePortsFromValue:
    def test_json_string(self):
        """JSON string port list."""
        value = json.dumps([
            {"port_name": "eth0", "port_type": "QSFP56", "speed_gbps": 200, "direction": "uplink"},
            {"port_name": "eth1", "port_type": "SFP28", "speed_gbps": 25, "direction": "downlink"},
        ])
        ports = _parse_ports_from_value(value)
        assert len(ports) == 2
        assert ports[0].port_name == "eth0"
        assert ports[0].port_type == PortType.QSFP56
        assert ports[1].port_name == "eth1"
        assert ports[1].port_type == PortType.SFP28

    def test_json_dict_with_ports_key(self):
        """JSON dict with 'ports' key."""
        value = json.dumps({"ports": [
            {"port_name": "P1", "port_type": "QSFP28", "speed_gbps": 100}
        ]})
        ports = _parse_ports_from_value(value)
        assert len(ports) == 1
        assert ports[0].port_name == "P1"

    def test_json_dict_without_ports_key(self):
        """JSON dict without 'ports' key falls back to wrapping in list."""
        value = json.dumps({"port_name": "P1", "port_type": "QSFP28", "speed_gbps": 100})
        ports = _parse_ports_from_value(value)
        assert len(ports) == 1
        assert ports[0].port_name == "P1"

    def test_compact_format_fallback(self):
        """Non-JSON string is parsed as compact format."""
        ports = _parse_ports_from_value("QSFP28:100:downlink:2")
        assert len(ports) == 2
        assert ports[0].port_type == PortType.QSFP28

    def test_list_of_strings(self):
        """Python list of compact-format strings."""
        ports = _parse_ports_from_value([
            "QSFP56:200:uplink:2",
            "RJ45:1:downlink:1",
        ])
        assert len(ports) == 3
        assert ports[0].port_type == PortType.QSFP56
        assert ports[2].port_type == PortType.RJ45

    def test_list_of_dicts(self):
        """Python list of dicts."""
        ports = _parse_ports_from_value([
            {"port_name": "P1", "port_type": "QSFP56", "speed_gbps": 200},
            {"name": "P2", "type": "SFP28", "speed": 25},
        ])
        assert len(ports) == 2
        assert ports[1].port_name == "P2"
        assert ports[1].speed_gbps == 25

    def test_unparseable_string_warns(self):
        """Totally malformed string emits warning and returns empty list."""
        with pytest.warns(UserWarning, match="Could not parse port data"):
            ports = _parse_ports_from_value("not-json-nor-compact")
        assert ports == []


# ── parse_rack_layout ─────────────────────────────────────────────────────

class TestParseRackLayout:
    def test_excel(self):
        """Parse rack layout from Excel file."""
        df = pd.DataFrame({
            "rack_id": ["R01", "R02"],
            "x_m": [0.0, 0.8],
            "y_m": [0.0, 3.0],
            "row": [1, 2],
            "col": [1, 1],
        })
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            df.to_excel(f.name, index=False)
            tmp_path = f.name
        try:
            racks = parse_rack_layout(tmp_path)
            assert len(racks) == 2
            assert racks[0].rack_id == "R01"
            assert racks[0].x_m == 0.0
            assert racks[1].rack_id == "R02"
            assert racks[1].y_m == 3.0
            # Defaults
            assert racks[0].width_mm == 600
            assert racks[0].depth_mm == 1200
            assert racks[0].height_u == 42
        finally:
            Path(tmp_path).unlink()

    def test_yaml(self):
        """Parse rack layout from YAML file."""
        data = {
            "racks": [
                {"rack_id": "R01", "x_m": 1.0, "y_m": 2.0},
                {"rack_id": "R02", "x_m": 3.0, "y_m": 4.0, "width_mm": 800},
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            racks = parse_rack_layout(tmp_path)
            assert len(racks) == 2
            assert racks[0].x_m == 1.0
            assert racks[1].width_mm == 800
        finally:
            Path(tmp_path).unlink()

    def test_missing_required_columns(self):
        """Raises ValueError when x_m or y_m is missing."""
        df = pd.DataFrame({"rack_id": ["R01"]})  # no x_m, y_m
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            df.to_excel(f.name, index=False)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="missing required columns"):
                parse_rack_layout(tmp_path)
        finally:
            Path(tmp_path).unlink()

    def test_unsupported_format(self):
        """Raises ValueError for unsupported file format."""
        with pytest.raises(ValueError, match="Unsupported rack file format"):
            parse_rack_layout("racks.csv")

    def test_column_name_normalization(self):
        """Column names are normalized: spaces/parens stripped, lowercased."""
        df = pd.DataFrame({
            "Rack ID": ["R01"],
            "X (m)": [1.5],
            "Y (m)": [2.5],
        })
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            df.to_excel(f.name, index=False)
            tmp_path = f.name
        try:
            racks = parse_rack_layout(tmp_path)
            assert len(racks) == 1
            assert racks[0].rack_id == "R01"
            assert racks[0].x_m == 1.5
            assert racks[0].y_m == 2.5
        finally:
            Path(tmp_path).unlink()


# ── parse_devices ──────────────────────────────────────────────────────────

class TestParseDevices:
    def test_excel(self):
        """Parse devices from Excel with JSON ports."""
        df = pd.DataFrame({
            "name": ["GPU-01"],
            "device_type": ["gpu_server"],
            "rack_id": ["R01"],
            "ru_start": [20],
            "ru_height": [4],
            "ports": [json.dumps([
                {"port_name": "Port1", "port_type": "QSFP56", "speed_gbps": 200, "direction": "uplink"},
                {"port_name": "Port2", "port_type": "QSFP56", "speed_gbps": 200, "direction": "uplink"},
            ])],
        })
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            df.to_excel(f.name, index=False)
            tmp_path = f.name
        try:
            devices = parse_devices(tmp_path)
            assert len(devices) == 1
            assert devices[0].name == "GPU-01"
            assert devices[0].device_type == DeviceType.GPU_SERVER
            assert devices[0].ru_start == 20
            assert devices[0].ru_height == 4
            assert len(devices[0].ports) == 2
            assert devices[0].ports[0].port_type == PortType.QSFP56
        finally:
            Path(tmp_path).unlink()

    def test_compact_ports(self):
        """Devices with compact port notation."""
        df = pd.DataFrame({
            "name": ["MGMT-01"],
            "device_type": ["mgmt_switch"],
            "rack_id": ["R03"],
            "ru_start": [38],
            "ports": ["RJ45:1:downlink:24"],
        })
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            df.to_excel(f.name, index=False)
            tmp_path = f.name
        try:
            devices = parse_devices(tmp_path)
            assert len(devices) == 1
            assert len(devices[0].ports) == 24
            assert all(p.port_type == PortType.RJ45 for p in devices[0].ports)
            assert all(p.direction == PortDirection.DOWNLINK for p in devices[0].ports)
        finally:
            Path(tmp_path).unlink()

    def test_missing_required_columns(self):
        """Raises ValueError when required columns are missing."""
        df = pd.DataFrame({"name": ["GPU-01"]})  # missing device_type, rack_id, etc.
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            df.to_excel(f.name, index=False)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="missing required columns"):
                parse_devices(tmp_path)
        finally:
            Path(tmp_path).unlink()

    def test_default_ru_height(self):
        """ru_height defaults to 4 when not specified."""
        df = pd.DataFrame({
            "name": ["GPU-01"],
            "device_type": ["gpu_server"],
            "rack_id": ["R01"],
            "ru_start": [20],
            "ports": ["QSFP56:200:uplink:1"],
        })
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            df.to_excel(f.name, index=False)
            tmp_path = f.name
        try:
            devices = parse_devices(tmp_path)
            assert devices[0].ru_height == 4
        finally:
            Path(tmp_path).unlink()

    def test_yaml(self):
        """Parse devices from YAML."""
        data = {
            "devices": [
                {
                    "name": "GPU-01",
                    "device_type": "gpu_server",
                    "rack_id": "R01",
                    "ru_start": 20,
                    "ports": [{"port_name": "P1", "port_type": "QSFP56", "speed_gbps": 200}],
                }
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            devices = parse_devices(tmp_path)
            assert len(devices) == 1
            assert devices[0].name == "GPU-01"
        finally:
            Path(tmp_path).unlink()


# ── parse_connection_rules ────────────────────────────────────────────────

class TestParseConnectionRules:
    def test_rules_key(self):
        """Parse rules from YAML with 'rules' key."""
        data = {
            "rules": [
                {
                    "name": "GPU→RDMA",
                    "src_device_type": "gpu_server",
                    "src_port_type": "QSFP56",
                    "dst_device_type": "rdma_switch",
                    "dst_port_type": "QSFP56",
                    "pattern": "many_to_one",
                    "ports_per_group": 8,
                }
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            rules = parse_connection_rules(tmp_path)
            assert len(rules) == 1
            assert rules[0].name == "GPU→RDMA"
            assert rules[0].src_device_type == DeviceType.GPU_SERVER
            assert rules[0].ports_per_group == 8
        finally:
            Path(tmp_path).unlink()

    def test_bare_list(self):
        """Parse rules from YAML that is a bare list (no 'rules' key)."""
        data = [
            {
                "name": "Test Rule",
                "src_device_type": "eth_switch",
                "src_port_type": "QSFP28",
                "dst_device_type": "eth_switch",
                "dst_port_type": "QSFP28",
            }
        ]
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            rules = parse_connection_rules(tmp_path)
            assert len(rules) == 1
            assert rules[0].name == "Test Rule"
        finally:
            Path(tmp_path).unlink()

    def test_defaults(self):
        """Unspecified fields get sensible defaults."""
        data = {
            "rules": [
                {
                    "src_device_type": "gpu_server",
                    "src_port_type": "QSFP56",
                    "dst_device_type": "rdma_switch",
                    "dst_port_type": "QSFP56",
                }
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            rules = parse_connection_rules(tmp_path)
            rule = rules[0]
            assert rule.pattern.value == "one_to_one"
            assert rule.src_direction == PortDirection.DOWNLINK
            assert rule.dst_direction == PortDirection.UPLINK
            assert rule.ports_per_group == 1
            assert rule.priority == 0
            assert rule.allow_same_rack is True
            assert rule.max_distance_m is None
            assert rule.cable_preference == "auto"
        finally:
            Path(tmp_path).unlink()

    def test_missing_rules_key(self):
        """YAML dict without 'rules' key raises ValueError."""
        data = {"other_key": "value"}
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="does not contain a 'rules' key"):
                parse_connection_rules(tmp_path)
        finally:
            Path(tmp_path).unlink()

    def test_optional_max_distance(self):
        """max_distance_m is optional and parsed correctly when present."""
        data = {
            "rules": [
                {
                    "name": "Limited",
                    "src_device_type": "gpu_server",
                    "src_port_type": "QSFP56",
                    "dst_device_type": "rdma_switch",
                    "dst_port_type": "QSFP56",
                    "max_distance_m": 50.0,
                }
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            rules = parse_connection_rules(tmp_path)
            assert rules[0].max_distance_m == 50.0
        finally:
            Path(tmp_path).unlink()

    # ── New device type names ──

    def test_backend_switch_device_type(self):
        """New backend_switch name is parsed correctly."""
        data = {"rules": [{
            "name": "Test",
            "src_device_type": "gpu_server",
            "src_port_type": "QSFP56",
            "dst_device_type": "backend_switch",
            "dst_port_type": "QSFP56",
        }]}
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            rules = parse_connection_rules(tmp_path)
            assert rules[0].dst_device_type == DeviceType.BACKEND_SWITCH
        finally:
            Path(tmp_path).unlink()

    def test_frontend_switch_device_type(self):
        """New frontend_switch name is parsed correctly."""
        data = {"rules": [{
            "name": "Test",
            "src_device_type": "frontend_switch",
            "src_port_type": "QSFP28",
            "dst_device_type": "frontend_switch",
            "dst_port_type": "QSFP28",
        }]}
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            rules = parse_connection_rules(tmp_path)
            assert rules[0].src_device_type == DeviceType.FRONTEND_SWITCH
        finally:
            Path(tmp_path).unlink()

    def test_inband_switch_device_type(self):
        """New inband_switch name is parsed correctly."""
        data = {"rules": [{
            "name": "Inband",
            "src_device_type": "gpu_server",
            "src_port_type": "SFP28",
            "dst_device_type": "inband_switch",
            "dst_port_type": "SFP28",
        }]}
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            rules = parse_connection_rules(tmp_path)
            assert rules[0].dst_device_type == DeviceType.INBAND_SWITCH
        finally:
            Path(tmp_path).unlink()

    def test_legacy_names_still_work(self):
        """Old device type names (rdma_switch, eth_switch) are still valid."""
        for old_name, expected in [
            ("rdma_switch", DeviceType.RDMA_SWITCH),
            ("eth_switch", DeviceType.ETH_SWITCH),
        ]:
            data = {"rules": [{
                "name": "Legacy",
                "src_device_type": "gpu_server",
                "src_port_type": "QSFP56",
                "dst_device_type": old_name,
                "dst_port_type": "QSFP56",
            }]}
            with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
                yaml.dump(data, f)
                tmp_path = f.name
            try:
                rules = parse_connection_rules(tmp_path)
                assert rules[0].dst_device_type == expected, \
                    f"'{old_name}' should map to {expected}"
            finally:
                Path(tmp_path).unlink()


# ── load_batch_config ─────────────────────────────────────────────────────

class TestLoadBatchConfig:
    def test_load_batch(self):
        """Load a batch config YAML file."""
        data = {
            "rack_layout": "racks.xlsx",
            "devices": "devices.xlsx",
            "connection_rules": "rules.yaml",
            "tray_height_m": 2.8,
            "slack_factor": 1.2,
            "output": "out.xlsx",
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            config = load_batch_config(tmp_path)
            assert config["rack_layout"] == "racks.xlsx"
            assert config["tray_height_m"] == 2.8
            assert config["slack_factor"] == 1.2
        finally:
            Path(tmp_path).unlink()


# ── Parametric rack layout ────────────────────────────────────────────────

class TestParseRackLayoutParametric:
    """Tests for the parametric (grid-based) rack layout config."""

    def test_basic_grid(self):
        """2 rows × 3 cols = 6 racks with correct IDs and coordinates."""
        data = {
            "layout": {
                "num_rows": 2,
                "racks_per_row": 3,
                "col_spacing_m": 0.8,
                "row_spacing_m": 3.0,
            }
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            racks = parse_rack_layout(tmp_path)
            assert len(racks) == 6

            # Row 1, Col 1
            assert racks[0].rack_id == "Row01-Rack01"
            assert racks[0].row == 1
            assert racks[0].col == 1
            assert racks[0].x_m == 0.0
            assert racks[0].y_m == 0.0

            # Row 1, Col 2
            assert racks[1].rack_id == "Row01-Rack02"
            assert racks[1].x_m == 0.8
            assert racks[1].y_m == 0.0

            # Row 2, Col 1
            assert racks[3].rack_id == "Row02-Rack01"
            assert racks[3].x_m == 0.0
            assert racks[3].y_m == 3.0

            # Row 2, Col 3 (last rack)
            assert racks[5].rack_id == "Row02-Rack03"
            assert racks[5].x_m == 1.6
            assert racks[5].y_m == 3.0
        finally:
            Path(tmp_path).unlink()

    def test_default_dimensions(self):
        """Unspecified dimensions use defaults."""
        data = {
            "layout": {
                "num_rows": 1,
                "racks_per_row": 1,
                "col_spacing_m": 0.8,
                "row_spacing_m": 3.0,
            }
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            racks = parse_rack_layout(tmp_path)
            r = racks[0]
            assert r.width_mm == 600
            assert r.depth_mm == 1200
            assert r.height_u == 42
            assert r.tray_side == "low"
            assert r.tray_offset_m == 0.0
        finally:
            Path(tmp_path).unlink()

    def test_tray_offset_parameter(self):
        """tray_offset_m is populated from the config."""
        data = {
            "layout": {
                "num_rows": 1,
                "racks_per_row": 1,
                "col_spacing_m": 0.8,
                "row_spacing_m": 3.0,
                "tray_offset_m": 0.8,
            }
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            racks = parse_rack_layout(tmp_path)
            r = racks[0]
            assert r.tray_offset_m == 0.8
        finally:
            Path(tmp_path).unlink()

    def test_custom_dimensions_and_origin(self):
        """Custom rack dimensions, origin, and tray_side."""
        data = {
            "layout": {
                "num_rows": 1,
                "racks_per_row": 2,
                "col_spacing_m": 1.0,
                "row_spacing_m": 4.0,
                "rack_width_mm": 800,
                "rack_depth_mm": 1000,
                "rack_height_u": 48,
                "origin_x_m": 2.0,
                "origin_y_m": 5.0,
                "tray_side": "high",
            }
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            racks = parse_rack_layout(tmp_path)
            assert len(racks) == 2
            r0 = racks[0]
            assert r0.rack_id == "Row01-Rack01"
            assert r0.x_m == 2.0
            assert r0.y_m == 5.0
            assert r0.width_mm == 800
            assert r0.height_u == 48
            assert r0.tray_side == "high"

            r1 = racks[1]
            assert r1.rack_id == "Row01-Rack02"
            assert r1.x_m == 3.0  # 2.0 + 1*1.0
            assert r1.y_m == 5.0
        finally:
            Path(tmp_path).unlink()

    def test_missing_required_param(self):
        """Raises ValueError when required params are missing."""
        data = {
            "layout": {
                "num_rows": 2,
                # missing racks_per_row, col_spacing_m, row_spacing_m
            }
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            with pytest.raises(ValueError, match="missing required parameter"):
                parse_rack_layout(tmp_path)
        finally:
            Path(tmp_path).unlink()

    def test_backward_compat_explicit_yaml(self):
        """YAML with 'racks' key still works (explicit format)."""
        data = {
            "racks": [
                {"rack_id": "R01", "x_m": 1.0, "y_m": 2.0},
                {"rack_id": "R02", "x_m": 3.0, "y_m": 4.0},
            ]
        }
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            yaml.dump(data, f)
            tmp_path = f.name
        try:
            racks = parse_rack_layout(tmp_path)
            assert len(racks) == 2
            assert racks[0].rack_id == "R01"
            assert racks[0].x_m == 1.0
            assert racks[1].rack_id == "R02"
        finally:
            Path(tmp_path).unlink()

    def test_backward_compat_excel(self):
        """Excel rack layout still works when a YAML 'layout' file also exists."""
        df = pd.DataFrame({
            "rack_id": ["X01"],
            "x_m": [5.0],
            "y_m": [6.0],
        })
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            df.to_excel(f.name, index=False)
            tmp_path = f.name
        try:
            racks = parse_rack_layout(tmp_path)
            assert len(racks) == 1
            assert racks[0].rack_id == "X01"
        finally:
            Path(tmp_path).unlink()
