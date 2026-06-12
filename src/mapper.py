"""Port mapping core — matches source ports to destination ports
based on connection rules, calculates cable lengths, and generates
complete Connection objects.
"""

import warnings
from collections import defaultdict

from .models import (
    Device, Port, Rack, Connection, ConnectionRule, ConnectionPattern,
    DeviceType, PortDirection, PortType,
)
from .distance import calculate_cable_length_m
from .cable_matcher import match_cable, get_port_type_compatibility, CableMatchResult


def _build_index(devices: list[Device]) -> dict[str, Device]:
    return {d.name: d for d in devices}


def _build_rack_index(racks: list[Rack]) -> dict[str, Rack]:
    return {r.rack_id: r for r in racks}


# Generic device types match their specific leaf/spine subtypes.
_DEVICE_TYPE_MATCH: dict[DeviceType, set[DeviceType]] = {
    DeviceType.BACKEND_SWITCH:  {DeviceType.BACKEND_LEAF, DeviceType.BACKEND_SPINE, DeviceType.BACKEND_SWITCH},
    DeviceType.FRONTEND_SWITCH: {DeviceType.FRONTEND_LEAF, DeviceType.FRONTEND_SPINE, DeviceType.FRONTEND_SWITCH},
    # Legacy types also match the new generic + specific types
    DeviceType.RDMA_SWITCH: {DeviceType.BACKEND_LEAF, DeviceType.BACKEND_SPINE, DeviceType.BACKEND_SWITCH, DeviceType.RDMA_SWITCH},
    DeviceType.ETH_SWITCH:  {DeviceType.FRONTEND_LEAF, DeviceType.FRONTEND_SPINE, DeviceType.FRONTEND_SWITCH, DeviceType.ETH_SWITCH},
}

# Leaf ↔ Leaf and Spine ↔ Spine are physically invalid within the same network.
# Only Leaf ↔ Spine (or Leaf/Spine ↔ Server/Gateway) connections are allowed.
_INCOMPATIBLE_PAIRS: set[tuple[DeviceType, DeviceType]] = {
    (DeviceType.BACKEND_LEAF, DeviceType.BACKEND_LEAF),
    (DeviceType.BACKEND_SPINE, DeviceType.BACKEND_SPINE),
    (DeviceType.FRONTEND_LEAF, DeviceType.FRONTEND_LEAF),
    (DeviceType.FRONTEND_SPINE, DeviceType.FRONTEND_SPINE),
}


def _device_matches(rule_type: DeviceType, device_type: DeviceType) -> bool:
    """Check if a device's type satisfies a rule's device type requirement.

    Generic types (BACKEND_SWITCH) match their specific leaf/spine subtypes,
    and legacy types (RDMA_SWITCH) match the new backend types.
    """
    if rule_type == device_type:
        return True
    matched = _DEVICE_TYPE_MATCH.get(rule_type, set())
    return device_type in matched


def _device_pair_valid(src_type: DeviceType, dst_type: DeviceType) -> bool:
    """Reject physically invalid pairings like leaf↔leaf or spine↔spine.

    Within the same network family, leaf switches must only connect to spine
    switches (or servers), never to other leaves.  Spine switches must only
    connect to leaves, never to other spines.
    """
    return (src_type, dst_type) not in _INCOMPATIBLE_PAIRS


def _select_ports(
    devices: list[Device],
    device_type: DeviceType,
    port_type: PortType,
    direction: PortDirection,
) -> list[tuple[Device, Port]]:
    """Collect all unassigned ports matching the criteria."""
    result = []
    for dev in devices:
        if not _device_matches(device_type, dev.device_type):
            continue
        for port in dev.ports:
            if port.assigned:
                continue
            if port.port_type != port_type:
                continue
            # Match direction: rule=any matches anything, otherwise port must match or be any
            if direction != PortDirection.ANY and port.direction != PortDirection.ANY and port.direction != direction:
                continue
            result.append((dev, port))
    return result


