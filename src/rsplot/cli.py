"""CLI command definitions for rsplot."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

import typer
from rich.console import Console

console = Console()
app = typer.Typer(
    name="rsplot",
    help="CLI tool for Remote sensing raster plotting.",
    no_args_is_help=True,
)


def _get_version() -> str:
    try:
        return version("rsplot")
    except PackageNotFoundError:
        return "unknown"


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"rsplot {_get_version()}")
        raise typer.Exit()


@app.callback()
def _callback(
    show_version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    "CLI tool for Remote sensing raster plotting."


@app.command()
def raster(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    date_arg: str = typer.Argument(
        ...,
        help="单日 YYYYMMDD 走单日路径；带 --days 或写成 YYYYMMDD-YYYYMMDD "
        "时切换为窗口均值（HCHO 单日覆盖率低，月均更可读）",
    ),
    # --- optional overrides ---
    product: str = typer.Option(
        "o3",
        "--product",
        "-p",
        help="产品类型: no2 / o3 / o3pr / hcho",
    ),
    days: int | None = typer.Option(
        None,
        "--days",
        help="时间窗口天数；不指定且 DATE 为单日时走单日路径。"
        "推荐值: 30 (月均，HCHO 首选) / 7 (周均) / 显式区间用 YYYYMMDD-YYYYMMDD",
    ),
    n_min: int | None = typer.Option(
        None,
        "--n-min",
        help=(
            "窗口模式下每像元最少有效天数。默认: NO2/O3/O3PR="
            "max(3, 天数//2), HCHO=max(3, ceil(天数*0.25))"
        ),
    ),
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    data_dir: str | None = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径，不指定则弹窗显示。",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    res: float | None = typer.Option(None, "--res", help="网格分辨率 (度)"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        "-b",
        help="底图控制: satellite / none (覆盖级别默认)",
    ),
    vmin: float | None = typer.Option(None, "--vmin", help="Colorbar 最小值"),
    vmax: float | None = typer.Option(None, "--vmax", help="Colorbar 最大值"),
    cmap: str | None = typer.Option(None, "--cmap", help="Colormap 名称"),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
    qa: float | None = typer.Option(0.5, "--qa", help="QA 阈值 (0-1)"),
) -> None:
    """绘制卫星遥感栅格图。

    示例:
        rsplot raster 北京    20260108 --dpi 300 --output yrd.png        # 单日
        rsplot raster 安徽    20260131 -p hcho --days 30                 # 月均（推荐 HCHO）
        rsplot raster 长三角  20260101-20260131 -p no2                   # 显式区间
    """
    from rsplot.commands.raster import run_raster

    run_raster(
        region=region,
        date_arg=date_arg,
        product=product,
        days=days,
        n_min=n_min,
        level=level,
        data_dir=data_dir,
        output=output,
        dpi=dpi,
        res=res,
        basemap=basemap,
        vmin=vmin,
        vmax=vmax,
        cmap=cmap,
        smooth=smooth,
        title=title,
        qa=qa,
        console=console,
    )


@app.command()
def forecast(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    datetime_str: str = typer.Argument(
        ..., help="起报时次 YYYYMMDDHH，或 YYYYMMDD 自动取当天最新小时"
    ),
    var: str = typer.Option(
        "o3",
        "--var",
        "-v",
        help="预报变量: PM2.5 / PM10 / SO2 / NO2 / CO / O3",
    ),
    lead: int = typer.Option(
        24,
        "--lead",
        help="预报时效: 6 / 12 / 24 / 48 / 72 小时",
    ),
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    data_dir: str | None = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="预报数据目录 (覆盖配置中的 forecast 路径)",
    ),
    station_overlay: bool = typer.Option(
        False,
        "--station-overlay",
        help="叠加同有效时次的国控站点散点",
    ),
    station_var: str | None = typer.Option(
        None,
        "--station-var",
        help="站点变量名；默认按预报变量自动匹配 PM2.5/PM10/SO2/NO2/CO/O3",
    ),
    station_data_dir: str | None = typer.Option(
        None,
        "--station-data-dir",
        help="国控站点数据目录 (覆盖配置中的 guokong 路径)",
    ),
    station_datetime: str | None = typer.Option(
        None,
        "--station-datetime",
        help="站点时次 YYYYMMDDHH 或 YYYYMMDD；默认使用预报有效时次",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        "-b",
        help="底图控制: satellite / none (覆盖级别默认)",
    ),
    vmin: float | None = typer.Option(None, "--vmin", help="Colorbar 最小值"),
    vmax: float | None = typer.Option(None, "--vmax", help="Colorbar 最大值"),
    cmap: str | None = typer.Option(None, "--cmap", help="Colormap 名称"),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制空气质量预报栅格图。

    示例:
        rsplot forecast 安徽 2026063000 --lead 24 --var O3
        rsplot forecast 合肥 20260630 --lead 72 --var PM2.5
        rsplot forecast 合肥 2026041409 --lead 6 --var O3 --station-overlay
    """
    from rsplot.commands.forecast import run_forecast

    run_forecast(
        region=region,
        datetime_str=datetime_str,
        var=var,
        lead=lead,
        level=level,
        data_dir=data_dir,
        station_overlay=station_overlay,
        station_var=station_var,
        station_data_dir=station_data_dir,
        station_datetime=station_datetime,
        output=output,
        dpi=dpi,
        basemap=basemap,
        vmin=vmin,
        vmax=vmax,
        cmap=cmap,
        smooth=smooth,
        title=title,
        console=console,
    )


