"""CLI command definitions for rsplot."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

import typer
from rich.console import Console

console = Console()
app = typer.Typer(
    name="rsplot",
    help="CLI tool for Remote sensing raster plotting.",
    no_args_is_help=True,
    add_completion=False,
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
        ...,
        help="区域名称；支持逗号分隔多个省市县街道，如 '中山市/东区街道,中山市/南区街道'，无需配置",
    ),
    date_arg: str = typer.Argument(
        ...,
        metavar="DATE",
        help=(
            "TROPOMI: YYYYMMDD 按文件名日期合并当天轨道；"
            "GEMS: YYYYMMDD 日均或 YYYYMMDDHHMM 精确扫描。"
            "两者均支持 YYYYMMDD-YYYYMMDD 闭区间，"
            "或结束日期 YYYYMMDD 配合 --days N，逐日等权平均。"
        ),
    ),
    # --- Required options ---
    product: str = typer.Option(
        ...,
        "--product",
        help="产品类型: no2 / o3 / o3pr / hcho",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        help="输出 PNG 路径，同时写同名 JSON",
    ),
    # --- Data selection and processing ---
    sensor: str = typer.Option(
        "tropomi", "--sensor", help="卫星来源: tropomi / gems"
    ),
    processing: str | None = typer.Option(
        None,
        "--processing",
        help="TROPOMI 处理流: nrti（筛选并去重）；省略则读取目录内匹配文件",
    ),
    days: int | None = typer.Option(
        None,
        "--days",
        help=(
            "以 DATE 为结束日期、向前共 N 天（含当天），按日等权平均；"
            "不能与日期区间同时使用。省略时 YYYYMMDD 仅处理当天。"
        ),
    ),
    res: float | None = typer.Option(
        None,
        "--res",
        help="目标网格间距 (度)；GEMS 默认 0.05°，直接重映射原始像元",
    ),
    qa: float | None = typer.Option(
        None, "--qa", help="TROPOMI QA 阈值 (0-1)，默认取配置；GEMS 不适用"
    ),
    cf: float = typer.Option(
        0.5,
        "--cf",
        min=0.0,
        max=1.0,
        help="最大云量比例 (0-1)，保留 CF <= 该值的卫星像元",
    ),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    # --- Plotting ---
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        help="底图控制: satellite / none (覆盖级别默认)",
    ),
    vmin: float | None = typer.Option(None, "--vmin", help="Colorbar 最小值"),
    vmax: float | None = typer.Option(None, "--vmax", help="Colorbar 最大值"),
    cmap: str | None = typer.Option(None, "--cmap", help="Colormap 名称"),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制卫星遥感栅格图。

    TROPOMI 单日合并轨道后网格化并填补小空洞；窗口模式先逐日网格化，
    再对每个网格的有效天等权平均（缺测不计为 0，至少一天有效即保留，
    全无有效天则留空），不填补空洞。因此 --days 1 与省略 --days 不等价。

    示例:
        rsplot raster 北京    20260108 --dpi 300 --output yrd.png  # 单日
        rsplot raster 安徽    20260131 --product hcho --days 30  # 月均（推荐 HCHO）
        rsplot raster 长三角  20260101-20260131 --product no2  # 显式区间
    """
    from rsplot.commands.raster import run_raster

    run_raster(
        region=region,
        date_arg=date_arg,
        product=product,
        sensor=sensor,
        processing=processing,
        days=days,
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
        cf=cf,
        console=console,
    )


