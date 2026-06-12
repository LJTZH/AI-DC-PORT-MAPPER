"""Tests for distance calculation engine."""
import pytest
from src.distance import (
    calculate_cable_length_m,
    rack_horizontal_distance_m,
    port_center_height_mm,
    MM_PER_U,
)
from src.models import Rack, Device


class TestPortCenterHeight:
    def test_mid_rack_device(self):
        dev = Device(name="test", device_type="gpu_server",
                     rack_id="R01", ru_start=20, ru_height=4)
        expected_mm = (20 + 2) * MM_PER_U  # middle at RU 22
        assert port_center_height_mm(dev) == pytest.approx(expected_mm)

    def test_1u_device(self):
        dev = Device(name="test", device_type="eth_switch",
                     rack_id="R01", ru_start=42, ru_height=1)
        expected_mm = 42.5 * MM_PER_U
        assert port_center_height_mm(dev) == pytest.approx(expected_mm)


class TestRackHorizontalDistance:
    def test_same_rack(self):
        r1 = Rack(rack_id="R01", x_m=0.0, y_m=0.0)
        r2 = Rack(rack_id="R01", x_m=0.0, y_m=0.0)
        assert rack_horizontal_distance_m(r1, r2) == 0.0

    def test_adjacent_racks(self):
        r1 = Rack(rack_id="R01", x_m=0.0, y_m=0.0)
        r2 = Rack(rack_id="R02", x_m=0.8, y_m=0.0)
        assert rack_horizontal_distance_m(r1, r2) == 0.8

    def test_diagonal_racks(self):
        r1 = Rack(rack_id="R01", x_m=1.0, y_m=2.0)
        r2 = Rack(rack_id="R05", x_m=4.0, y_m=5.0)
        # Manhattan: |4-1| + |5-2| = 3 + 3 = 6
        assert rack_horizontal_distance_m(r1, r2) == 6.0


class TestCableLength:
    def test_same_rack_same_device(self):
        r = Rack(rack_id="R01", x_m=0.0, y_m=0.0)
        d1 = Device(name="d1", device_type="gpu_server",
                    rack_id="R01", ru_start=20, ru_height=4)
        d2 = Device(name="d2", device_type="gpu_server",
                    rack_id="R01", ru_start=20, ru_height=4)
        length = calculate_cable_length_m(r, r, d1, d2, tray_height_m=2.6)
        # Vertical: 2*(2600 - 22*44.45) = 2*(2600-977.9) = 2*1622.1 = 3244.2mm
        # Total = 3244.2/1000 * 1.15 ≈ 3.73m
        assert length > 3.0
        assert length < 5.0

    def test_adjacent_racks(self):
        r1 = Rack(rack_id="R01", x_m=0.0, y_m=0.0)
        r2 = Rack(rack_id="R02", x_m=0.8, y_m=0.0)
        d1 = Device(name="d1", device_type="gpu_server",
                    rack_id="R01", ru_start=20, ru_height=4)
        d2 = Device(name="d2", device_type="rdma_switch",
                    rack_id="R02", ru_start=30, ru_height=1)
        length = calculate_cable_length_m(r1, r2, d1, d2, tray_height_m=2.6)
        # Horizontal: 800mm
        # Vertical A: 2600 - 22*44.45 = 1622.1mm
        # Vertical B: 2600 - 30.5*44.45 = 1244.3mm
        # Total: (800 + 1622.1 + 1244.3)/1000 * 1.15 = 3666.4/1000*1.15 ≈ 4.22m
        assert length > 4.0
        assert length < 5.0

    def test_slack_factor(self):
        r = Rack(rack_id="R01", x_m=0.0, y_m=0.0)
        d1 = Device(name="d1", device_type="gpu_server",
                    rack_id="R01", ru_start=20, ru_height=4)
        d2 = Device(name="d2", device_type="gpu_server",
                    rack_id="R01", ru_start=20, ru_height=4)

        l1 = calculate_cable_length_m(r, r, d1, d2, tray_height_m=2.6, slack_factor=1.0)
        l2 = calculate_cable_length_m(r, r, d1, d2, tray_height_m=2.6, slack_factor=1.15)
        assert l2 > l1
        assert l2 == pytest.approx(l1 * 1.15, rel=0.01)
