"""Check port mapping for GPU->RDMA connections."""
import pandas as pd
df = pd.read_excel("output/mapping_final.xlsx", sheet_name="端口映射表")

# GPU-01 -> RDMA connections
gpu01 = df[df["源设备"] == "GPU-Server-01"]
print("GPU-Server-01 connections:")
print(gpu01[["源端口", "目标设备", "目标端口", "线缆类型", "标准长度(m)"]].to_string())
print()

# Check: any duplicate switch ports?
rdma_conns = df[df["备注"] == "GPU → RDMA Switch (Compute Fabric)"]
dup_dst = rdma_conns.groupby(["目标设备", "目标端口"]).size().reset_index(name="count")
multi = dup_dst[dup_dst["count"] > 1]
if len(multi) > 0:
    print(f"WARNING: {len(multi)} switch ports have multiple connections:")
    print(multi.head(10).to_string())
else:
    print("All switch ports have exactly 1 connection (1:1 mapping)")

print()
print(f"Total GPU->RDMA connections: {len(rdma_conns)}")
print(f"Unique switch ports used: {len(dup_dst)}")

# Also check device summary
df2 = pd.read_excel("output/mapping_final.xlsx", sheet_name="设备连接统计")
print()
print("Device summary:")
print(df2.to_string())