def _mark_assigned(device: Device, port: Port):
    """Mark a port as assigned."""
    # Find the port in the device's port list and mark it
    for p in device.ports:
        if p.port_name == port.port_name:
            p.assigned = True
            return


def _make_connection(
    src_dev: Device, src_port: Port,
    dst_dev: Device, dst_port: Port,
    cable: "CableMatchResult",
    rule_name: str,
) -> Connection | None:
    """Build a Connection with device location metadata.

    Returns None if the device pair is physically invalid (e.g. leaf↔leaf).
    """
    if not _device_pair_valid(src_dev.device_type, dst_dev.device_type):
        return None

    def _ru_label(dev: Device) -> str:
        if dev.ru_height == 1:
            return str(dev.ru_start)
        return f"{dev.ru_start}-{dev.ru_start + dev.ru_height - 1}"

    return Connection(
        src_device=src_dev.name,
        src_port=src_port.port_name,
        src_port_type=src_port.port_type.value,
        dst_device=dst_dev.name,
        dst_port=dst_port.port_name,
        dst_port_type=dst_port.port_type.value,
        cable_type=cable.cable_type,
        cable_length_m=cable.length_m,
        src_rack=src_dev.rack_id,
        src_ru=_ru_label(src_dev),
        src_port_direction=src_port.direction.value,
        dst_rack=dst_dev.rack_id,
        dst_ru=_ru_label(dst_dev),
        dst_port_direction=dst_port.direction.value,
        calculated_length_m=cable.calculated_length_m,
        needs_transceiver=cable.needs_transceiver,
        transceiver_type=cable.transceiver_type,
        notes=rule_name,
    )


def generate_mapping(
    racks: list[Rack],
    devices: list[Device],
    rules: list[ConnectionRule],
    tray_height_m: float,
    slack_factor: float = 1.15,
    custom_lengths: dict[str, list[float]] | None = None,
) -> list[Connection]:
    """Generate the complete port mapping table.

    Args:
        racks: List of all racks with coordinates.
        devices: List of all devices with ports.
        rules: Connection rules defining what connects to what.
        tray_height_m: Cable tray height from floor (meters).
        slack_factor: Cable slack multiplier.
        custom_lengths: Optional dict of category → list of standard lengths (m).

    Returns:
        List of Connection objects ready for output.
    """
    rack_index = _build_rack_index(racks)
    device_index = _build_index(devices)

    # Sort rules by priority (lower number = higher priority)
    sorted_rules = sorted(rules, key=lambda r: r.priority)

    # Reset all port assignments
    for dev in devices:
        for port in dev.ports:
            port.assigned = False

    connections: list[Connection] = []
    errors: list[str] = []
    warnings: list[str] = []

    for rule in sorted_rules:
        try:
            rule_conns = _apply_rule(
                rule, devices, rack_index, tray_height_m, slack_factor, custom_lengths
            )
            connections.extend(rule_conns)
        except ValueError as e:
            errors.append(f"[{rule.name}] {e}")

    if errors:
        err_msg = "\n".join(errors)
        raise ValueError(f"Mapping errors encountered:\n{err_msg}")

    return connections


