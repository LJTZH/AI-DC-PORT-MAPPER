# AI 数据中心端口映射表生成器

自动生成 AI 数据中心端口映射表的 Python 工具。根据机柜布局、设备清单和连接规则，
计算线缆长度并自动匹配线缆类型（DAC / AOC / 光纤 / 铜缆），
支持 Spine-Leaf 拓扑中 Leaf↔Spine 的正确配对。

## 功能

- **参数化机柜布局**：指定行列数、间距、走线架参数，自动生成机柜坐标和编号
- **设备清单解析**：支持 GPU 服务器、后端/前端 Leaf/Spine 交换机、带内/带外管理交换机
- **紧凑端口格式**：`QSFP56:200:uplink:8, SFP28:25:uplink:2` 一条字符串定义全部端口
- **距离计算**：走线架高度 + 曼哈顿距离 + `tray_offset`（同排直连 / 跨排走通道）
- **线缆匹配**：QSFP112(800G) ~ RJ45(1G)，自动按距离选 DAC/AOC/光纤，含 Breakout 检查
- **连接规则**：一对一、多对一（汇聚）、Mesh（Spine-Leaf），支持 Leaf↔Spine 隔离
- **三语 Excel 输出**：中文 / 日本語 / English，含端口映射、线缆按长度 BOM、光模块清单、设备统计

## 快速开始

### 安装

```bash
pip install -r requirements.txt
```

### 生成示例数据

```bash
python scripts/generate_samples.py
```

### 运行

```bash
# 使用参数化 YAML 机柜布局（推荐）
python -m src.main \
    --racks config/sample_rack_layout.yaml \
    --devices config/sample_devices.xlsx \
    --rules config/sample_connection_rules.yaml \
    --tray-height 2.6 \
    --output output/port_mapping.xlsx
```

### 运行测试

```bash
python -m pytest tests/ -v
```

## 输入文件格式

### 1. 机柜布局（YAML 参数化格式，推荐）

```yaml
layout:
  num_rows: 2
  racks_per_row: 8
  col_spacing_m: 0.8       # 同排相邻机柜中心距 (x 方向, m)
  row_spacing_m: 3.0       # 排间距 (y 方向, m)
  rack_width_mm: 600
  rack_depth_mm: 1200
  rack_height_u: 42
  tray_height_m: 2.6       # 走线架距地面高度
  tray_side: low           # 走线架位置: low / high
  tray_offset_m: 0.6       # 机柜中心到通道走线架的水平距离
  origin_x_m: 0.0
  origin_y_m: 0.0
```

机柜坐标自动计算：`x = origin_x + (col-1) × col_spacing`，
`y = origin_y + (row-1) × row_spacing`。
机柜编号自动生成为 `RowXX-RackXX`。

也兼容 Excel 显式格式（逐行填写 rack_id, x_m, y_m 等列）。

### 2. 设备清单（Excel）

| name | device_type | rack_id | ru_start | ru_height | ports |
|------|-------------|---------|----------|-----------|-------|
| GPU-Server-01 | gpu_server | Row01-Rack01 | 20 | 4 | `QSFP56:200:uplink:8, SFP28:25:uplink:2, RJ45:1:uplink:1` |

**支持的设备类型：**

| 类型 | 说明 |
|------|------|
| `gpu_server` | GPU 服务器 |
| `backend_leaf` | 后端 Leaf 交换机（面向 GPU 服务器） |
| `backend_spine` | 后端 Spine 交换机（互联 Leaf） |
| `frontend_leaf` | 前端 Leaf 交换机（存储/业务网络） |
| `frontend_spine` | 前端 Spine 交换机 |
| `mgmt_switch` | 带外管理交换机（BMC/IPMI） |
| `inband_switch` | 带内管理交换机 |
| `backend_switch` | 后端通用（同时匹配 leaf 和 spine） |
| `frontend_switch` | 前端通用 |
| `rdma_switch` / `eth_switch` | 旧名称，兼容 |

**端口紧凑格式：**

一条字符串定义所有端口，逗号分隔，多种格式可混用：

- **计数式**：`QSFP56:200:uplink:8` → 生成 Port1~Port8，类型 QSFP56/200G/uplink
- **独立式**：`Mgmt:RJ45:1:uplink:bond0` → 命名端口 Mgmt
- **混合**：`QSFP56:200:uplink:8, SFP28:25:uplink:2, Mgmt:RJ45:1:uplink`

多个计数式条目共享计数器，端口命名自动递增（Port1~8, Port9~10, Port11）。

也兼容 JSON 格式：`'[{"port_name":"Port1","port_type":"QSFP56",...}]'`

### 3. 连接规则（YAML）

```yaml
rules:
  - name: "GPU → Backend Leaf (Compute Fabric)"
    src_device_type: gpu_server
    src_port_type: QSFP56
    src_direction: uplink
    dst_device_type: backend_leaf
    dst_port_type: QSFP56
    dst_direction: downlink
    pattern: one_to_one
    priority: 0
    cable_preference: fiber     # auto / dac / aoc / fiber
    allow_same_rack: true
    max_distance_m: null        # 可选：最大线缆距离限制

  - name: "Backend Leaf → Backend Spine"
    src_device_type: backend_leaf
    src_port_type: QSFP56
    src_direction: uplink
    dst_device_type: backend_spine
    dst_port_type: QSFP56
    dst_direction: downlink
    pattern: mesh               # 每台 Leaf 均匀分布于各 Spine
    allow_same_rack: false
    priority: 3
    cable_preference: fiber
```

