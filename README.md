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

`rsplot` does not ship site-specific data paths. Configure local satellite,
station, boundary, and font paths with a TOML file:

```bash
mkdir -p ~/.config/rsplot
cp config.example.toml ~/.config/rsplot/config.toml
```

Then edit `~/.config/rsplot/config.toml`:

```toml
[paths]
geojson_dir = "/path/to/geojson"
font_dir = "/path/to/fonts"
# hcho_cmap_file = "/path/to/256x3_rgb_table.txt"

[paths.data_dirs]
no2 = "/path/to/NO2"
o3 = "/path/to/O3"
o3pr = "/path/to/O3PR"
hcho = "/path/to/HCHO"
guokong = "/path/to/guokong_combine"

# Optional satellite basemap key. Leave commented unless you have a real key.
# [tianditu]
# api_key = "your-real-key"
```

You can also point to a different config file:

```bash
export RSPLOT_CONFIG="/path/to/rsplot.toml"
```

Environment variables override TOML values:

```bash
export TIANDITU_API_KEY="your-key"
export RSPLOT_GEOJSON_DIR="/path/to/geojson"
export RSPLOT_FONT_DIR="/path/to/fonts"
export RSPLOT_DATA_DIR_NO2="/path/to/NO2"
export RSPLOT_DATA_DIR_O3="/path/to/O3"
export RSPLOT_DATA_DIR_O3PR="/path/to/O3PR"
export RSPLOT_DATA_DIR_HCHO="/path/to/HCHO"
export RSPLOT_DATA_DIR_GUOKONG="/path/to/guokong_combine"
export RSPLOT_HCHO_CMAP_FILE="/path/to/256x3_rgb_table.txt"
```

Command-line directory options, such as `--data-dir`, take precedence for the
command being run. If no TianDiTu API key is configured, use `--basemap none`
to avoid requesting satellite tiles.

## Usage

The examples below assume data paths are configured and readable.

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
