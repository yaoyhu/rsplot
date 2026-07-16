# rsplot

`rsplot` is an Agent-oriented command-line tool for plotting remote-sensing,
reconstructed, and air-quality data. It provides a small, stable CLI surface for
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
era5 = "/path/to/era5"
forecast = "/path/to/forecast"
reconstruct = "/path/to/reconstruct"

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
export RSPLOT_DATA_DIR_ERA5="/path/to/era5"
export RSPLOT_DATA_DIR_FORECAST="/path/to/forecast"
export RSPLOT_DATA_DIR_RECONSTRUCT="/path/to/reconstruct"
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

# Reconstructed-grid input is China standard time; rsplot converts it to the
# matching UTC archive filename. This reads 2026051100.nc.
rsplot reconstruct 安徽 2026051108 --var PM2.5 \
  -o reconstruct_anhui_pm25.png

# Date-only input selects the latest complete hour in that China-time day.
rsplot reconstruct 合肥 20260511 --var O3 --res 0.01 \
  -o reconstruct_hefei_o3.png

# Forecast input is China standard time; rsplot converts it
# to the matching UTC archive initialization hour before reading.
rsplot forecast 安徽 2026063000 --lead 24 --var O3 -o forecast_anhui_o3.png

# Date-only input selects the latest initialization within that China-time day.
rsplot forecast 合肥 20260630 --lead 72 --var PM2.5 -o forecast_hefei_pm25.png

# Overlay station observations on the forecast valid time.
rsplot forecast 合肥 2026041409 --lead 6 --var O3 --station-overlay -o forecast_station_hefei_o3.png

# Plot ERA5 2 m temperature. Input hours are China standard time; rsplot
# converts them to the matching UTC archive day and hour automatically.
rsplot meteo 南京 2026051115 --temp-level 2m -o meteo_nanjing_t2m.png

# Plot black 850 hPa wind arrows; length represents speed and no wind
# colorbar is drawn. The reference arrow gives the speed scale.
rsplot meteo 南京 2026051115 --wind-level 850 -o meteo_nanjing_wind850.png

# Overlay black wind arrows on a temperature background. Only the temperature
# colorbar is drawn.
rsplot meteo 南京 2026051115 --temp-level 850 \
  --wind-level 850 -o meteo_nanjing_t850_wind850.png

# Overlay station observations with black wind arrows.
rsplot meteo 南京 2026051115 --station-var O3 \
  --wind-level 850 -o meteo_nanjing_o3_wind850.png

# Temperature, stations, and wind can be combined. The two colorbars describe
# temperature and station concentration; wind magnitude is encoded by length.
rsplot meteo 南京 2026051115 --temp-level 850 --station-var O3 \
  --wind-level 850 -o meteo_nanjing_t850_o3_wind850.png

# Plot national monitoring station observations.
rsplot station 合肥 2026041415 --var O3 -o station_hefei_o3.png

# Plot one station's hourly observations over the latest seven days.
rsplot trend 3347A 20260520 --days 7 --var O3 -o trend_3347A_o3_7d.png

# A single day and an explicit date range are also supported.
rsplot trend 3347A 20260520 --days 1 --var O3 -o trend_3347A_o3_day.png
rsplot trend 3347A 20260501-20260507 --var PM2.5 -o trend_3347A_pm25.png

# Plot all regional stations as grey lines plus the hourly station mean.
rsplot trend 重庆 20260520 --days 7 --var O3 --region -o trend_chongqing_o3.png

# Plot only the regional mean and highlight one or more explicit stations.
rsplot trend 重庆 20260520 --days 7 --var O3 --region --view mean \
  --focus-station 3347A --threshold 200 -o trend_chongqing_focus.png

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
writes a JSON sidecar with the same base name. Reconstructed-grid JSON records
both the China-time input and matched UTC archive hour, source file, native and
output resolution, regional statistics, administrative summaries, and hotspots.

## License

This project is distributed under the license in `LICENSE`.
