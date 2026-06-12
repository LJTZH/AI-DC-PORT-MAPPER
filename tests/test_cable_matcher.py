"""Tests for cable type matching."""
import pytest
from src.cable_matcher import (
    match_cable, get_port_type_compatibility,
    snap_to_standard_length, load_cable_lengths_from_file,
    DEFAULT_CABLE_LENGTHS,
)
from src.models import PortType


class TestSnapToStandardLength:
    def test_snap_dac_rounds_up(self):
        result = snap_to_standard_length(3.3, "DAC")
        assert result == 5.0  # 3.0 < 3.3 → next is 5.0

    def test_snap_dac_exact_match(self):
        result = snap_to_standard_length(3.0, "DAC")
        assert result == 3.0

    def test_snap_aoc_mid_range(self):
        result = snap_to_standard_length(8.5, "AOC")
        assert result == 10.0

    def test_snap_fiber_exceeds_max(self):
        result = snap_to_standard_length(200.0, "Fiber")
        assert result == 100.0  # max standard

    def test_snap_copper(self):
        result = snap_to_standard_length(5.2, "Copper")
        assert result == 7.0

    def test_custom_lengths(self):
        custom = {"DAC": [0.5, 2.0, 4.0, 6.0]}
        result = snap_to_standard_length(3.0, "DAC", custom_lengths=custom)
        assert result == 4.0

    def test_empty_lengths_fallback(self):
        result = snap_to_standard_length(3.0, "UnknownCategory")
        assert result == 3.0  # no standard lengths defined, returns as-is


