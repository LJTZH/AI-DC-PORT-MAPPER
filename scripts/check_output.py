"""Quick output check script."""
import pandas as pd

df = pd.read_excel("output/mapping_fiber.xlsx", sheet_name="端口映射表")

# GPU->RDMA connections
gpu_rdma = df[df["备注"] == "GPU → RDMA Switch (Compute Fabric)"]
print("GPU->RDMA connections:")
print(f"  Count: {len(gpu_rdma)}")
print(f"  Cable types: {gpu_rdma['线缆类型'].value_counts().to_dict()}")
print(f"  Need transceiver: {gpu_rdma['需要光模块'].value_counts().to_dict()}")
print()
print(gpu_rdma.head(3)[["源设备", "源端口", "目标设备", "线缆类型", "标准长度(m)", "需要光模块", "光模块类型"]].to_string())
print()

# Transceiver sheet
df3 = pd.read_excel("output/mapping_fiber.xlsx", sheet_name="光模块汇总")
print("Transceiver summary:")
print(df3.to_string())
print()

# Also check the non-RDMA connections to confirm they still use auto mode
other = df[df["备注"] != "GPU → RDMA Switch (Compute Fabric)"]
print(f"Other connections ({len(other)} total):")
print(f"  Cable types: {other['线缆类型'].value_counts().to_dict()}")
print(f"  Need transceiver: {other['需要光模块'].value_counts().to_dict()}")