def _apply_rule(
    rule: ConnectionRule,
    devices: list[Device],
    rack_index: dict[str, Rack],
    tray_height_m: float,
    slack_factor: float,
    custom_lengths: dict[str, list[float]] | None = None,
) -> list[Connection]:
    """Apply a single connection rule to generate connections."""
    src_ports = _select_ports(
        devices, rule.src_device_type, rule.src_port_type, rule.src_direction
    )
    dst_ports = _select_ports(
        devices, rule.dst_device_type, rule.dst_port_type, rule.dst_direction
    )

    if not src_ports:
        raise ValueError(
            f"No available source ports for {rule.src_device_type.value} "
            f"({rule.src_port_type.value})"
        )
    if not dst_ports:
        raise ValueError(
            f"No available destination ports for {rule.dst_device_type.value} "
            f"({rule.dst_port_type.value})"
        )

    if rule.pattern == ConnectionPattern.ONE_TO_ONE:
        return _match_one_to_one(
            rule, src_ports, dst_ports, rack_index, tray_height_m, slack_factor, custom_lengths
        )
    elif rule.pattern == ConnectionPattern.MANY_TO_ONE:
        return _match_many_to_one(
            rule, src_ports, dst_ports, rack_index, tray_height_m, slack_factor, custom_lengths
        )
    elif rule.pattern == ConnectionPattern.MESH:
        return _match_mesh(
            rule, src_ports, dst_ports, rack_index, tray_height_m, slack_factor, custom_lengths
        )
    else:
        raise ValueError(f"Unknown connection pattern: {rule.pattern}")


def _match_one_to_one(
    rule: ConnectionRule,
    src_ports: list[tuple[Device, Port]],
    dst_ports: list[tuple[Device, Port]],
    rack_index: dict[str, Rack],
    tray_height_m: float,
    slack_factor: float,
    custom_lengths: dict[str, list[float]] | None = None,
) -> list[Connection]:
    """One-to-one matching: pair ports by index order.

    When src and dst device types are the same, we match src[i] to dst[i]
    while avoiding self-connections and respecting destination port availability.
    """
    connections = []
    dst_used = set()  # Track used dst ports by (device_name, port_name)
    dst_by_index = list(dst_ports)

    for src_dev, src_port in src_ports:
        for j, (dst_dev, dst_port) in enumerate(dst_by_index):
            dst_key = (dst_dev.name, dst_port.port_name)
            if dst_key in dst_used:
                continue
            if src_dev.name == dst_dev.name and src_port.port_name == dst_port.port_name:
                continue
            if not rule.allow_same_rack and src_dev.rack_id == dst_dev.rack_id:
                continue

            # Guard against missing rack references
            rack_a = rack_index.get(src_dev.rack_id)
            if rack_a is None:
                warnings.warn(
                    f"[{rule.name}] Device '{src_dev.name}' references "
                    f"unknown rack '{src_dev.rack_id}' — skipping"
                )
                continue
            rack_b = rack_index.get(dst_dev.rack_id)
            if rack_b is None:
                warnings.warn(
                    f"[{rule.name}] Device '{dst_dev.name}' references "
                    f"unknown rack '{dst_dev.rack_id}' — skipping"
                )
                continue

            length_m = calculate_cable_length_m(
                rack_a, rack_b, src_dev, dst_dev, tray_height_m, slack_factor
            )

            if rule.max_distance_m and length_m > rule.max_distance_m:
                continue

            try:
                cable = match_cable(src_port.port_type, src_port.speed_gbps, length_m,
                                    custom_lengths=custom_lengths,
                                    cable_preference=rule.cable_preference)
            except ValueError:
                continue

            conn = _make_connection(
                src_dev, src_port, dst_dev, dst_port, cable, rule.name,
            )
            if conn is not None:
                connections.append(conn)
                _mark_assigned(src_dev, src_port)
                _mark_assigned(dst_dev, dst_port)
                dst_used.add(dst_key)
                break

    return connections