class TestCableMatching:
    def test_dac_short_distance(self):
        result = match_cable(PortType.QSFP56, 200, 3.0)
        assert result.cable_category == "DAC"
        assert "DAC" in result.cable_type
        assert not result.needs_transceiver
        assert result.length_m == 3.0  # snapped
        assert result.calculated_length_m == 3.0

    def test_dac_snaps_up(self):
        """3.3m → DAC → snapped to 5.0m (standard DAC length)."""
        result = match_cable(PortType.QSFP56, 200, 3.3)
        assert result.cable_category == "DAC"
        assert result.length_m == 5.0
        assert result.calculated_length_m == 3.3

    def test_aoc_medium_distance(self):
        result = match_cable(PortType.QSFP56, 200, 10.0)
        assert result.cable_category == "AOC"
        assert "AOC" in result.cable_type
        assert not result.needs_transceiver

    def test_fiber_long_distance(self):
        result = match_cable(PortType.QSFP56, 200, 50.0)
        assert result.cable_category == "Fiber"
        assert result.needs_transceiver
        assert result.transceiver_count == 2
        assert result.length_m == 50.0  # standard fiber length

    def test_sfp28_dac(self):
        result = match_cable(PortType.SFP28, 25, 2.0)
        assert result.cable_category == "DAC"
        assert "SFP28" in result.cable_type

    def test_sfp_plus_aoc(self):
        result = match_cable(PortType.SFP_PLUS, 10, 15.0)
        assert result.cable_category == "AOC"
        assert result.length_m == 15.0

    def test_rj45_copper(self):
        result = match_cable(PortType.RJ45, 1, 30.0)
        assert result.cable_category == "Copper"
        assert "Cat" in result.cable_type
        assert not result.needs_transceiver

    def test_distance_too_long(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            match_cable(PortType.QSFP56, 200, 600.0)

    def test_boundary_dac_to_aoc(self):
        """At exactly 5m, DAC should still be selected (boundary inclusive)."""
        result = match_cable(PortType.QSFP56, 200, 5.0)
        assert result.cable_category == "DAC"

    # ── QSFP112 800G ──

    def test_qsfp112_dac_short(self):
        result = match_cable(PortType.QSFP112, 800, 2.0)
        assert result.cable_category == "DAC"
        assert "QSFP112 DAC" == result.cable_type
        assert not result.needs_transceiver

    def test_qsfp112_aoc_medium(self):
        result = match_cable(PortType.QSFP112, 800, 15.0)
        assert result.cable_category == "AOC"
        assert "QSFP112 AOC" == result.cable_type

    def test_qsfp112_fiber_long(self):
        result = match_cable(PortType.QSFP112, 800, 80.0)
        assert result.cable_category == "Fiber"
        assert result.needs_transceiver
        assert result.transceiver_type == "QSFP112 SR8"
        assert result.transceiver_count == 2

    def test_qsfp112_boundary_dac_3m(self):
        """At exactly 3m, QSFP112 DAC is still selected."""
        result = match_cable(PortType.QSFP112, 800, 3.0)
        assert result.cable_category == "DAC"

    def test_qsfp112_boundary_aoc_3_01m(self):
        """Just beyond 3m, AOC takes over for QSFP112."""
        result = match_cable(PortType.QSFP112, 800, 3.1)
        assert result.cable_category == "AOC"

    # ── OSFP 800G ──

    def test_osfp_800g_dac(self):
        result = match_cable(PortType.OSFP, 800, 1.5)
        assert result.cable_category == "DAC"
        assert "OSFP 800G DAC" == result.cable_type

    def test_osfp_800g_aoc(self):
        result = match_cable(PortType.OSFP, 800, 10.0)
        assert result.cable_category == "AOC"
        assert "OSFP 800G AOC" == result.cable_type

    def test_osfp_800g_fiber(self):
        result = match_cable(PortType.OSFP, 800, 100.0)
        assert result.cable_category == "Fiber"
        assert result.transceiver_type == "OSFP 800G SR8"

    def test_osfp_400g_still_works(self):
        """OSFP at 400G uses the legacy 400G entries (not 800G)."""
        result = match_cable(PortType.OSFP, 400, 2.0)
        assert result.cable_category == "DAC"
        assert "OSFP DAC" == result.cable_type  # 400G entry, not 800G


class TestPortCompatibility:
    def test_same_type_compatible(self):
        ok, msg = get_port_type_compatibility(PortType.QSFP56, PortType.QSFP56)
        assert ok

    def test_breakout_qsfp56_to_sfp28(self):
        ok, msg = get_port_type_compatibility(PortType.QSFP56, PortType.SFP28)
        assert ok
        assert "breakout" in msg.lower()

    def test_incompatible_types(self):
        ok, msg = get_port_type_compatibility(PortType.QSFP56, PortType.RJ45)
        assert not ok

    # ── QSFP112 / OSFP 800G breakouts ──

    def test_breakout_qsfp112_to_qsfp56_dd(self):
        ok, msg = get_port_type_compatibility(PortType.QSFP112, PortType.QSFP56_DD)
        assert ok
        assert "QSFP112" in msg

    def test_breakout_qsfp112_to_qsfp56(self):
        ok, msg = get_port_type_compatibility(PortType.QSFP112, PortType.QSFP56)
        assert ok

    def test_breakout_osfp_to_qsfp56_dd(self):
        ok, msg = get_port_type_compatibility(PortType.OSFP, PortType.QSFP56_DD)
        assert ok

    def test_breakout_osfp_to_qsfp112_compatible(self):
        ok, msg = get_port_type_compatibility(PortType.OSFP, PortType.QSFP112)
        assert ok
        assert "compatible" in msg.lower()

    def test_breakout_qsfp56_dd_to_sfp28(self):
        ok, msg = get_port_type_compatibility(PortType.QSFP56_DD, PortType.SFP28)
        assert ok

    def test_breakout_reverse_direction(self):
        """Breakout is symmetric: A→B same as B→A."""
        ok1, _ = get_port_type_compatibility(PortType.QSFP112, PortType.QSFP56)
        ok2, _ = get_port_type_compatibility(PortType.QSFP56, PortType.QSFP112)
        assert ok1 == ok2
