"""CLI entry point for AI DC Port Mapper.

Usage:
    python -m src.main \
        --racks config/sample_rack_layout.xlsx \
        --devices config/sample_devices.xlsx \
        --rules config/sample_connection_rules.yaml \
        --tray-height 2.6 \
        --output output/port_mapping.xlsx

    python -m src.main --batch config/batch.yaml
"""

import sys
import io
import contextlib
from pathlib import Path

import click


@contextlib.contextmanager
def _fix_windows_encoding():
    """Context manager to wrap stdout/stderr for UTF-8 on Windows terminals.

    Only patches when the encoding is not already UTF-8, and restores
    the original streams on exit so global state is not permanently altered.
    """
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    try:
        if sys.stdout.encoding != "utf-8":
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
        if sys.stderr.encoding != "utf-8":
            sys.stderr = io.TextIOWrapper(
                sys.stderr.buffer, encoding="utf-8", errors="replace"
            )
        yield
    finally:
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr

from .parser import (
    parse_rack_layout,
    parse_devices,
    parse_connection_rules,
    load_batch_config,
)
from .mapper import generate_mapping, get_unassigned_summary
from .writer import write_output
from .cable_matcher import load_cable_lengths_from_file
from .i18n import get_lang

# Languages to generate output for (zh = CLI, all three for Excel)
_OUTPUT_LANGS = {"zh": "_zh", "ja": "_ja", "en": "_en"}


@click.command()
@click.option("--racks", "-r", type=click.Path(exists=True),
              help="Rack layout file (.xlsx or .yaml)")
@click.option("--devices", "-d", type=click.Path(exists=True),
              help="Device inventory file (.xlsx or .yaml)")
@click.option("--rules", "-c", type=click.Path(exists=True),
              help="Connection rules file (.yaml)")
@click.option("--tray-height", "-t", type=float, default=2.6,
              help="Cable tray height from floor in meters (default: 2.6)")
@click.option("--slack-factor", "-s", type=float, default=1.15,
              help="Cable slack factor (default: 1.15 = 15%%)")
@click.option("--cable-lengths", "-l", type=click.Path(exists=True),
              help="Custom cable standard lengths config file (.yaml)")
@click.option("--output", "-o", type=click.Path(), default="output/port_mapping.xlsx",
              help="Output Excel file path")
@click.option("--batch", "-b", type=click.Path(exists=True),
              help="Batch config file (.yaml) — overrides individual options")
def main(racks, devices, rules, tray_height, slack_factor, cable_lengths, output, batch):
    """AI Data Center Port Mapping Generator.

    Generates a complete port mapping table with cable types and lengths
    for GPU clusters, RDMA fabrics, and management networks.
    """
    with _fix_windows_encoding():
        _run_main(racks, devices, rules, tray_height, slack_factor,
                  cable_lengths, output, batch)


def _run_main(racks, devices, rules, tray_height, slack_factor, cable_lengths, output, batch):
    """Internal implementation — called inside the encoding fix wrapper."""
    # Load batch config if provided
    if batch:
        config = load_batch_config(batch)
        racks = config.get("rack_layout", racks)
        devices = config.get("devices", devices)
        rules = config.get("connection_rules", rules)
        tray_height = config.get("tray_height_m", tray_height)
        slack_factor = config.get("slack_factor", slack_factor)
        output = config.get("output", output)
        if config.get("cable_lengths") and not cable_lengths:
            cable_lengths = config.get("cable_lengths")

    # Load custom cable lengths if specified
    custom_lengths = None
    if cable_lengths:
        click.echo(f"  自定义线缆长度: {cable_lengths}")
        custom_lengths = load_cable_lengths_from_file(cable_lengths)

    # Validate inputs
    if not racks:
        click.echo("错误: 必须指定 --racks 文件或使用 --batch 配置", err=True)
        sys.exit(1)
    if not devices:
        click.echo("错误: 必须指定 --devices 文件或使用 --batch 配置", err=True)
        sys.exit(1)
    if not rules:
        click.echo("错误: 必须指定 --rules 文件或使用 --batch 配置", err=True)
        sys.exit(1)

    click.echo("=" * 60)
    click.echo("  AI 数据中心端口映射表生成器")
    click.echo("=" * 60)
    click.echo()

    # Step 1: Parse inputs
    click.echo(f"[1/4] 解析输入文件...")
    click.echo(f"  机柜布局: {racks}")
    rack_list = parse_rack_layout(racks)
    click.echo(f"  → 加载 {len(rack_list)} 个机柜")

    click.echo(f"  设备清单: {devices}")
    device_list = parse_devices(devices)
    total_ports = sum(len(d.ports) for d in device_list)
    click.echo(f"  → 加载 {len(device_list)} 台设备, {total_ports} 个端口")

    click.echo(f"  连接规则: {rules}")
    rule_list = parse_connection_rules(rules)
    click.echo(f"  → 加载 {len(rule_list)} 条连接规则")

    # Step 2: Generate mappings
    click.echo()
    click.echo(f"[2/4] 生成端口映射 (走线架高度={tray_height}m, 余量={slack_factor})...")
    try:
        connections = generate_mapping(
            rack_list, device_list, rule_list, tray_height, slack_factor,
            custom_lengths=custom_lengths,
        )
    except ValueError as e:
        click.echo(f"\n映射错误:\n{e}", err=True)
        sys.exit(1)

    click.echo(f"  → 生成 {len(connections)} 条连接")

    # Step 3: Check unassigned ports
    click.echo()
    click.echo(f"[3/4] 检查未分配端口...")
    unassigned = get_unassigned_summary(device_list)
    if unassigned:
        click.echo(f"  警告: 以下设备有未分配的端口:")
        for dev_name, ports in unassigned.items():
            port_desc = ", ".join(f"{k}: {v}" for k, v in ports.items())
            click.echo(f"    - {dev_name}: {port_desc}")
    else:
        click.echo(f"  → 所有端口已分配完成")

    # Step 4: Write output
    click.echo()
    click.echo(f"[4/4] 写入输出文件...")
    base_path = Path(output)
    base_path.parent.mkdir(parents=True, exist_ok=True)
    stem = base_path.stem
    suffix = base_path.suffix

    out_files = []
    for lang, tag in _OUTPUT_LANGS.items():
        lang_path = base_path.parent / f"{stem}{tag}{suffix}"
        result = write_output(str(lang_path), connections, lang=lang)
        out_files.append(result)
        click.echo(f"  → [{lang}] {result}")
    click.echo()

    # Summary
    cable_types = {}
    fiber_count = sum(1 for c in connections if c.needs_transceiver)
    dac_count = sum(1 for c in connections if "DAC" in c.cable_type)
    aoc_count = sum(1 for c in connections if "AOC" in c.cable_type)
    copper_count = sum(1 for c in connections if "Cat" in c.cable_type)

    click.echo("=" * 60)
    click.echo("  生成摘要")
    click.echo("=" * 60)
    click.echo(f"  总连接数:     {len(connections)}")
    click.echo(f"  DAC 连接:     {dac_count}")
    click.echo(f"  AOC 连接:     {aoc_count}")
    click.echo(f"  光纤连接:     {fiber_count}")
    click.echo(f"  铜缆连接:     {copper_count}")
    click.echo(f"  输出文件:")
    for f in out_files:
        click.echo(f"    {f}")
    click.echo("=" * 60)


if __name__ == "__main__":
    main()