def _match_many_to_one(
    rule: ConnectionRule,
    src_ports: list[tuple[Device, Port]],
    dst_ports: list[tuple[Device, Port]],
    rack_index: dict[str, Rack],
    tray_height_m: float,
    slack_factor: float,
    custom_lengths: dict[str, list[float]] | None = None,
) -> list[Connection]:
    """Many-to-one matching: N source ports → 1 destination port.

    Grouped by rack affinity: same-rack sources prefer same-rack destination.
    """
    connections = []
    n_per_group = rule.ports_per_group

    if len(dst_ports) == 0:
        return connections

    src_by_rack: dict[str, list[tuple[Device, Port]]] = defaultdict(list)
    for dev, port in src_ports:
        src_by_rack[dev.rack_id].append((dev, port))

    # Track unmapped source ports for warning
    all_src_names: set[tuple[str, str]] = {(d.name, p.port_name) for d, p in src_ports}
    mapped_src: set[tuple[str, str]] = set()

    dst_idx = 0
    total_connected = 0

    for rack_id, rack_srcs in src_by_rack.items():
        for i in range(0, len(rack_srcs), n_per_group):
            if dst_idx >= len(dst_ports):
                # Collect remaining unmapped source ports for warning
                remaining = []
                for dev, port in rack_srcs[i:]:
                    remaining.append(f"{dev.name}:{port.port_name}")
                if remaining:
                    warnings.warn(
                        f"[{rule.name}] Destination ports exhausted; "
                        f"{len(remaining)} source port(s) in rack {rack_id} "
                        f"left unmapped: {', '.join(remaining[:10])}"
                        f"{'...' if len(remaining) > 10 else ''}"
                    )
                break

            group = rack_srcs[i:i + n_per_group]
            dst_dev, dst_port = dst_ports[dst_idx]

            # Check same-rack restriction
            if not rule.allow_same_rack:
                # All src ports in this group share the same rack_id (grouped by rack)
                first_src_dev = group[0][0] if group else None
                if first_src_dev and first_src_dev.rack_id == dst_dev.rack_id:
                    # Skip this group — same rack not allowed
                    continue

            for src_dev, src_port in group:
                # Guard against missing rack references
                src_rack = rack_index.get(src_dev.rack_id)
                if src_rack is None:
                    warnings.warn(
                        f"[{rule.name}] Device '{src_dev.name}' references "
                        f"unknown rack '{src_dev.rack_id}' — skipping"
                    )
                    continue
                dst_rack = rack_index.get(dst_dev.rack_id)
                if dst_rack is None:
                    warnings.warn(
                        f"[{rule.name}] Device '{dst_dev.name}' references "
                        f"unknown rack '{dst_dev.rack_id}' — skipping"
                    )
                    continue

                length_m = calculate_cable_length_m(
                    src_rack, dst_rack, src_dev, dst_dev, tray_height_m, slack_factor
                )

                if rule.max_distance_m and length_m > rule.max_distance_m:
                    continue

                try:
                    cable = match_cable(src_port.port_type, src_port.speed_gbps, length_m,
                                        custom_lengths=custom_lengths,
                                        cable_preference=rule.cable_preference)
                except ValueError:
                    continue

                conn = _make_connection(
                    src_dev, src_port, dst_dev, dst_port, cable, rule.name,
                )
                if conn is not None:
                    connections.append(conn)
                    _mark_assigned(src_dev, src_port)
                    mapped_src.add((src_dev.name, src_port.port_name))
                    total_connected += 1

            _mark_assigned(dst_dev, dst_port)
            dst_idx += 1

    return connections


