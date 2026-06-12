"""Cable type matching based on port type and cable length.

Decision logic:
- Short distances (≤5m):  DAC (Direct Attach Copper) — lowest cost
- Medium distances (5-30m): AOC (Active Optical Cable) — no separate transceivers
- Long distances (>30m):  Optical transceivers + fiber patch cables
- Copper RJ45:            Cat6a patch cables (up to 100m)

Cable lengths are snapped to the nearest standard length >= calculated distance.
Custom standard lengths can be provided via a YAML config file.
"""

from dataclasses import dataclass, field
from typing import Optional

from .models import PortType


# ── Standard cable lengths (meters) by category ─────────────────────────

# Industry-standard available lengths for each cable type.
# Calculated lengths are rounded UP to the next available standard length.
DEFAULT_CABLE_LENGTHS: dict[str, list[float]] = {
    "DAC":    [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0],
    "AOC":    [1.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0],
    "Fiber":  [1.0, 2.0, 3.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 50.0, 100.0],
    "Copper": [0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0],
}


@dataclass
class CableMatchResult:
    cable_type: str              # e.g. "QSFP56 DAC"
    cable_category: str          # "DAC", "AOC", "Fiber", "Copper"
    length_m: float              # snapped standard length (e.g. 5.0)
    calculated_length_m: float   # original calculated length (e.g. 4.22)
    needs_transceiver: bool
    transceiver_type: str        # e.g. "QSFP56 SR4" if fiber
    transceiver_count: int       # 2 (one each end) for fiber


# ── Cable catalog ───────────────────────────────────────────────────────

@dataclass
class _CableEntry:
    port_type: str
    speed_gbps: int
    category: str            # DAC / AOC / Fiber / Copper
    cable_name_template: str
    min_m: float
    max_m: float
    transceiver_type: str = ""
    connector: str = ""


