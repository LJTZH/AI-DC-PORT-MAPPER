"""Distance calculation engine for data center cable routing.

Assumes overhead cable tray routing:
1. From source device port vertically up to cable tray
2. From rack center horizontally to cable tray in the aisle (tray_offset)
3. Along cable tray (Manhattan distance) to destination rack's tray entry
4. Horizontally from tray to destination rack center (tray_offset)
5. From cable tray down to destination device port

Total = horizontal(rack-to-tray + Manhattan + tray-to-rack) + vertical1 + vertical2 + slack_factor
"""

from .models import Rack, Device


# Physical constants
MM_PER_U = 44.45          # 1 rack unit = 44.45 mm
MM_PER_M = 1000.0
DEFAULT_SLACK_FACTOR = 1.15   # 15% slack


def port_center_height_mm(device: Device) -> float:
    """Calculate the center height of a device's ports from the floor (mm).

    Uses the device's midpoint in the rack.
    """
    ru_center = device.ru_start + device.ru_height / 2.0
    return ru_center * MM_PER_U


def rack_horizontal_distance_m(rack_a: Rack, rack_b: Rack) -> float:
    """Manhattan distance between two rack centers (meters).

    Models orthogonal cable tray routing — cables follow aisles,
    not diagonal paths.
    """
    return abs(rack_a.x_m - rack_b.x_m) + abs(rack_a.y_m - rack_b.y_m)


def calculate_cable_length_m(
    rack_a: Rack,
    rack_b: Rack,
    device_a: Device,
    device_b: Device,
    tray_height_m: float,
    slack_factor: float = DEFAULT_SLACK_FACTOR,
) -> float:
    """Calculate total cable length between two devices (meters).

    Args:
        rack_a, rack_b: Source and destination racks.
        device_a, device_b: Source and destination devices.
        tray_height_m: Height of the overhead cable tray from floor (meters).
        slack_factor: Multiplier for cable slack (default 1.15 = 15%).

    Returns:
        Total cable length in meters.
    """
    # Use rack-level tray_height_m from YAML layout if configured, else CLI default
    effective_tray_h = tray_height_m
    if rack_a.tray_height_m > 0:
        effective_tray_h = rack_a.tray_height_m
    elif rack_b.tray_height_m > 0:
        effective_tray_h = rack_b.tray_height_m

    tray_height_mm = effective_tray_h * MM_PER_M

    # Horizontal distance along cable tray (meters)
    horiz_m = rack_horizontal_distance_m(rack_a, rack_b)

    # Vertical distance: device → tray for both ends
    dev_a_h = port_center_height_mm(device_a)
    dev_b_h = port_center_height_mm(device_b)

    vert_a_mm = abs(tray_height_mm - dev_a_h)   # Vertical distance A ↔ tray
    vert_b_mm = abs(tray_height_mm - dev_b_h)   # Vertical distance B ↔ tray

    if rack_a.rack_id == rack_b.rack_id:
        # Same rack: cable routes up from lower device to tray, then down to
        # the higher device, plus 300 mm horizontal within the rack.
        total_mm = vert_a_mm + vert_b_mm + 300.0
    else:
        # Cross-rack routing. The aisle cable tray runs between rows.
        # Two cases:
        #
        # A) Same row: racks are side by side, cable routes directly within
        #    the row without entering the aisle cable tray.
        #    tray_offset does NOT apply.
        #
        # B) Different rows: cable must enter the aisle cable tray
        #    (tray_offset at each end), then travel along the tray.
        tray_offset_total_m = 0.0
        if rack_a.row != rack_b.row:
            # Different rows -> must enter/exit the aisle cable tray
            tray_offset_total_m = rack_a.tray_offset_m + rack_b.tray_offset_m

        total_mm = (horiz_m + tray_offset_total_m) * MM_PER_M + vert_a_mm + vert_b_mm

    total_m = total_mm / MM_PER_M

    # Apply slack
    return round(total_m * slack_factor, 2)
