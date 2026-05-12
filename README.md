# rsplot

`rsplot` is an Agent-oriented command-line tool for plotting remote-sensing and
air-quality data. It is designed to provide a small, stable CLI surface for
[tianpu-agent](https://git.lug.ustc.edu.cn/yaoyhu/tianpu-agent).


## Installation

Run directly with `uvx`:

```bash
uvx rsplot --help
```

Or install it in a project environment:

```bash
uv add rsplot
uv run rsplot --help
```

For local development:

```bash
git clone https://github.com/yaoyhu/rsplot.git
cd rsplot
uv sync
uv run rsplot --help
```

## Configuration

For satellite basemaps, set a TianDiTu API key:

```bash
export TIANDITU_API_KEY="your-key"
```

## Usage

The examples below assume the command is running on a USTC server or in an
environment with equivalent data paths configured.

```bash
# Show available commands and options.
rsplot --help

# Plot a single-day TROPOMI raster.
rsplot raster 合肥 20260115 -p no2 -o ./logs/hcho/raster_city_jiujiang_hcho.png

# Plot a 30-day TROPOMI window mean.
rsplot raster 安徽 20260131 -p hcho --days 30 -o hcho_anhui_202601.png

# Plot a TROPOMI ozone-profile tropospheric column raster.
rsplot raster 安徽 20260227 -p o3pr -o o3pr_anhui_20260227.png

# Plot an explicit TROPOMI date range.
rsplot raster 长三角 20260101-20260131 -p no2 -o no2_yrd_202601.png

# Plot national monitoring station observations.
rsplot station 合肥 2026041415 --var O3 -o station_hefei_o3.png

# Overlay satellite raster data and station observations.
rsplot overlay 合肥 2026041415 -p no2 --var NO2 -o overlay_hefei_no2.png

# Plot an FNR regime map with the default 7-day window.
rsplot fnr 合肥 20260114 -o fnr_hefei.png

# Plot an FNR regime map with an explicit date range.
rsplot fnr 长三角 20260101-20260130 -o fnr_yrd_202601.png

# Override FNR regime thresholds for agent-driven sensitivity tests.
rsplot fnr 合肥 20260114 --voc-threshold 0.8 --nox-threshold 1.8 --display-max 5 -o fnr_hefei_sensitivity.png
```

When `-o/--output` is provided, `rsplot` writes the image to that path and also
writes a JSON sidecar with the same base name.

## License

This project is distributed under the license in `LICENSE`.
