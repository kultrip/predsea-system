import argparse
from pathlib import Path


DEFAULT_TITLE = "PredSea Oceanographic Conditions"
DEFAULT_RESOLUTION_LABEL = "Copernicus Med ~4.2 km ocean forecast grid"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a captain-facing ocean conditions map with real coastline context."
    )
    parser.add_argument("--waves", required=True, help="Path to Copernicus wave NetCDF file.")
    parser.add_argument("--currents", help="Optional path to Copernicus surface-current NetCDF file.")
    parser.add_argument("--output", required=True, help="Output PNG path.")
    parser.add_argument("--time", help="Model time to plot, e.g. 12:00 or 2026-05-15T12:00.")
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--resolution-label", default=DEFAULT_RESOLUTION_LABEL)
    parser.add_argument("--coastline-resolution", default="10m", choices=["10m", "50m", "110m"])
    parser.add_argument("--extent", nargs=4, type=float, metavar=("LON_MIN", "LON_MAX", "LAT_MIN", "LAT_MAX"))
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--arrow-density", default="normal", choices=["sparse", "normal", "dense"])
    parser.add_argument("--arrow-color", default="black", help="Current-vector arrow color.")
    parser.add_argument("--no-currents", action="store_true", help="Do not draw current vectors.")
    return parser.parse_args(argv)


def select_time_index(dataset, requested_time=None):
    if "time" not in dataset:
        return 0
    labels = [str(value) for value in dataset["time"].dt.strftime("%H:%M").values]
    iso_labels = [str(value) for value in dataset["time"].values]
    if requested_time in labels:
        return labels.index(requested_time)
    if requested_time:
        for index, label in enumerate(iso_labels):
            if requested_time in label:
                return index
    return 0


def infer_extent(wave, padding_degrees=0.08):
    lons = wave["longitude"].values
    lats = wave["latitude"].values
    return [
        float(lons.min()) - padding_degrees,
        float(lons.max()) + padding_degrees,
        float(lats.min()) - padding_degrees,
        float(lats.max()) + padding_degrees,
    ]


def quiver_steps(lon_count, lat_count, density="normal"):
    targets = {
        "sparse": (10, 7),
        "normal": (14, 10),
        "dense": (22, 15),
    }
    target_lon, target_lat = targets[density]
    return max(1, lon_count // target_lon), max(1, lat_count // target_lat)


def dependency_error(error):
    message = (
        "Publication map generation requires matplotlib and cartopy. "
        "Install the map extras with: python -m pip install matplotlib cartopy"
    )
    runtime_error = RuntimeError(message)
    runtime_error.__cause__ = error
    return runtime_error


def generate_ocean_conditions_map(
    waves_path,
    output_path,
    currents_path=None,
    requested_time=None,
    title=DEFAULT_TITLE,
    resolution_label=DEFAULT_RESOLUTION_LABEL,
    coastline_resolution="10m",
    extent=None,
    dpi=220,
    arrow_density="normal",
    arrow_color="white",
    draw_currents=True,
):
    try:
        import numpy as np
        import xarray as xr
        import matplotlib.pyplot as plt
        import cartopy
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature

        # Configure Cartopy to use local offline shapefiles to prevent dynamic downloads
        cartopy.config['data_dir'] = str(Path(__file__).resolve().parent.parent / "assets" / "cartopy_data")
    except ImportError as error:
        raise dependency_error(error)

    waves_path = Path(waves_path)
    output_path = Path(output_path)
    with xr.open_dataset(waves_path) as waves:
        time_index = select_time_index(waves, requested_time)
        wave = waves["VHM0"].isel(time=time_index)
        time_label = str(waves["time"].dt.strftime("%Y-%m-%d %H:%M UTC").values[time_index])
        map_extent = extent or infer_extent(wave)

        projection = ccrs.PlateCarree()
        figure = plt.figure(figsize=(14, 11), dpi=dpi)
        axis = plt.axes(projection=projection)
        axis.set_extent(map_extent, crs=projection)
        axis.set_facecolor("#06202d")

        land = cfeature.NaturalEarthFeature(
            "physical",
            "land",
            coastline_resolution,
            edgecolor="#111111",
            facecolor="#c7ccd1",
        )
        axis.add_feature(land, zorder=4, linewidth=0.8)
        axis.coastlines(resolution=coastline_resolution, color="#111111", linewidth=0.8, zorder=5)

        levels = np.linspace(0.0, 2.5, 26)
        field = axis.contourf(
            wave["longitude"].values,
            wave["latitude"].values,
            wave.values,
            levels=levels,
            cmap="turbo",
            extend="max",
            transform=projection,
            zorder=1,
        )

        if currents_path and draw_currents:
            with xr.open_dataset(currents_path) as currents:
                current_index = min(time_index, currents.sizes.get("time", 1) - 1)
                current_u = currents["uo"].isel(time=current_index)
                current_v = currents["vo"].isel(time=current_index)
                lon_values = current_u["longitude"].values
                lat_values = current_u["latitude"].values
                lon_step, lat_step = quiver_steps(len(lon_values), len(lat_values), arrow_density)
                axis.quiver(
                    lon_values[::lon_step],
                    lat_values[::lat_step],
                    current_u.values[::lat_step, ::lon_step],
                    current_v.values[::lat_step, ::lon_step],
                    color=arrow_color,
                    scale=6.8,
                    width=0.002,
                    headwidth=3.2,
                    transform=projection,
                    zorder=6,
                )

        gridlines = axis.gridlines(
            draw_labels=True,
            linewidth=0.4,
            color="#5e7480",
            alpha=0.5,
            linestyle="--",
        )
        gridlines.top_labels = False
        gridlines.right_labels = False
        gridlines.xlabel_style = {"size": 10}
        gridlines.ylabel_style = {"size": 10}

        colorbar = figure.colorbar(field, ax=axis, shrink=0.82, pad=0.03)
        colorbar.set_label("Significant wave height (m)", fontsize=12)

        axis.set_title(f"{title}\n{time_label} | {resolution_label}", fontsize=17, pad=18)
        axis.text(
            0.01,
            0.02,
            "Forecast field: significant wave height. Arrows: surface currents.",
            transform=axis.transAxes,
            fontsize=10,
            color="#f7fbff",
            bbox={"facecolor": "#06202d", "alpha": 0.78, "edgecolor": "none", "pad": 6},
            zorder=10,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(output_path, bbox_inches="tight", facecolor="white")
        plt.close(figure)
    return output_path


def main():
    args = parse_args()
    output = generate_ocean_conditions_map(
        args.waves,
        args.output,
        currents_path=args.currents,
        requested_time=args.time,
        title=args.title,
        resolution_label=args.resolution_label,
        coastline_resolution=args.coastline_resolution,
        extent=args.extent,
        dpi=args.dpi,
        arrow_density=args.arrow_density,
        arrow_color=args.arrow_color,
        draw_currents=not args.no_currents,
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