# Ordered cable catalog — first match wins
CABLE_CATALOG: list[_CableEntry] = [
    # ── QSFP112 400G (4×112G PAM4) ──
    _CableEntry("QSFP112", 400, "DAC",   "QSFP112 DAC",      0.5, 3.0),
    _CableEntry("QSFP112", 400, "AOC",   "QSFP112 AOC",      3.0, 30.0),
    _CableEntry("QSFP112", 400, "Fiber", "QSFP112 SR4 Fiber", 30.0, 500.0,
                transceiver_type="QSFP112 SR4", connector="MTP/MPO-12"),

    # ── OSFP 800G ──
    _CableEntry("OSFP", 800, "DAC",   "OSFP 800G DAC",      0.5, 3.0),
    _CableEntry("OSFP", 800, "AOC",   "OSFP 800G AOC",      3.0, 30.0),
    _CableEntry("OSFP", 800, "Fiber", "OSFP 800G SR8 Fiber", 30.0, 500.0,
                transceiver_type="OSFP 800G SR8", connector="MTP/MPO-16"),

    # ── QSFP56-DD 400G ──
    _CableEntry("QSFP56-DD", 400, "DAC",   "QSFP56-DD DAC",      0.5, 5.0),
    _CableEntry("QSFP56-DD", 400, "AOC",   "QSFP56-DD AOC",      5.0, 30.0),
    _CableEntry("QSFP56-DD", 400, "Fiber", "QSFP56-DD SR8 Fiber", 30.0, 500.0,
                transceiver_type="QSFP56-DD SR8", connector="MTP/MPO-16"),

    # ── QSFP56 200G ──
    _CableEntry("QSFP56", 200, "DAC",   "QSFP56 DAC",      0.5, 5.0),
    _CableEntry("QSFP56", 200, "AOC",   "QSFP56 AOC",      5.0, 30.0),
    _CableEntry("QSFP56", 200, "Fiber", "QSFP56 SR4 Fiber", 30.0, 500.0,
                transceiver_type="QSFP56 SR4", connector="MTP/MPO-12"),

    # ── QSFP28 100G ──
    _CableEntry("QSFP28", 100, "DAC",   "QSFP28 DAC",      0.5, 5.0),
    _CableEntry("QSFP28", 100, "AOC",   "QSFP28 AOC",      5.0, 30.0),
    _CableEntry("QSFP28", 100, "Fiber", "QSFP28 SR4 Fiber", 30.0, 500.0,
                transceiver_type="QSFP28 SR4", connector="MTP/MPO-12"),

    # ── QSFP+ 40G ──
    _CableEntry("QSFP+", 40, "DAC",   "QSFP+ DAC",      0.5, 5.0),
    _CableEntry("QSFP+", 40, "AOC",   "QSFP+ AOC",      5.0, 30.0),
    _CableEntry("QSFP+", 40, "Fiber", "QSFP+ SR4 Fiber", 30.0, 500.0,
                transceiver_type="QSFP+ SR4", connector="MTP/MPO-12"),

    # ── SFP28 25G ──
    _CableEntry("SFP28", 25, "DAC",   "SFP28 DAC",      0.5, 5.0),
    _CableEntry("SFP28", 25, "AOC",   "SFP28 AOC",      5.0, 30.0),
    _CableEntry("SFP28", 25, "Fiber", "SFP28 SR Fiber",  30.0, 500.0,
                transceiver_type="SFP28 SR", connector="LC"),

    # ── SFP+ 10G ──
    _CableEntry("SFP+", 10, "DAC",   "SFP+ DAC",      0.5, 5.0),
    _CableEntry("SFP+", 10, "AOC",   "SFP+ AOC",      5.0, 30.0),
    _CableEntry("SFP+", 10, "Fiber", "SFP+ SR Fiber",  30.0, 500.0,
                transceiver_type="SFP+ SR", connector="LC"),

    # ── SFP 1G ──
    _CableEntry("SFP", 1, "DAC",   "SFP DAC",      0.5, 5.0),
    _CableEntry("SFP", 1, "Fiber", "SFP SX Fiber",  0.5, 550.0,
                transceiver_type="SFP SX", connector="LC"),

    # ── RJ45 1G/10G ──
    _CableEntry("RJ45", 10, "Copper", "Cat6a Patch Cable",  0.5, 100.0),
    _CableEntry("RJ45", 1, "Copper",  "Cat6 Patch Cable",   0.5, 100.0),

    # ── OSFP 400G ──
    _CableEntry("OSFP", 400, "DAC",   "OSFP DAC",      0.5, 5.0),
    _CableEntry("OSFP", 400, "AOC",   "OSFP AOC",      5.0, 30.0),
    _CableEntry("OSFP", 400, "Fiber", "OSFP SR8 Fiber", 30.0, 500.0,
                transceiver_type="OSFP SR8", connector="MTP/MPO-16"),
]


# ── Length snapping ─────────────────────────────────────────────────────

def snap_to_standard_length(
    calculated_m: float,
    category: str,
    custom_lengths: Optional[dict[str, list[float]]] = None,
) -> float:
    """Snap a calculated cable length to the nearest available standard length.

    Always rounds UP to the next standard length >= calculated.
    If calculated exceeds all standard lengths, returns the max and logs a warning.

    Args:
        calculated_m: The calculated cable length (with slack).
        category: Cable category — "DAC", "AOC", "Fiber", or "Copper".
        custom_lengths: Optional dict mapping category → list of standard lengths (m).

    Returns:
        Standard cable length in meters (integer if exact, else float).
    """
    lengths = (custom_lengths or DEFAULT_CABLE_LENGTHS).get(category, [])
    if not lengths:
        # No standard lengths defined for this category — return calculated as-is
        return round(calculated_m, 2)

    # Sort and find first length >= calculated
    sorted_lengths = sorted(lengths)

    for std_len in sorted_lengths:
        if std_len >= calculated_m:
            return std_len

    # Calculated exceeds max standard — use max
    return sorted_lengths[-1]