**连接模式：**

| 模式 | 说明 |
|------|------|
| `one_to_one` | 一对一配对 |
| `many_to_one` | N 个源端口汇聚到 1 个目标端口（`ports_per_group` 控制 N） |
| `mesh` | Spine-Leaf 全网状互联，Leaf 上行端口均匀分配至 Spine |

**Leaf/Spine 隔离：** 后端和前端网络均禁止 Leaf↔Leaf、Spine↔Spine 连接，即使误配泛型规则也不会出现。

## 布线模型

采用 **上走线（Overhead Cable Tray）** 模型：

```
同排（同一 row）：
  设备A ──垂直上行──→ 排内直连（不走通道走线架）──→ ──垂直下行──→ 设备B
  水平 = 曼哈顿距离（无 tray_offset）

跨排（不同 row）：
  设备A ──垂直上行──→ 偏移 tray_offset 进入通道走线架 ──→ 沿走线架 ──→ 偏移 tray_offset 离开 ──→ ──垂直下行──→ 设备B
  水平 = 曼哈顿距离 + tray_offset × 2

总长度 = (水平距离 + 垂直距离A + 垂直距离B) / 1000 × 余量系数(1.15)
```

- 曼哈顿距离 = `|x₁ - x₂| + |y₁ - y₂|`（模拟正交走线架）
- 垂直距离 = `走线架高度 - 设备U位中点高度`（取 ≥0）

## 线缆匹配规则

| 端口 | 速度 | ≤3m / ≤5m | 中距离 | >30m |
|------|------|-----------|--------|------|
| QSFP112 | 800G | QSFP112 DAC (≤3m) | QSFP112 AOC (3–30m) | QSFP112 SR8 光纤 |
| OSFP | 800G | OSFP 800G DAC (≤3m) | OSFP 800G AOC (3–30m) | OSFP 800G SR8 光纤 |
| QSFP56-DD | 400G | QSFP56-DD DAC (≤5m) | QSFP56-DD AOC (5–30m) | QSFP56-DD SR8 光纤 |
| QSFP56 | 200G | QSFP56 DAC (≤5m) | QSFP56 AOC (5–30m) | QSFP56 SR4 光纤 |
| QSFP28 | 100G | QSFP28 DAC (≤5m) | QSFP28 AOC (5–30m) | QSFP28 SR4 光纤 |
| SFP28 | 25G | SFP28 DAC (≤5m) | SFP28 AOC (5–30m) | SFP28 SR 光纤 |
| RJ45 | 1G/10G | Cat6/Cat6a 跳线 (≤100m) | — | — |

线缆长度自动向上取整到标准长度（可自定义 `config/sample_cable_lengths.yaml`）。

## 输出文件

每次运行生成 **三种语言** 的 Excel 文件（`_zh` / `_ja` / `_en` 后缀），
每种语言包含 4 个 Sheet：

| Sheet | 内容 |
|-------|------|
| 端口映射表 | 源/目标设备、机柜、U 位、端口、线缆类型、标准长度、计算长度、光模块需求 |
| 线缆汇总 BOM | 每种线缆按长度细分（如 QSFP56 SR4: 5m×20 + 10m×60），含小计和总计 |
| 光模块汇总 | 光模块类型、数量、对应连接数 |
| 设备连接统计 | 每台设备的总连接数、上/下行连接数、使用的端口类型 |

## 项目结构

```
ai-dc-port-mapper/
├── README.md
├── requirements.txt
├── config/
│   ├── sample_rack_layout.yaml          # 参数化机柜布局
│   ├── sample_devices.xlsx              # 设备清单示例
│   ├── sample_connection_rules.yaml     # 连接规则
│   └── sample_cable_lengths.yaml        # 自定义线缆标准长度（可选）
├── src/
│   ├── models.py                        # 数据模型（Device, Port, Rack, Connection 等）
│   ├── parser.py                        # 输入解析（Excel / YAML + 参数化布局）
│   ├── distance.py                      # 线缆长度计算
│   ├── cable_matcher.py                 # 线缆类型匹配（含 QSFP112/OSFP 800G）
│   ├── mapper.py                        # 端口映射核心（one_to_one / many_to_one / mesh）
│   ├── writer.py                        # 多语言 Excel 输出
│   ├── i18n.py                          # 中/日/英三语字符串
│   └── main.py                          # CLI 入口
├── tests/
│   ├── test_models.py（隐式）
│   ├── test_parser.py                   # 解析器测试（含参数化布局 + 向后兼容）
│   ├── test_distance.py                 # 距离计算测试
│   ├── test_cable_matcher.py            # 线缆匹配测试（含 QSFP112/OSFP + Breakout）
│   └── test_integration.py             # 集成测试（含 Leaf/Spine 隔离 + Mesh 均匀分布）
└── scripts/
    └── generate_samples.py              # 生成示例配置文件
```