@app.command()
def station(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    datetime_str: str = typer.Argument(
        ..., help="YYYYMMDDHH (精确小时) 或 YYYYMMDD (自动取最新小时)"
    ),
    # --- optional overrides ---
    var: str = typer.Option(
        "AQI",
        "--var",
        "-v",
        help="变量名: AQI, PM2.5, PM10, NO2, O3, SO2, CO, O3_8h, *_24h",
    ),
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    data_dir: str | None = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        "-b",
        help="底图控制: satellite / none",
    ),
    wind_level: str | None = typer.Option(
        None,
        "--wind-level",
        help="叠加 ERA5 风场层次: 10m / 100m / 1000 / 925 / 850 / 700 / 500",
    ),
    wind_data_dir: str | None = typer.Option(
        None,
        "--wind-data-dir",
        help="ERA5 数据目录 (覆盖配置中的 era5 路径)",
    ),
    station_timezone: str = typer.Option(
        "Asia/Shanghai",
        "--station-timezone",
        help="国控文件名时次的 IANA 时区，用于匹配 ERA5 UTC",
    ),
    wind_stride: int | None = typer.Option(
        None,
        "--wind-stride",
        help="风矢量抽稀步长；默认根据区域和网格大小自动选择",
    ),
    wind_scale: float | None = typer.Option(
        None,
        "--wind-scale",
        help="Matplotlib quiver scale；不指定时自动缩放",
    ),
    wind_width: float = typer.Option(
        0.004,
        "--wind-width",
        help="风箭头宽度；默认 0.004",
    ),
    wind_cmap: str = typer.Option(
        "viridis", "--wind-cmap", help="风速色标名称"
    ),
    wind_vmin: float | None = typer.Option(
        None, "--wind-vmin", help="风速色标最小值"
    ),
    wind_vmax: float | None = typer.Option(
        None, "--wind-vmax", help="风速色标最大值"
    ),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制国控站点散点图，可选叠加 ERA5 风场。

    示例:
        rsplot station 安徽 20260414        (自动取当天最新小时)
        rsplot station 安徽 2026041415      (精确到15时)
        rsplot station 中国 20260414 --var PM2.5_24h
        rsplot station YRD 2026041415 --var NO2 -o logs/yrd_no2.png
        rsplot station 合肥 2026041415 --var O3 --wind-level 10m
    """
    from rsplot.commands.station import run_station

    run_station(
        region=region,
        datetime_str=datetime_str,
        var=var,
        level=level,
        data_dir=data_dir,
        output=output,
        dpi=dpi,
        basemap=basemap,
        wind_level=wind_level,
        wind_data_dir=wind_data_dir,
        station_timezone=station_timezone,
        wind_stride=wind_stride,
        wind_scale=wind_scale,
        wind_width=wind_width,
        wind_cmap=wind_cmap,
        wind_vmin=wind_vmin,
        wind_vmax=wind_vmax,
        title=title,
        console=console,
    )


@app.command()
def station_trend(
    station_id: str = typer.Argument(..., help="国控站点 ID，如 3347A"),
    date_arg: str = typer.Argument(
        ...,
        help="结束日期 YYYYMMDD，或显式范围 YYYYMMDD-YYYYMMDD",
    ),
    days: int = typer.Option(
        7,
        "--days",
        help="最近天数；仅当 DATE 为单日时生效，默认 7",
    ),
    var: str = typer.Option(
        "O3_8h_24h",
        "--var",
        "-v",
        help="变量名: AQI, PM2.5, PM10, NO2, O3, SO2, CO, O3_8h, O3_8h_24h",
    ),
    data_dir: str | None = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="国控站点数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="PNG 输出文件路径",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制单个国控站点一日或多日的小时观测折线图。

    示例:
        rsplot station-trend 3347A 20260520 --days 1 --var O3
        rsplot station-trend 3347A 20260520 --days 7 --var PM2.5
        rsplot station-trend 3347A 20260501-20260507 --var O3
    """
    from rsplot.commands.station_trend import run_station_trend

    run_station_trend(
        station_id=station_id,
        date_arg=date_arg,
        days=days,
        var=var,
        data_dir=data_dir,
        output=output,
        dpi=dpi,
        title=title,
        console=console,
    )