def load_cable_lengths_from_file(filepath: str) -> dict[str, list[float]]:
    """Load custom cable lengths from a YAML file.

    Example YAML:
    ```yaml
    cable_lengths:
      DAC: [0.5, 1, 1.5, 2, 3, 5]
      AOC: [1, 3, 5, 10, 15, 20, 30]
      Fiber: [1, 3, 5, 10, 15, 30, 50]
      Copper: [0.5, 1, 2, 3, 5, 10, 15]
    ```
    """
    import yaml
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    lengths = data.get("cable_lengths", data)
    if not isinstance(lengths, dict):
        raise ValueError(
            f"Cable length config must have a 'cable_lengths' key. "
            f"Got keys: {sorted(lengths.keys()) if isinstance(lengths, dict) else type(lengths).__name__}"
        )

    # Validate and convert
    result: dict[str, list[float]] = {}
    for category, lengths_list in lengths.items():
        if not isinstance(lengths_list, list):
            raise ValueError(f"Cable lengths for '{category}' must be a list, got {type(lengths_list).__name__}")
        result[str(category)] = [float(v) for v in lengths_list]

    return result


# ── Matching functions ──────────────────────────────────────────────────

def match_cable(
    port_type: PortType,
    speed_gbps: int,
    distance_m: float,
    catalog: Optional[list[_CableEntry]] = None,
    custom_lengths: Optional[dict[str, list[float]]] = None,
    cable_preference: str = "auto",
) -> CableMatchResult:
    """Find the best cable type for a given port type and distance.

    Args:
        port_type: The port connector type (QSFP56, SFP28, etc.)
        speed_gbps: Port speed in Gbps.
        distance_m: Calculated cable length in meters (before snapping).
        catalog: Optional custom cable catalog.
        custom_lengths: Optional dict of category → list of standard lengths (m).
        cable_preference: "auto" (distance-based), "dac", "aoc", or "fiber".

    Returns:
        CableMatchResult with standard length and transceiver info.

    Raises:
        ValueError: If no suitable cable found or distance exceeds limits.
    """
    catalog = catalog or CABLE_CATALOG
    port_type_str = port_type.value

    # Find matching entries for this port type and speed
    candidates = [
        e for e in catalog
        if e.port_type == port_type_str and e.speed_gbps == speed_gbps
    ]

    # Fallback: match by port type only (ignore speed)
    if not candidates:
        candidates = [e for e in catalog if e.port_type == port_type_str]

    if not candidates:
        raise ValueError(
            f"No cable entries found for port type {port_type_str} "
            f"at {speed_gbps}Gbps"
        )

    # ── Apply cable preference override ──
    # Map preference to catalog category name
    preference_map = {
        "dac": "DAC",
        "aoc": "AOC",
        "fiber": "Fiber",
    }

    if cable_preference != "auto":
        target_category = preference_map.get(cable_preference)
        if target_category is None:
            raise ValueError(
                f"Invalid cable_preference '{cable_preference}'. "
                f"Must be one of: auto, dac, aoc, fiber."
            )

        preferred = [e for e in candidates
                     if e.category.lower() == target_category.lower()]
        if not preferred:
            raise ValueError(
                f"No {target_category} cable entry found for port type "
                f"{port_type_str} at {speed_gbps}Gbps. "
                f"Check your cable_preference setting in the connection rule."
            )

        # Use the preferred entry — check distance compatibility
        for entry in preferred:
            if entry.min_m <= distance_m <= entry.max_m:
                standard_len = snap_to_standard_length(distance_m, entry.category, custom_lengths)
                return CableMatchResult(
                    cable_type=entry.cable_name_template,
                    cable_category=entry.category,
                    length_m=standard_len,
                    calculated_length_m=round(distance_m, 2),
                    needs_transceiver=bool(entry.transceiver_type),
                    transceiver_type=entry.transceiver_type,
                    transceiver_count=2 if entry.transceiver_type else 0,
                )

        # Distance doesn't fit preferred category — force it anyway with a warning
        entry = preferred[0]
        standard_len = snap_to_standard_length(distance_m, entry.category, custom_lengths)
        return CableMatchResult(
            cable_type=entry.cable_name_template,
            cable_category=entry.category,
            length_m=standard_len,
            calculated_length_m=round(distance_m, 2),
            needs_transceiver=bool(entry.transceiver_type),
            transceiver_type=entry.transceiver_type,
            transceiver_count=2 if entry.transceiver_type else 0,
        )

    # ── Auto mode: distance-based matching ──
    # Find the first entry whose distance range covers our distance
    for entry in candidates:
        if entry.min_m <= distance_m <= entry.max_m:
            # Snap to standard length
            standard_len = snap_to_standard_length(distance_m, entry.category, custom_lengths)

            return CableMatchResult(
                cable_type=entry.cable_name_template,
                cable_category=entry.category,
                length_m=standard_len,
                calculated_length_m=round(distance_m, 2),
                needs_transceiver=bool(entry.transceiver_type),
                transceiver_type=entry.transceiver_type,
                transceiver_count=2 if entry.transceiver_type else 0,
            )

    # No direct match — check if distance exceeds all options
    max_dist = max(e.max_m for e in candidates)
    raise ValueError(
        f"Cable length {distance_m:.1f}m exceeds maximum {max_dist:.1f}m "
        f"for port type {port_type_str} at {speed_gbps}Gbps. "
        f"Consider adding repeaters or re-routing."
    )


