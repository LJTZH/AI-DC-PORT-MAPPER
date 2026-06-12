"""Data models for AI DC Port Mapper."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DeviceType(str, Enum):
    """Supported device types.

    Backend network:   GPU interconnect / RDMA fabric (compute plane)
    Frontend network:  Storage, service, and general-purpose LAN
    In-band mgmt:      Management traffic over shared data network
    Out-of-band mgmt:  Dedicated management network (BMC/IPMI access)

    Leaf / Spine distinction:
      Leaf switches face servers (downlink ports toward servers).
      Spine switches interconnect leaf switches (uplink ports toward core).
      The generic BACKEND_SWITCH / FRONTEND_SWITCH match both leaf and spine
      (useful for mesh rules where devices interconnect peer-to-peer).
    """
    GPU_SERVER = "gpu_server"
    # ── Backend network (compute fabric / RDMA) ──
    BACKEND_LEAF = "backend_leaf"          # Backend leaf (faces GPU servers)
    BACKEND_SPINE = "backend_spine"        # Backend spine (interconnects leaves)
    BACKEND_SWITCH = "backend_switch"      # Generic backend (matches both leaf & spine)
    # ── Frontend network (storage / service LAN) ──
    FRONTEND_LEAF = "frontend_leaf"        # Frontend leaf (faces servers)
    FRONTEND_SPINE = "frontend_spine"      # Frontend spine (interconnects leaves)
    FRONTEND_SWITCH = "frontend_switch"    # Generic frontend (matches both)
    # ── Management ──
    INBAND_SWITCH = "inband_switch"        # In-band management (over data network)
    MGMT_SWITCH = "mgmt_switch"            # Out-of-band management (BMC/IPMI)
    # ── Legacy aliases (kept for backward compatibility) ──
    RDMA_SWITCH = "rdma_switch"
    ETH_SWITCH = "eth_switch"


class PortType(str, Enum):
    """Supported port connector types."""
    QSFP112 = "QSFP112"          # 400G (4×112G PAM4)
    QSFP56_DD = "QSFP56-DD"      # 400G (8×50G PAM4)
    QSFP56 = "QSFP56"            # 200G (4×50G PAM4)
    QSFP28 = "QSFP28"            # 100G (4×25G NRZ)
    QSFP_PLUS = "QSFP+"          # 40G
    SFP28 = "SFP28"              # 25G
    SFP_PLUS = "SFP+"            # 10G
    SFP = "SFP"                  # 1G SFP
    RJ45 = "RJ45"                # 1G/10G Copper
    OSFP = "OSFP"                # 400G (8×50G) / 800G (8×112G PAM4)


class PortDirection(str, Enum):
    UPLINK = "uplink"
    DOWNLINK = "downlink"
    ANY = "any"


class ConnectionPattern(str, Enum):
    """Matching patterns for connection rules."""
    ONE_TO_ONE = "one_to_one"       # Port N ↔ Port N, 一一对应
    MANY_TO_ONE = "many_to_one"     # Multiple downlinks → single uplink
    MESH = "mesh"                   # All-to-all (Spine-Leaf)


# ── Cable type definitions ──────────────────────────────────────────────

@dataclass
class CableSpec:
    """Definition of a cable type with distance constraints."""
    name: str                    # e.g. "QSFP56 DAC 1m"
    cable_type: str              # e.g. "DAC", "AOC", "Fiber", "Copper"
    connector_a: str             # e.g. "QSFP56"
    connector_b: str             # same or different for breakout
    speed_gbps: int
    min_length_m: float
    max_length_m: float
    needs_transceiver: bool = False
    transceiver_type: str = ""   # e.g. "QSFP56 SR4" if fiber


@dataclass
class Port:
    """A physical port on a device."""
    port_name: str               # e.g. "eth0", "Port1", "E1/1"
    port_type: PortType
    speed_gbps: int
    direction: PortDirection = PortDirection.ANY
    group: str = ""              # Logical group for bonding/LAG
    assigned: bool = False       # Whether already mapped


@dataclass
class Device:
    """A device (server or switch) in a rack."""
    name: str
    device_type: DeviceType
    rack_id: str                 # Which rack this device is in
    ru_start: int                # Starting rack unit (from bottom)
    ru_height: int               # Height in rack units
    ports: list[Port] = field(default_factory=list)

    @property
    def port_height_mm(self) -> float:
        """Height of the device mid-point from floor (mm)."""
        middle_ru = self.ru_start + self.ru_height / 2.0
        return middle_ru * 44.45  # 1U = 44.45mm

    def unassigned_ports(self) -> list[Port]:
        """Return ports that haven't been mapped yet."""
        return [p for p in self.ports if not p.assigned]

    def ports_by_type(self, port_type: PortType) -> list[Port]:
        """Get unassigned ports of a given type."""
        return [p for p in self.unassigned_ports() if p.port_type == port_type]

    def ports_by_direction(self, direction: PortDirection) -> list[Port]:
        """Get unassigned ports of a given direction."""
        return [p for p in self.unassigned_ports() if p.direction in (direction, PortDirection.ANY)]


@dataclass
class Rack:
    """A rack in the data center."""
    rack_id: str
    name: str = ""
    row: int = 0
    col: int = 0
    x_m: float = 0.0            # Center X coordinate in meters
    y_m: float = 0.0            # Center Y coordinate in meters
    width_mm: int = 600         # Standard 19" rack width
    depth_mm: int = 1200        # Rack depth
    height_u: int = 42          # Total rack height in U
    tray_side: str = "low"      # Cable tray side: "low" (near smaller col #s) or "high"
    tray_offset_m: float = 0.0  # Horizontal distance from rack center to cable tray (m)


@dataclass
class Connection:
    """A completed port-to-port connection."""
    src_device: str
    src_port: str
    src_port_type: str
    dst_device: str
    dst_port: str
    dst_port_type: str
    cable_type: str                 # e.g. "QSFP56 DAC"
    cable_length_m: float           # snapped standard length
    src_rack: str = ""              # rack_id of source device
    src_ru: str = ""                # RU position e.g. "20-24" or "30"
    src_port_direction: str = ""    # uplink / downlink / any
    dst_rack: str = ""              # rack_id of destination device
    dst_ru: str = ""                # RU position
    dst_port_direction: str = ""    # uplink / downlink / any
    calculated_length_m: float = 0.0
    needs_transceiver: bool = False
    transceiver_type: str = ""
    notes: str = ""


@dataclass
class ConnectionRule:
    """Rule defining which device types connect to which."""
    name: str
    src_device_type: DeviceType
    src_port_type: PortType
    dst_device_type: DeviceType
    dst_port_type: PortType
    pattern: ConnectionPattern = ConnectionPattern.ONE_TO_ONE
    src_direction: PortDirection = PortDirection.DOWNLINK
    dst_direction: PortDirection = PortDirection.UPLINK
    ports_per_group: int = 1     # For many_to_one: how many src ports per dst port
    priority: int = 0
    allow_same_rack: bool = True
    max_distance_m: Optional[float] = None  # Optional max cable distance
    cable_preference: str = "auto"  # "auto" | "dac" | "aoc" | "fiber" — force specific cable category