@app.command()
def overlay(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    datetime_str: str = typer.Argument(
        ...,
        help="YYYYMMDDHH (精确小时) 或 YYYYMMDD (自动取最新小时)；"
        "日期部分用于卫星，小时部分用于站点",
    ),
    # --- satellite product ---
    product: str = typer.Option(
        "o3",
        "--product",
        "-p",
        help="卫星产品类型: no2 / o3 / o3pr / hcho",
    ),
    # --- station variable ---
    var: str | None = typer.Option(
        None,
        "--var",
        "-v",
        help="站点变量名，省略时按 product 自动选同名变量 (NO2 / O3)",
    ),
    # --- overrides ---
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    raster_dir: str | None = typer.Option(
        None,
        "--raster-dir",
        help="卫星数据目录 (覆盖配置默认值)",
    ),
    station_dir: str | None = typer.Option(
        None,
        "--station-dir",
        help="国控站点数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径，不指定则弹窗显示。",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    res: float | None = typer.Option(None, "--res", help="网格分辨率 (度)"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        "-b",
        help="底图控制: satellite / none (覆盖级别默认)",
    ),
    vmin: float | None = typer.Option(
        None, "--vmin", help="卫星 colorbar 最小值"
    ),
    vmax: float | None = typer.Option(
        None, "--vmax", help="卫星 colorbar 最大值"
    ),
    cmap: str | None = typer.Option(None, "--cmap", help="卫星 colormap 名称"),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    qa: float | None = typer.Option(0.5, "--qa", help="QA 阈值 (0-1)"),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """叠加绘制卫星栅格+国控站点图。

    两种数据同时输出到一张 PNG 和一个合并的 JSON sidecar。
    日期部分 (YYYYMMDD) 用于卫星，整串 (YYYYMMDDHH) 用于站点；
    YYYYMMDD 会自动选当天最新小时的站点数据。

    示例:
        rsplot overlay YRD    20260208   -p no2
        rsplot overlay 安徽   2026041415 -p o3  -v O3_8h
        rsplot overlay 中国   20260208   -p no2 -o logs/overlay/china_no2.png
    """
    from rsplot.commands.overlay import run_overlay

    run_overlay(
        region=region,
        datetime_str=datetime_str,
        product=product,
        var=var,
        level=level,
        raster_dir=raster_dir,
        station_dir=station_dir,
        output=output,
        dpi=dpi,
        res=res,
        basemap=basemap,
        vmin=vmin,
        vmax=vmax,
        cmap=cmap,
        smooth=smooth,
        qa=qa,
        title=title,
        console=console,
    )


@app.command()
def recent(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    end_date: str = typer.Argument(
        ..., help="结束日期 YYYYMMDD，最近 N 天统计以该日期为窗口末端"
    ),
    days: int = typer.Option(
        30,
        "--days",
        help="最近天数，如 7 / 30 / 365",
    ),
    source: str = typer.Option(
        "raster",
        "--source",
        help="数据源: raster / station",
    ),
    product: str = typer.Option(
        "o3",
        "--product",
        "-p",
        help="source=raster 时的产品: no2 / o3 / o3pr / hcho",
    ),
    var: str = typer.Option(
        "AQI",
        "--var",
        "-v",
        help="source=station 时的变量名: AQI, PM2.5, PM10, NO2, O3, SO2, CO...",
    ),
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    data_dir: str | None = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出 JSON 路径",
    ),
    res: float | None = typer.Option(None, "--res", help="网格分辨率 (度)"),
    qa: float | None = typer.Option(0.5, "--qa", help="QA 阈值 (0-1)"),
) -> None:
    """输出最近 N 天数据 JSON，用于周/月/年变化对比。

    示例:
        rsplot recent 合肥 20260428 --days 30 -p hcho -o recent.json
        rsplot recent 安徽 20260428 --days 7 --source station --var O3
    """
    from rsplot.commands.recent import run_recent

    run_recent(
        region=region,
        end_date=end_date,
        days=days,
        source=source,
        product=product,
        var=var,
        level=level,
        data_dir=data_dir,
        output=output,
        res=res,
        qa=qa,
        console=console,
    )


@app.command()
def fnr(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    date_arg: str = typer.Argument(
        ...,
        help="单日 (YYYYMMDD，默认向前 --days 天) 或范围 "
        "(YYYYMMDD-YYYYMMDD，闭区间)",
    ),
    # --- window ---
    days: int = typer.Option(
        7,
        "--days",
        help="时间窗口天数（仅当 date_arg 为单日时生效，默认 7）",
    ),
    n_min: int | None = typer.Option(
        None,
        "--n-min",
        help="每像元最少有效天数，默认 max(3, 窗口天数 // 2)",
    ),
    no2_min: float = typer.Option(
        0.5,
        "--no2-min",
        help="最小平均 NO2 柱浓度阈值 (x10^15 molec/cm2)；"
        "低于此值的像元 FNR 不可信，输出为 NaN",
    ),
    voc_threshold: float = typer.Option(
        1.0,
        "--voc-threshold",
        help="VOC-limited 分级阈值：FNR 小于该值判为 VOC-limited",
    ),
    nox_threshold: float = typer.Option(
        2.0,
        "--nox-threshold",
        help="NOx-limited 分级阈值：FNR 大于该值判为 NOx-limited",
    ),
    display_max: float = typer.Option(
        6.0,
        "--display-max",
        help="FNR 图例显示上限，必须大于 --nox-threshold",
    ),
    # --- overrides ---
    level: str | None = typer.Option(
        None,
        "--level",
        "-l",
        help="强制指定级别: country / key_region / province / city / county",
    ),
    raster_dir_no2: str | None = typer.Option(
        None,
        "--no2-dir",
        help="NO2 数据目录 (覆盖配置默认值)",
    ),
    raster_dir_hcho: str | None = typer.Option(
        None,
        "--hcho-dir",
        help="HCHO 数据目录 (覆盖配置默认值)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出文件路径",
    ),
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    res: float | None = typer.Option(None, "--res", help="网格分辨率 (度)"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        "-b",
        help="底图控制: satellite / none",
    ),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    qa: float | None = typer.Option(
        0.5,
        "--qa",
        help="QA 阈值 (0-1)，同时应用于 NO2 和 HCHO（OFFL L2 swath 推荐 ≥0.5）",
    ),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制 FNR (HCHO / NO2) 区域控制 regime 图。

    时间窗口平均后再相除（避免日尺度 HCHO 覆盖率太低）。
    分级依据 Duncan 2010: FNR<1 VOC-limited, 1~2 过渡, >2 NOx-limited.

    示例:
        rsplot fnr 合肥   20260114                 (7日窗口)
        rsplot fnr 安徽   20260131 --days 30      (30日窗口)
        rsplot fnr 长三角 20260101-20260130       (显式范围)
    """
    from rsplot.commands.fnr import run_fnr

    run_fnr(
        region=region,
        date_arg=date_arg,
        days=days,
        n_min=n_min,
        no2_min=no2_min,
        voc_threshold=voc_threshold,
        nox_threshold=nox_threshold,
        display_max=display_max,
        level=level,
        raster_dir_no2=raster_dir_no2,
        raster_dir_hcho=raster_dir_hcho,
        output=output,
        dpi=dpi,
        res=res,
        basemap=basemap,
        smooth=smooth,
        qa=qa,
        title=title,
        console=console,
    )