def get_port_type_compatibility(
    port_type_a: PortType,
    port_type_b: PortType,
) -> tuple[bool, str]:
    """Check if two port types are compatible for direct connection.

    Returns:
        (is_compatible, message) tuple.
    """
    # Same type is always compatible
    if port_type_a == port_type_b:
        return True, "Same port type — compatible"

    # Breakout scenarios: higher-speed port → multiple lower-speed ports
    breakout_pairs = {
        # 800G breakouts (OSFP 800G)
        (PortType.OSFP, PortType.QSFP56_DD):    "OSFP 800G→2×QSFP56-DD breakout possible",
        (PortType.OSFP, PortType.QSFP56):       "OSFP 800G→4×QSFP56 breakout possible",
        (PortType.OSFP, PortType.QSFP28):       "OSFP 800G→8×QSFP28 breakout possible",
        # 400G breakouts / fan-outs (QSFP112)
        (PortType.QSFP112, PortType.QSFP56):    "QSFP112→2×QSFP56 fan-out possible",
        (PortType.QSFP112, PortType.QSFP28):    "QSFP112→4×QSFP28 fan-out possible",
        # 400G breakouts (QSFP56-DD)
        (PortType.QSFP56_DD, PortType.QSFP56): "QSFP56-DD→2×QSFP56 breakout possible",
        (PortType.QSFP56_DD, PortType.QSFP28): "QSFP56-DD→4×QSFP28 breakout possible",
        (PortType.QSFP56_DD, PortType.SFP28):  "QSFP56-DD→8×SFP28 breakout possible",
        # 200G breakouts
        (PortType.QSFP56, PortType.QSFP28):   "QSFP56→2×QSFP28 breakout possible",
        (PortType.QSFP56, PortType.SFP28):    "QSFP56→4×SFP28 breakout possible",
        # 100G breakouts
        (PortType.QSFP28, PortType.SFP_PLUS): "QSFP28→4×SFP+ breakout possible",
        (PortType.QSFP28, PortType.SFP28):    "QSFP28→4×SFP28 breakout possible",
        # 40G breakouts
        (PortType.QSFP_PLUS, PortType.SFP_PLUS): "QSFP+→4×SFP+ breakout possible",
    }

    pair = (port_type_a, port_type_b)
    reverse_pair = (port_type_b, port_type_a)

    if pair in breakout_pairs:
        return True, breakout_pairs[pair]
    if reverse_pair in breakout_pairs:
        return True, breakout_pairs[reverse_pair]

    return False, f"Incompatible port types: {port_type_a.value} ↔ {port_type_b.value}"