def _match_mesh(
    rule: ConnectionRule,
    src_ports: list[tuple[Device, Port]],
    dst_ports: list[tuple[Device, Port]],
    rack_index: dict[str, Rack],
    tray_height_m: float,
    slack_factor: float,
    custom_lengths: dict[str, list[float]] | None = None,
) -> list[Connection]:
    """Mesh (all-to-all) matching for Spine-Leaf topologies.

    Correctly models physical cabling: each port = exactly one cable connector.
    Src ports are distributed round-robin across eligible dst devices so every
    (src_device, dst_device) pair gets a fair share of connections.

    Example: 4 RDMA switches with 8 uplink ports each.
    Switch-01 has 8 uplink ports → distributed across 3 other switches
    ≈ 3+3+2 connections, one physical cable per port.
    """
    connections = []

    # Group available ports by device name
    src_by_device: dict[str, list[tuple[Device, Port]]] = defaultdict(list)
    for dev, port in src_ports:
        src_by_device[dev.name].append((dev, port))

    dst_by_device: dict[str, list[tuple[Device, Port]]] = defaultdict(list)
    for dev, port in dst_ports:
        dst_by_device[dev.name].append((dev, port))

    for src_dev_name, src_list in src_by_device.items():
        # Build the ordered list of eligible dst device names for this src device.
        # Filter out: self, same-rack (if rule forbids), and incompatible roles
        # (e.g. leaf↔leaf) so the round-robin only sees valid targets.
        src_dev_type = src_list[0][0].device_type if src_list else None
        eligible_dst_names: list[str] = []
        for dst_dev_name in dst_by_device:
            if src_dev_name == dst_dev_name:
                continue
            dst_dev_type = dst_by_device[dst_dev_name][0][0].device_type if dst_by_device[dst_dev_name] else None
            if src_dev_type is not None and dst_dev_type is not None:
                if not _device_pair_valid(src_dev_type, dst_dev_type):
                    continue  # leaf↔leaf or spine↔spine — skip
            if not rule.allow_same_rack:
                src_rack = src_list[0][0].rack_id if src_list else None
                dst_rack = dst_by_device[dst_dev_name][0][0].rack_id if dst_by_device[dst_dev_name] else None
                if src_rack == dst_rack:
                    continue
            eligible_dst_names.append(dst_dev_name)

        if not eligible_dst_names:
            continue  # No suitable dst devices for this src device

        # Round-robin: distribute src ports evenly across eligible dst devices
        rr_idx = 0
        n_dst = len(eligible_dst_names)

        for src_dev, src_port in src_list:
            if src_port.assigned:
                continue

            # Try up to one full round of dst devices to find an available port
            connected = False
            for attempt in range(n_dst):
                dst_dev_name = eligible_dst_names[(rr_idx + attempt) % n_dst]
                dst_list = dst_by_device[dst_dev_name]

                # Find first available dst port on this device
                dst_pair = None
                for d_dev, d_port in dst_list:
                    if not d_port.assigned:
                        dst_pair = (d_dev, d_port)
                        break

                if dst_pair is None:
                    continue  # This dst device is full, try next

                dst_dev, dst_port = dst_pair

                # Rack distance check — skip if rack info is missing (don't waste ports)
                rack_a = rack_index.get(src_dev.rack_id)
                rack_b = rack_index.get(dst_dev.rack_id)
                if rack_a is None or rack_b is None:
                    continue  # try next dst device, do NOT mark ports assigned

                length_m = calculate_cable_length_m(
                    rack_a, rack_b, src_dev, dst_dev, tray_height_m, slack_factor
                )

                if rule.max_distance_m and length_m > rule.max_distance_m:
                    continue  # Too far, try next dst device

                try:
                    cable = match_cable(src_port.port_type, src_port.speed_gbps, length_m,
                                        custom_lengths=custom_lengths,
                                        cable_preference=rule.cable_preference)
                except ValueError:
                    continue  # Cable match failed, try next dst device

                conn = _make_connection(
                    src_dev, src_port, dst_dev, dst_port, cable, rule.name,
                )
                if conn is not None:
                    connections.append(conn)
                    # Each port = one physical cable connector → consume both
                    _mark_assigned(src_dev, src_port)
                    _mark_assigned(dst_dev, dst_port)
                    connected = True
                    break
                # Invalid pair (e.g. leaf↔leaf) — continue trying other dsts

            if connected:
                # Advance round-robin index so next src port tries the next dst device first
                rr_idx = (rr_idx + 1) % n_dst

    return connections


def get_unassigned_summary(devices: list[Device]) -> dict:
    """Return a summary of unassigned ports by device."""
    summary = {}
    for dev in devices:
        unassigned = dev.unassigned_ports()
        if unassigned:
            by_type = defaultdict(int)
            for p in unassigned:
                by_type[p.port_type.value] += 1
            summary[dev.name] = dict(by_type)
    return summary
