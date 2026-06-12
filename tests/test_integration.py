"""Integration tests for the full pipeline."""
import json
import tempfile
from pathlib import Path

import pytest

from src.models import Port, Device, Rack, ConnectionRule, DeviceType, PortType
from src.models import PortDirection, ConnectionPattern
from src.mapper import generate_mapping
from src.writer import write_output
from src.parser import parse_rack_layout, parse_devices, parse_connection_rules
from src.distance import calculate_cable_length_m


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_racks():
    return [
        Rack(rack_id="R01", name="Rack 01", x_m=0.0, y_m=0.0, row=1, col=1),
        Rack(rack_id="R02", name="Rack 02", x_m=0.8, y_m=0.0, row=1, col=2),
        Rack(rack_id="R03", name="Rack 03", x_m=0.0, y_m=3.0, row=2, col=1),
        Rack(rack_id="R04", name="Rack 04", x_m=0.8, y_m=3.0, row=2, col=2),
    ]


@pytest.fixture
def sample_devices():
    devices = []

    # 2 GPU servers
    for i in range(1, 3):
        ports = []
        for p in range(1, 5):
            ports.append(Port(port_name=f"Port{p}", port_type=PortType.QSFP56,
                              speed_gbps=200, direction=PortDirection.DOWNLINK))
        ports.append(Port(port_name="Mgmt", port_type=PortType.RJ45,
                          speed_gbps=1, direction=PortDirection.DOWNLINK))
        devices.append(Device(
            name=f"GPU-{i:02d}", device_type=DeviceType.GPU_SERVER,
            rack_id=f"R0{i}", ru_start=20, ru_height=4, ports=ports
        ))

    # 1 RDMA switch
    rdma_ports = []
    for p in range(1, 9):
        rdma_ports.append(Port(port_name=f"Port{p}", port_type=PortType.QSFP56,
                               speed_gbps=200, direction=PortDirection.UPLINK))
    devices.append(Device(
        name="RDMA-01", device_type=DeviceType.RDMA_SWITCH,
        rack_id="R01", ru_start=30, ru_height=1, ports=rdma_ports
    ))

    # 1 Management switch
    mgmt_ports = []
    for p in range(1, 25):
        mgmt_ports.append(Port(port_name=f"Port{p}", port_type=PortType.RJ45,
                               speed_gbps=1, direction=PortDirection.UPLINK))
    devices.append(Device(
        name="MGMT-01", device_type=DeviceType.MGMT_SWITCH,
        rack_id="R03", ru_start=38, ru_height=1, ports=mgmt_ports
    ))

    return devices


@pytest.fixture
def sample_rules():
    return [
        ConnectionRule(
            name="GPU→RDMA",
            src_device_type=DeviceType.GPU_SERVER,
            src_port_type=PortType.QSFP56,
            dst_device_type=DeviceType.RDMA_SWITCH,
            dst_port_type=PortType.QSFP56,
            pattern=ConnectionPattern.MANY_TO_ONE,
            ports_per_group=4,
            priority=0,
        ),
        ConnectionRule(
            name="GPU→MGMT",
            src_device_type=DeviceType.GPU_SERVER,
            src_port_type=PortType.RJ45,
            dst_device_type=DeviceType.MGMT_SWITCH,
            dst_port_type=PortType.RJ45,
            pattern=ConnectionPattern.MANY_TO_ONE,
            ports_per_group=48,
            priority=1,
        ),
    ]


# ── Tests ───────────────────────────────────────────────────────────────

