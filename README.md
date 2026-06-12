# AI 数据中心端口映射表生成器

自动生成 AI 数据中心端口映射表的 Python 工具，根据机柜布局、设备清单和连接规则，计算线缆长度并匹配线缆类型。

## 功能

- **机柜布局解析**：支持 Excel/YAML 格式的机柜坐标和尺寸数据
- **设备清单解析**：支持 GPU 服务器、RDMA 交换机、以太网交换机、管理交换机
- **距离计算**：基于走线架高度+曼哈顿距离，自动计算端口间布线长度
- **线缆匹配**：根据端口类型(QSFP56/SFP28/RJ45等)和距离自动匹配 DAC/AOC/光纤
- **连接规则**：支持一对一、多对一(汇聚)、Mesh(Spine-Leaf)三种拓扑模式
- **Excel 输出**：多 Sheet 输出（端口映射表 + 线缆 BOM + 光模块清单 + 设备统计）

## 快速开始

### 安装

```bash
pip install -r requirements.txt
```

### 运行

```bash
# 使用示例数据
python -m src.main \
    --racks config/sample_rack_layout.xlsx \
    --devices config/sample_devices.xlsx \
    --rules config/sample_connection_rules.yaml \
    --tray-height 2.6 \
    --output output/port_mapping.xlsx

# 使用批量配置文件
python -m src.main --batch config/batch.yaml
```

### 运行测试

```bash
python -m pytest tests/ -v
```

## 输入文件格式

### 1. 机柜布局 (Excel)

| rack_id | row | col | x_m | y_m | width_mm | depth_mm | height_u |
|---------|-----|-----|-----|-----|----------|----------|----------|
| R01     | 1   | 1   | 0.0 | 0.0 | 600      | 1200     | 42       |

- `x_m`, `y_m`：机柜中心点的平面坐标（米）
- `width_mm`, `depth_mm`：机柜尺寸（毫米）
- `height_u`：机柜可用高度（U）
- 同时提供 `row`/`col` 用于按行列筛选

### 2. 设备清单 (Excel)

| name | device_type | rack_id | ru_start | ru_height | ports |
|------|-------------|---------|----------|-----------|-------|
| GPU-Server-01 | gpu_server | R01 | 20 | 4 | `[{"port_name":"Port1","port_type":"QSFP56",...}]` |

`device_type` 可选值：`gpu_server`, `rdma_switch`, `eth_switch`, `mgmt_switch`

`ports` 列支持两种格式：
- **JSON 字符串**：`'[{"port_name":"Port1","port_type":"QSFP56","speed_gbps":200,"direction":"downlink"}]'`
- **紧凑格式**：`"QSFP56:200:downlink:8"` 表示 8 个名为 Port1-8 的 QSFP56 端口

### 3. 连接规则 (YAML)

```yaml
rules:
  - name: "GPU → RDMA Switch"
    src_device_type: gpu_server
    src_port_type: QSFP56
    src_direction: downlink
    dst_device_type: rdma_switch
    dst_port_type: QSFP56
    dst_direction: uplink
    pattern: many_to_one       # one_to_one / many_to_one / mesh
    ports_per_group: 8         # many_to_one: N个源端口汇聚到1个目标端口
    priority: 0                # 数字越小优先级越高
    allow_same_rack: true      # 是否允许同机柜连接
    max_distance_m: null       # 可选：最大线缆距离限制
```

## 布线模型

采用 **上走线（Overhead Cable Tray）** 模型：

```
总长度 = (水平距离 + 垂直距离A + 垂直距离B) × 余量系数

水平距离 = |x₁ - x₂| + |y₁ - y₂|  （曼哈顿距离，模拟正交走线架）
垂直距离 = (走线架高度 - 设备U位中点高度)  × 两端
余量系数 = 1.15（15%冗余，可配置）
```

## 线缆匹配规则

| 端口类型 | ≤5m | 5–30m | >30m |
|---------|-----|-------|------|
| QSFP56 (200G) | QSFP56 DAC | QSFP56 AOC | QSFP56 SR4 + MTP/MPO-12 光纤 |
| QSFP28 (100G) | QSFP28 DAC | QSFP28 AOC | QSFP28 SR4 + MTP/MPO-12 光纤 |
| SFP28 (25G) | SFP28 DAC | SFP28 AOC | SFP28 SR + LC 光纤 |
| SFP+ (10G) | SFP+ DAC | SFP+ AOC | SFP+ SR + LC 光纤 |
| RJ45 (1G/10G) | Cat6a 跳线 | Cat6a 跳线 | Cat6a 跳线 (≤100m) |

距离阈值可在 `cable_matcher.py` 中的 `CABLE_CATALOG` 自定义。

## 输出文件

生成的 Excel 包含 4 个 Sheet：

1. **端口映射表**：源设备、源端口、目标设备、目标端口、线缆类型、线缆长度、光模块需求
2. **线缆汇总 BOM**：按线缆类型汇总的数量和长度
3. **光模块汇总**：所需光模块类型和数量
4. **设备连接统计**：每个设备的连接数和使用端口类型

## 项目结构

```
ai-dc-port-mapper/
├── README.md
├── requirements.txt
├── config/                        # 示例输入文件
│   ├── sample_rack_layout.xlsx
│   ├── sample_devices.xlsx
│   └── sample_connection_rules.yaml
├── src/                           # 源代码
│   ├── models.py                  # 数据模型
│   ├── parser.py                  # 输入解析
│   ├── distance.py                # 距离计算
│   ├── cable_matcher.py           # 线缆匹配
│   ├── mapper.py                  # 端口映射核心
│   ├── writer.py                  # Excel输出
│   └── main.py                    # CLI入口
├── tests/                         # 测试
│   ├── test_distance.py
│   ├── test_cable_matcher.py
│   └── test_integration.py
└── output/                        # 输出目录
```