@app.command()
def radius(
    station_id: str = typer.Argument(
        ...,
        help="中心国控站点 ID，如 1379A",
    ),
    date_arg: str = typer.Argument(
        ...,
        help="GEMS: YYYYMMDDHHMM 精确扫描，YYYYMMDD 日均；单日 YYYYMMDD 走单日路径；带 --days 或写成 YYYYMMDD-YYYYMMDD "
        "时切换为窗口均值（HCHO 单日覆盖率低，月均更可读）",
    ),
    # --- Required options ---
    product: str = typer.Option(
        ...,
        "--product",
        help="产品类型: no2 / o3 / o3pr / hcho",
    ),
    km: float = typer.Option(
        ...,
        "--km",
        help="从站点向上下左右各延伸的公里数，正方形边长为该值的两倍",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        help="输出 PNG 路径，同时写同名 JSON",
    ),
    # --- Data selection and processing ---
    sensor: str = typer.Option(
        "tropomi", "--sensor", help="卫星来源: tropomi / gems"
    ),
    processing: str | None = typer.Option(
        None,
        "--processing",
        help="TROPOMI 处理流: nrti；省略时沿用原有目录与读取行为",
    ),
    days: int | None = typer.Option(
        None,
        "--days",
        help="时间窗口天数；不指定且 DATE 为单日时走单日路径。"
        "推荐值: 30 (月均，HCHO 首选) / 7 (周均) / 显式区间用 YYYYMMDD-YYYYMMDD",
    ),
    station_var: str | None = typer.Option(
        None,
        "--station-var",
        help="站点变量，如 NO2 / O3 / PM2.5；省略只标位置",
    ),
    station_datetime: str | None = typer.Option(
        None,
        "--station-datetime",
        help="站点小时 YYYYMMDDHH；日均/窗口叠加变量时必填，GEMS 扫描默认匹配最近整点",
    ),
    res: float | None = typer.Option(
        None,
        "--res",
        help="目标网格间距 (度)；GEMS 默认 0.05°，直接重映射原始像元",
    ),
    qa: float | None = typer.Option(
        None, "--qa", help="TROPOMI QA 阈值 (0-1)，默认取配置；GEMS 不适用"
    ),
    cf: float = typer.Option(
        0.5,
        "--cf",
        min=0.0,
        max=1.0,
        help="最大云量比例 (0-1)，保留 CF <= 该值的卫星像元",
    ),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    # --- Plotting ---
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    basemap: str | None = typer.Option(
        "none",
        "--basemap",
        help="底图控制: satellite / none (覆盖级别默认)",
    ),
    vmin: float | None = typer.Option(None, "--vmin", help="Colorbar 最小值"),
    vmax: float | None = typer.Option(None, "--vmax", help="Colorbar 最大值"),
    cmap: str | None = typer.Option(None, "--cmap", help="Colormap 名称"),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制站点居中、上下左右各延伸指定公里数的正方形卫星图，可叠加指定小时的站点变量。"""
    from rsplot.commands.radius import run_radius

    run_radius(
        station_id=station_id,
        date_arg=date_arg,
        km=km,
        station_var=station_var,
        station_datetime=station_datetime,
        sensor=sensor,
        processing=processing,
        product=product,
        days=days,
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
        cf=cf,
        console=console,
    )


@app.command()
def meteo(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、南京、YRD、合肥/蜀山"
    ),
    datetime_str: str = typer.Argument(
        ...,
        help="YYYYMMDDHH；不接受仅日期，不自动选择最新小时",
    ),
    # --- Required options ---
    output: str = typer.Option(
        ...,
        "--output",
        help="输出 PNG 路径；同时写同名 JSON",
    ),
    # --- Data selection and processing ---
    temp_level: str | None = typer.Option(
        None,
        "--temp-level",
        help="温度层次: 2m / 1000 / 925 / 850 / 700 / 500",
    ),
    wind_level: str | None = typer.Option(
        None,
        "--wind-level",
        help="风场层次: 10m / 100m / 1000 / 925 / 850 / 700 / 500",
    ),
    station_var: str | None = typer.Option(
        None,
        "--station-var",
        help="叠加国控站点变量；必须同时指定 --wind-level",
    ),
    # --- Plotting ---
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        help="底图控制: satellite / none",
    ),
    vmin: float | None = typer.Option(
        None,
        "--vmin",
        help="温度色标最小值 (°C)，默认区域 2% 分位",
    ),
    vmax: float | None = typer.Option(
        None,
        "--vmax",
        help="温度色标最大值 (°C)，默认区域 98% 分位",
    ),
    cmap: str | None = typer.Option(
        None,
        "--cmap",
        help="温度色标；默认 RdYlBu_r",
    ),
    wind_stride: int | None = typer.Option(
        None,
        "--wind-stride",
        help="风矢量抽稀步长；默认根据区域和网格大小自动选择",
    ),
    wind_scale: float | None = typer.Option(
        None,
        "--wind-scale",
        help="Matplotlib quiver scale；数值越大箭头越短",
    ),
    wind_width: float = typer.Option(
        0.004,
        "--wind-width",
        help="风箭头宽度；默认 0.004",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="自定义标题",
    ),
) -> None:
    """绘制温度、黑色风箭头及可选国控站点图层。

    DATETIME 为 YYYYMMDDHH：

        rsplot meteo 南京 2026051115 --temp-level 2m
        rsplot meteo 南京 2026051115 --wind-level 850
        rsplot meteo 南京 2026051115 --temp-level 850 --wind-level 850
        rsplot meteo 南京 2026051115 --station-var O3 --wind-level 850
    """
    from rsplot.commands.meteo import run_meteo

    run_meteo(
        region=region,
        datetime_str=datetime_str,
        temp_level=temp_level,
        wind_level=wind_level,
        station_var=station_var,
        output=output,
        dpi=dpi,
        basemap=basemap,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        wind_stride=wind_stride,
        wind_scale=wind_scale,
        wind_width=wind_width,
        title=title,
        console=console,
    )


@app.command()
def station(
    region: str = typer.Argument(
        ..., help="区域名称，如 中国、安徽、合肥、YRD、合肥/蜀山"
    ),
    datetime_str: str = typer.Argument(
        ...,
        help="YYYYMMDDHH（必须指定小时，不自动选择最新小时）",
    ),
    # --- Required options ---
    var: str = typer.Option(
        ...,
        "--var",
        help="变量名: AQI, PM2.5, PM2.5_24h, PM10, PM10_24h, SO2, SO2_24h, NO2, NO2_24h, O3, O3_24h, O3_8h, O3_8h_24h, CO, CO_24h",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        help="输出文件路径",
    ),
    # --- Data selection and processing ---
    # --- Plotting ---
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        help="底图控制: satellite / none",
    ),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制国控站点污染物散点图。

    时间必须为 YYYYMMDDHH；不接受仅日期或自动选择最新小时。

    示例:
        rsplot station 安徽 2026041415
        rsplot station 中国 2026041415 --var PM2.5_24h
        rsplot station YRD 2026041415 --var NO2 --output logs/yrd_no2.png
    """
    from rsplot.commands.station import run_station

    run_station(
        region=region,
        datetime_str=datetime_str,
        var=var,
        output=output,
        dpi=dpi,
        basemap=basemap,
        title=title,
        console=console,
    )


@app.command()
def trend(
    target: str = typer.Argument(
        ...,
        help="国控站点 ID；配合 --region 时为区域名称",
    ),
    date_arg: str = typer.Argument(
        ...,
        help="结束日期 YYYYMMDD，或显式范围 YYYYMMDD-YYYYMMDD",
    ),
    # --- Required options ---
    var: str = typer.Option(
        ...,
        "--var",
        help="变量名: AQI, PM2.5, PM10, NO2, O3, SO2, CO, O3_8h, O3_8h_24h",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        help="PNG 输出文件路径",
    ),
    # --- Data selection and processing ---
    days: int | None = typer.Option(
        None,
        "--days",
        help="以单日 DATE 为结束日的天数；单日 DATE 必填，日期区间时不可用",
    ),
    region: bool = typer.Option(
        False,
        "--region",
        help="将 TARGET 作为区域名称，绘制区域站点趋势",
    ),
    threshold: float | None = typer.Option(
        None,
        "--threshold",
        min=0.0,
        help="覆盖变量默认超标阈值",
    ),
    # --- Plotting ---
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    view: str = typer.Option(
        "lines",
        "--view",
        help="区域视图: lines（灰色站点线+均值）/ mean（仅均值）",
    ),
    focus_station: Annotated[
        list[str] | None,
        typer.Option(
            "--focus-station",
            help="区域图中重点突出站点 ID；可重复指定",
        ),
    ] = None,
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """绘制单站点或区域国控站点小时观测趋势图。

    示例:
        rsplot trend 3347A 20260520 --days 7 --var O3
        rsplot trend 安徽 20260520 --days 7 --var O3 --region
        rsplot trend 安徽 20260520 --region --view mean --focus-station 3347A
    """
    from rsplot.commands.station_trend import run_trend

    run_trend(
        target=target,
        date_arg=date_arg,
        days=days,
        var=var,
        region_mode=region,
        view=view,
        focus_station_ids=focus_station,
        threshold=threshold,
        output=output,
        dpi=dpi,
        title=title,
        console=console,
    )


@app.command()
def overlay(
    region: str = typer.Argument(
        ...,
        help="区域名称；支持逗号分隔多个省市县街道，如 '中山市/东区街道,中山市/南区街道'，无需配置",
    ),
    date_arg: str = typer.Argument(
        ...,
        metavar="DATE",
        help=(
            "卫星时间，与 raster 相同。TROPOMI: YYYYMMDD 按文件名日期合并"
            "当天轨道；GEMS: YYYYMMDD 日均或 YYYYMMDDHHMM 精确扫描。"
            "两者均支持 YYYYMMDD-YYYYMMDD 闭区间，或结束日期 YYYYMMDD 配合"
            " --days N，逐日等权平均。"
        ),
    ),
    # --- Required options ---
    product: str = typer.Option(
        ...,
        "--product",
        help="卫星产品类型: no2 / o3 / o3pr / hcho",
    ),
    station_var: str = typer.Option(
        ...,
        "--station-var",
        help="站点变量名，如 NO2 / O3 / O3_8h_24h；与卫星产品无默认配对",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        help="输出 PNG 路径，同时写同名 JSON",
    ),
    # --- Data selection and processing ---
    sensor: str = typer.Option(
        "tropomi", "--sensor", help="卫星来源: tropomi / gems"
    ),
    processing: str | None = typer.Option(
        None,
        "--processing",
        help="TROPOMI 处理流: nrti；省略时沿用原有目录与读取行为",
    ),
    days: int | None = typer.Option(
        None,
        "--days",
        help=(
            "以 DATE 为结束日期、向前共 N 天（含当天），按日等权平均；"
            "不能与日期区间同时使用。"
        ),
    ),
    station_datetime: str | None = typer.Option(
        None,
        "--station-datetime",
        help=(
            "站点观测小时 YYYYMMDDHH。TROPOMI、GEMS 日均及窗口"
            "均值必须指定；GEMS 精确扫描默认匹配最近整点，也可显式覆盖。"
            "不会自动选择最新小时。"
        ),
    ),
    res: float | None = typer.Option(
        None,
        "--res",
        help="目标网格间距 (度)；GEMS 默认 0.05°，直接重映射原始像元",
    ),
    qa: float | None = typer.Option(
        None, "--qa", help="TROPOMI QA 阈值 (0-1)，默认取配置；GEMS 不适用"
    ),
    cf: float = typer.Option(
        0.5,
        "--cf",
        min=0.0,
        max=1.0,
        help="最大云量比例 (0-1)，保留 CF <= 该值的卫星像元",
    ),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    # --- Plotting ---
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        help="底图控制: satellite / none (覆盖级别默认)",
    ),
    vmin: float | None = typer.Option(
        None, "--vmin", help="卫星 colorbar 最小值"
    ),
    vmax: float | None = typer.Option(
        None, "--vmax", help="卫星 colorbar 最大值"
    ),
    cmap: str | None = typer.Option(None, "--cmap", help="卫星 colormap 名称"),
    title: str | None = typer.Option(None, "--title", help="自定义标题"),
) -> None:
    """叠加绘制卫星栅格+国控站点图。

    两种数据同时输出到一张 PNG 和一个合并的 JSON sidecar。
    DATE 只决定卫星时间；站点始终是一个整点，从不做时间平均。

    示例:
        rsplot overlay YRD  20260208 --product no2 --station-datetime 2026020813
        rsplot overlay 安徽 20260414 --product o3 --days 7 \\
            --station-datetime 2026041414
        rsplot overlay 合肥 202604141200 --sensor gems --product no2
    """
    from rsplot.commands.overlay import run_overlay

    run_overlay(
        region=region,
        date_arg=date_arg,
        days=days,
        station_datetime=station_datetime,
        product=product,
        sensor=sensor,
        processing=processing,
        station_var=station_var,
        output=output,
        dpi=dpi,
        res=res,
        basemap=basemap,
        vmin=vmin,
        vmax=vmax,
        cmap=cmap,
        smooth=smooth,
        qa=qa,
        cf=cf,
        title=title,
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
    # --- Required options ---
    output: str = typer.Option(
        ...,
        "--output",
        help="输出文件路径",
    ),
    # --- Data selection and processing ---
    processing: str | None = typer.Option(
        None,
        "--processing",
        help="TROPOMI 处理流: nrti，同时用于 NO2 与 HCHO",
    ),
    days: int | None = typer.Option(
        None,
        "--days",
        help="以单日 DATE 为结束日的窗口天数；单日 DATE 必填，日期区间时不可用",
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
    res: float | None = typer.Option(None, "--res", help="网格分辨率 (度)"),
    qa: float | None = typer.Option(
        0.5,
        "--qa",
        help="QA 阈值 (0-1)，同时应用于 NO2 和 HCHO（OFFL L2 swath 推荐 ≥0.5）",
    ),
    cf: float = typer.Option(
        0.5,
        "--cf",
        min=0.0,
        max=1.0,
        help="最大云量比例，同时应用于 NO2 和 HCHO；保留 CF <= 该值的像元",
    ),
    smooth: float | None = typer.Option(
        None, "--smooth", help="高斯平滑 sigma"
    ),
    # --- Plotting ---
    dpi: int | None = typer.Option(300, "--dpi", help="输出 DPI"),
    basemap: str | None = typer.Option(
        None,
        "--basemap",
        help="底图控制: satellite / none",
    ),
    display_max: float = typer.Option(
        6.0,
        "--display-max",
        help="FNR 图例显示上限，必须大于 --nox-threshold",
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
        processing=processing,
        region=region,
        date_arg=date_arg,
        days=days,
        n_min=n_min,
        no2_min=no2_min,
        voc_threshold=voc_threshold,
        nox_threshold=nox_threshold,
        display_max=display_max,
        output=output,
        dpi=dpi,
        res=res,
        basemap=basemap,
        smooth=smooth,
        qa=qa,
        cf=cf,
        title=title,
        console=console,
    )
