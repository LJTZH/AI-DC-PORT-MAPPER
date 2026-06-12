"""Quick check device summary sheet."""
import pandas as pd
df = pd.read_excel("output/mapping_final.xlsx", sheet_name="设备连接统计")
print(df.to_string())
