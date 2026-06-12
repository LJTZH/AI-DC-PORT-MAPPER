"""Debug port direction in connections."""
import sys
sys.path.insert(0, ".")
from src.parser import parse_rack_layout, parse_devices, parse_connection_rules
from src.mapper import generate_mapping

racks = parse_rack_layout("config/sample_rack_layout.xlsx")
devices = parse_devices("config/sample_devices.xlsx")
rules = parse_connection_rules("config/sample_connection_rules.yaml")

# Check GPU server port directions
for dev in devices:
    if "GPU" in dev.name:
        for p in dev.ports[:2]:
            print(f"{dev.name} {p.port_name}: direction={p.direction}, type={p.port_type}")

connections = generate_mapping(racks, devices, rules, 2.6, 1.15)

# Check first few GPU connections
gpu_conns = [c for c in connections if "GPU" in c.src_device][:3]
for c in gpu_conns:
    print(f"\nConnection:")
    print(f"  {c.src_device}:{c.src_port} (direction={c.src_port_direction!r})")
    print(f"  → {c.dst_device}:{c.dst_port} (direction={c.dst_port_direction!r})")