class TestIntegration:
    def test_full_pipeline(self, sample_racks, sample_devices, sample_rules):
        """Test the full pipeline from models to output."""
        connections = generate_mapping(
            sample_racks, sample_devices, sample_rules,
            tray_height_m=2.6, slack_factor=1.15
        )
        assert len(connections) > 0

        # Check GPU→RDMA connections (2 GPUs × 4 QSFP56 ports = 8 → 2 RDMA ports)
        rdma_conns = [c for c in connections if "RDMA" in c.dst_device]
        assert len(rdma_conns) == 8  # 8 GPU ports → 2 switch port groups

        # Check GPU→MGMT connections (2 GPUs × 1 RJ45 = 2)
        mgmt_conns = [c for c in connections if "MGMT" in c.dst_device]
        assert len(mgmt_conns) == 2

        # All connections should have cable types and lengths
        for c in connections:
            assert c.cable_type
            assert c.cable_length_m > 0

    def test_write_output(self, sample_racks, sample_devices, sample_rules, tmp_path):
        """Test writing output to Excel."""
        connections = generate_mapping(
            sample_racks, sample_devices, sample_rules,
            tray_height_m=2.6
        )
        out_path = tmp_path / "test_output.xlsx"
        result = write_output(str(out_path), connections)
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_no_self_connections(self, sample_racks):
        """Verify that a port never connects to itself."""
        devices = [
            Device(name="SW-01", device_type=DeviceType.ETH_SWITCH,
                   rack_id="R01", ru_start=30, ru_height=1, ports=[
                       Port(port_name="P1", port_type=PortType.QSFP28,
                            speed_gbps=100, direction=PortDirection.DOWNLINK),
                       Port(port_name="P2", port_type=PortType.QSFP28,
                            speed_gbps=100, direction=PortDirection.DOWNLINK),
                   ]),
            Device(name="SW-02", device_type=DeviceType.ETH_SWITCH,
                   rack_id="R02", ru_start=30, ru_height=1, ports=[
                       Port(port_name="P1", port_type=PortType.QSFP28,
                            speed_gbps=100, direction=PortDirection.DOWNLINK),
                       Port(port_name="P2", port_type=PortType.QSFP28,
                            speed_gbps=100, direction=PortDirection.DOWNLINK),
                   ]),
        ]
        rules = [ConnectionRule(
            name="SW-SW Mesh",
            src_device_type=DeviceType.ETH_SWITCH,
            src_port_type=PortType.QSFP28,
            dst_device_type=DeviceType.ETH_SWITCH,
            dst_port_type=PortType.QSFP28,
            src_direction=PortDirection.DOWNLINK,
            dst_direction=PortDirection.DOWNLINK,
            pattern=ConnectionPattern.ONE_TO_ONE,
            allow_same_rack=False,
        )]
        connections = generate_mapping(sample_racks, devices, rules, tray_height_m=2.6)

        for c in connections:
            # No self-connections
            assert not (c.src_device == c.dst_device and c.src_port == c.dst_port), \
                f"Self-connection detected: {c.src_device}:{c.src_port} → {c.dst_device}:{c.dst_port}"

    def test_cable_length_monotonic(self):
        """Longer rack distances produce longer cables."""
        r1 = Rack(rack_id="R01", x_m=0.0, y_m=0.0)
        r2 = Rack(rack_id="R02", x_m=0.8, y_m=0.0)
        r3 = Rack(rack_id="R03", x_m=10.0, y_m=0.0)
        d = Device(name="d", device_type="gpu_server",
                   rack_id="R01", ru_start=20, ru_height=4)

        l_near = calculate_cable_length_m(r1, r2, d, d, tray_height_m=2.6)
        l_far = calculate_cable_length_m(r1, r3, d, d, tray_height_m=2.6)
        assert l_far > l_near, f"Far {l_far}m should be > near {l_near}m"

    def test_no_leaf_to_leaf_connections(self, sample_racks):
        """Leaf switches must never connect to other leaf switches."""
        devices = [
            Device(name="Leaf-01", device_type=DeviceType.BACKEND_LEAF, rack_id="R01",
                   ru_start=30, ru_height=1, ports=[
                       Port("P1", PortType.QSFP56, 200, PortDirection.UPLINK),
                       Port("P2", PortType.QSFP56, 200, PortDirection.UPLINK),
                   ]),
            Device(name="Leaf-02", device_type=DeviceType.BACKEND_LEAF, rack_id="R02",
                   ru_start=30, ru_height=1, ports=[
                       Port("P1", PortType.QSFP56, 200, PortDirection.DOWNLINK),
                       Port("P2", PortType.QSFP56, 200, PortDirection.DOWNLINK),
                   ]),
        ]
        rules = [ConnectionRule(
            name="ShouldNotConnect",
            src_device_type=DeviceType.BACKEND_SWITCH,  # generic matches both
            src_port_type=PortType.QSFP56,
            dst_device_type=DeviceType.BACKEND_SWITCH,  # generic matches both
            dst_port_type=PortType.QSFP56,
            src_direction=PortDirection.UPLINK,
            dst_direction=PortDirection.DOWNLINK,
            pattern=ConnectionPattern.ONE_TO_ONE,
        )]
        connections = generate_mapping(sample_racks, devices, rules, tray_height_m=2.6)
        assert len(connections) == 0, \
            f"Expected 0 leaf-to-leaf connections, got {len(connections)}"

    def test_no_spine_to_spine_connections(self, sample_racks):
        """Spine switches must never connect to other spine switches."""
        devices = [
            Device(name="Spine-01", device_type=DeviceType.BACKEND_SPINE, rack_id="R01",
                   ru_start=30, ru_height=1, ports=[
                       Port("P1", PortType.QSFP56, 200, PortDirection.UPLINK),
                   ]),
            Device(name="Spine-02", device_type=DeviceType.BACKEND_SPINE, rack_id="R02",
                   ru_start=30, ru_height=1, ports=[
                       Port("P1", PortType.QSFP56, 200, PortDirection.DOWNLINK),
                   ]),
        ]
        rules = [ConnectionRule(
            name="ShouldNotConnect",
            src_device_type=DeviceType.BACKEND_SWITCH,
            src_port_type=PortType.QSFP56,
            dst_device_type=DeviceType.BACKEND_SWITCH,
            dst_port_type=PortType.QSFP56,
            src_direction=PortDirection.UPLINK,
            dst_direction=PortDirection.DOWNLINK,
            pattern=ConnectionPattern.ONE_TO_ONE,
        )]
        connections = generate_mapping(sample_racks, devices, rules, tray_height_m=2.6)
        assert len(connections) == 0, \
            f"Expected 0 spine-to-spine connections, got {len(connections)}"

    def test_mesh_even_distribution(self, sample_racks):
        """Mesh round-robin distributes src ports evenly across dst devices."""
        ports_per_leaf = 7  # odd number to test uneven division
        devices = []
        # 1 leaf with uplink ports
        devices.append(Device(
            name="Leaf-01", device_type=DeviceType.BACKEND_LEAF, rack_id="R01",
            ru_start=30, ru_height=1,
            ports=[Port(f"P{i}", PortType.QSFP56, 200, PortDirection.UPLINK)
                   for i in range(1, ports_per_leaf + 1)]
        ))
        # 3 spines with plenty of downlink ports
        for s in range(1, 4):
            devices.append(Device(
                name=f"Spine-0{s}", device_type=DeviceType.BACKEND_SPINE,
                rack_id=f"R0{s+1}", ru_start=30, ru_height=1,
                ports=[Port(f"P{i}", PortType.QSFP56, 200, PortDirection.DOWNLINK)
                       for i in range(1, 33)]
            ))
        rules = [ConnectionRule(
            name="Leaf→Spine Mesh",
            src_device_type=DeviceType.BACKEND_LEAF,
            src_port_type=PortType.QSFP56,
            dst_device_type=DeviceType.BACKEND_SPINE,
            dst_port_type=PortType.QSFP56,
            src_direction=PortDirection.UPLINK,
            dst_direction=PortDirection.DOWNLINK,
            pattern=ConnectionPattern.MESH,
        )]
        connections = generate_mapping(sample_racks, devices, rules, tray_height_m=2.6)
        assert len(connections) == ports_per_leaf

        # Count per spine — should be 3+2+2 or 3+3+1, any distribution
        # should not exceed ceil(n/m)+1 difference
        from collections import Counter
        spine_counts = Counter(c.dst_device for c in connections)
        counts = list(spine_counts.values())
        assert max(counts) - min(counts) <= 1, \
            f"Uneven mesh distribution: {dict(spine_counts)}"
