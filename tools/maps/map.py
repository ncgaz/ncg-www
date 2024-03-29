#! ./tools/maps/venv/bin/python3

# ruff: noqa: E402 (allow imports not at top of file)

import matplotlib

# don't use matplotlib GUI
matplotlib.use("agg")

import matplotlib.pyplot as plt
import argparse
import fiona
import itertools
import json
import shutil
import sys
from math import factorial
from matplotlib.collections import LineCollection
from os import path
from patch import PolygonPatch
from pathlib import Path
from rdflib import Graph, Namespace, URIRef
from rdflib.query import ResultRow
from shapely.geometry import shape, Point, Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from tqdm import tqdm
from typing import Callable, NoReturn, Optional, Union, cast

DPI = 560
LW = 0.2
MAPSIZE = (3.0, 1.05)  # w, h

# USGS data is EPSG:4269, we could reproject to EPSG:32019

NCP = Namespace("http://n2t.net/ark:/39333/ncg/place/")


def bind_prefixes(g: Graph) -> None:
    g.bind("ncp", NCP)
    g.bind("ncv", Namespace("http://n2t.net/ark:/39333/ncg/vocab#"))
    g.bind("nct", Namespace("http://n2t.net/ark:/39333/ncg/type#"))
    g.bind("ncgaz", Namespace("http://n2t.net/ark:/39333/ncg/"))
    g.bind("geojson", Namespace("https://purl.org/geojson/vocab#"))


def info(s: str) -> None:
    print(s, file=sys.stdout)


def warn(s: str) -> None:
    print(f"Warning: {s}", file=sys.stderr)


def err(s: str) -> NoReturn:
    raise Exception(f"Error: {s}")


def load_state(geodb: str) -> MultiPolygon:
    with fiona.open(geodb, layer="GU_StateOrTerritory") as c:
        if c is not None:
            for r in c:
                if r["properties"]["state_name"] == "North Carolina":
                    return MultiPolygon(shape(r["geometry"]))
    return MultiPolygon()


def get_county_uri(g: Graph, name: str) -> URIRef:
    results = g.query(
        f"""
SELECT ?county WHERE {{
  ?county
    dcterms:type nct:county ;
    skos:prefLabel "{name} County" .
}}
"""
    )
    assert len(results) == 1
    return list(results)[0].county  # pyright: ignore


def get_bordering_county_uri(g: Graph, name: str, state: str) -> Optional[URIRef]:
    results = g.query(
        f"""
SELECT ?county WHERE {{
  ?county
    dcterms:type nct:borderingCounty ;
    skos:prefLabel "{name} County ({state})" .
}}
"""
    )
    if len(results) == 1:
        return list(results)[0].county  # pyright: ignore
    else:
        return None


def load_counties(g: Graph, geodbs: list[str]) -> dict[URIRef, MultiPolygon]:
    counties = {}
    for geodb in geodbs:
        with fiona.open(geodb, layer="GU_CountyOrEquivalent") as c:
            for r in tqdm(c, file=sys.stdout):
                state_name = r["properties"]["state_name"]
                county_name = r["properties"]["county_name"]
                if state_name == "North Carolina":
                    county_uri = get_county_uri(g, county_name)
                else:
                    county_uri = get_bordering_county_uri(g, county_name, state_name)
                if county_uri is not None:
                    counties[county_uri] = MultiPolygon(shape(r["geometry"]))
    return counties


def load_places(g: Graph) -> dict[URIRef, tuple[Optional[BaseGeometry], list[URIRef]]]:
    places = {}
    results = g.query(
        """
SELECT ?place ?county ?geojson WHERE {
  ncgaz:dataset rdfs:member ?place .

  OPTIONAL {
    ?place ncv:county ?county .
    { ?county dcterms:type nct:county }
    UNION
    { ?county dcterms:type nct:borderingCounty }
  }

  OPTIONAL { ?place geojson:geometry ?geojson }

  FILTER NOT EXISTS { ?place dcterms:type nct:county }
  FILTER NOT EXISTS { ?place dcterms:type nct:borderingCounty }
}
"""
    )
    for row in tqdm(results, file=sys.stdout):
        row = cast(ResultRow, row)
        if row.place not in places:
            geometry = None
            if row.geojson is not None:
                geojson = json.loads(str(row.geojson))
                if geojson["type"] == "Point":
                    geometry = Point(*geojson["coordinates"])
                elif geojson["type"] == "Polygon":
                    geometry = Polygon(*geojson["coordinates"])

            places[row.place] = (geometry, [])

        if row.county is not None:
            places[row.place][1].append(row.county)

    return places


GEOMETRY_CHECK_EXCEPTIONS = [
    "8vxvvgzjdxm8qbk8mxcbw",  # Cape Lookout Shoals, in the ocean off the coast of Carteret County
]

GEOMETRY_CHECK_PROGRESS_FILE = "data/checked-geometries.json"


def load_checked_places() -> set[str]:
    try:
        with open(GEOMETRY_CHECK_PROGRESS_FILE) as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def dump_checked_places(places: set[str]) -> None:
    with open(GEOMETRY_CHECK_PROGRESS_FILE, "w") as f:
        json.dump(list(places), f)


def find_place_containing_point(
    point: Point, places: dict[URIRef, MultiPolygon]
) -> Optional[URIRef]:
    for uri, mp in places.items():
        if mp.buffer(0.01).contains(point):
            return uri
    return None


def check_geometries(
    places: dict[URIRef, tuple[Optional[BaseGeometry], list[URIRef]]],
    counties: dict[URIRef, MultiPolygon],
    on_problem: Union[Callable[[str], None], Callable[[str], NoReturn]],
) -> None:
    checked_places = load_checked_places()
    try:
        for uri, (geometry, place_counties) in tqdm(places.items(), file=sys.stdout):
            ncgid = uri.removeprefix(NCP)
            if geometry is None:
                pass
            elif ncgid in GEOMETRY_CHECK_EXCEPTIONS:
                pass
            elif ncgid in checked_places:
                pass
            elif isinstance(geometry, Point):
                county_geometries = [
                    counties[c] for c in place_counties if c in counties
                ]
                if not any(
                    (cg.buffer(0.01).contains(geometry) for cg in county_geometries)
                ):
                    county = find_place_containing_point(geometry, counties)
                    if county is None:
                        msg = f"Point for {ncgid} is not in any county"
                    else:
                        cid = county.removeprefix(NCP)
                        msg = f"""Point is in a county, but there is no corresponding triple:
ncp:{ncgid} ncv:county ncp:{cid} ."""
                    on_problem(msg)
            elif isinstance(geometry, Polygon):
                explicit_counties = set(place_counties)
                implicit_counties = {
                    c
                    for c, mp in counties.items()
                    if mp.overlaps(geometry) or mp.within(geometry)
                }
                if not explicit_counties == implicit_counties:
                    msg = f"Polygon for {ncgid} does not correspond to its counties"
                    msg += "\n  linked counties are:"
                    msg += f"\n  {'|'.join(sorted(uri.removeprefix(NCP) for uri in explicit_counties))}"
                    msg += "\n  overlapping counties are:"
                    msg += f"\n  {'|'.join(sorted(uri.removeprefix(NCP) for uri in implicit_counties))}"
                    on_problem(msg)
            else:
                err(f"{ncgid} has an unsupported geometry type")
            checked_places.add(ncgid)
    finally:
        dump_checked_places(checked_places)


def get_borders(
    counties: list[MultiPolygon], show_progress: bool = True
) -> list[list[tuple[float, float]]]:
    mp = MultiPolygon(list(itertools.chain(*[mp.geoms for mp in counties])))
    n = len(mp.geoms)
    borders = []
    for p1, p2 in tqdm(
        itertools.combinations(mp.geoms, 2),
        total=(factorial(n) / factorial(2) / factorial(n - 2)),
        disable=(not show_progress),
        file=sys.stdout,
    ):
        if p1.touches(p2):
            i = p1.intersection(p2)
            if i.geom_type == "MultiLineString":
                for line in i.geoms:
                    x, y = line.xy
                    borders.append(list(zip(x, y)))  # noqa: B905 (python < 3.10)
    return borders


def setup_plot(shape: BaseGeometry, padding: float = 0.1):
    minx, miny, maxx, maxy = shape.bounds  # type: ignore
    w, h = maxx - minx, maxy - miny
    # num=1 and clear=True keep from reallocating a new figure each time
    fig = plt.figure(figsize=MAPSIZE, frameon=False, num=1, clear=True)
    axes = fig.add_axes((0, 0, 1, 1))
    axes.set_xlim(minx - padding * w, maxx + padding * w)
    axes.set_ylim(miny - padding * h, maxy + padding * h)
    axes.set_aspect("equal")
    axes.axis("off")
    return axes


def make_county_maps(
    counties: dict[URIRef, MultiPolygon],
    borders: list[list[tuple[float, float]]],
    state: MultiPolygon,
    directory: str,
) -> None:
    axes = setup_plot(state)
    axes.add_patch(PolygonPatch(state, fc="none", ec="#959595", lw=LW))
    axes.add_collection(LineCollection(borders, colors="#959595", lw=LW))

    for uri, mp in tqdm(counties.items(), file=sys.stdout):
        filename = f"{directory}/{uri.removeprefix(NCP)}.png"
        if not path.exists(filename):
            patch = PolygonPatch(mp, fc="#fefb00", ec="none", zorder=0)
            axes.add_patch(patch)
            plt.savefig(filename, dpi=DPI, transparent=True)
            patch.remove()

    plt.clf()
    plt.close()


def make_multicounty_map(
    geometry: Optional[BaseGeometry],
    multicounty: BaseGeometry,
    borders: list[list[tuple[float, float]]],
    state: MultiPolygon,
    filename: str,
) -> None:
    axes = setup_plot(state)
    axes.add_patch(PolygonPatch(multicounty, fc="#fefb00", ec="none"))
    axes.add_patch(PolygonPatch(state, fc="none", ec="#959595", lw=LW))
    axes.add_collection(LineCollection(borders, colors="#959595", lw=LW))
    if geometry is not None and isinstance(geometry, Point):
        axes.plot(geometry.x, geometry.y, marker="o", markersize=1.5, color="k")
    plt.savefig(filename, dpi=DPI, transparent=True)
    plt.clf()
    plt.close()


def make_single_county_map(
    geometry: BaseGeometry,
    county: BaseGeometry,
    borders: list[list[tuple[float, float]]],
    state: MultiPolygon,
    filename: str,
) -> None:
    axes = setup_plot(state)
    axes.add_patch(PolygonPatch(county, fc="#fefb00", ec="none"))
    axes.add_patch(PolygonPatch(state, fc="none", ec="#959595", lw=LW))
    axes.add_collection(LineCollection(borders, colors="#959595", lw=LW))
    if isinstance(geometry, Point):
        axes.plot(geometry.x, geometry.y, marker="o", markersize=1.5, color="k")
    plt.savefig(filename, dpi=DPI, transparent=True)
    plt.clf()
    plt.close()


def make_shape_and_lines(
    geometry: Optional[BaseGeometry],
    counties: list[URIRef],
    county_geometries: list[MultiPolygon],
    borders: list[list[tuple[float, float]]],
    state_geometry: MultiPolygon,
    directory: str,
    filename: str,
) -> tuple[Optional[MultiPolygon], Optional[LineCollection]]:
    shape, lines = None, None

    if len(county_geometries) == 0:
        if geometry is not None:
            shape = state_geometry

    elif len(county_geometries) == 1:
        county = county_geometries[0]

        shutil.copyfile(f"{directory}/{counties[0].removeprefix(NCP)}.png", filename)

        if geometry is not None:
            shape = county

    elif len(county_geometries) > 1:
        union = unary_union(county_geometries)
        if union is not None:
            make_multicounty_map(geometry, union, borders, state_geometry, filename)

            shape = union
            lines = LineCollection(
                get_borders(county_geometries, show_progress=False),
                colors="#959595",
                lw=LW,
            )

    return shape, lines


def make_place_maps(
    places: dict[URIRef, tuple[Optional[BaseGeometry], list[URIRef]]],
    counties: dict[URIRef, MultiPolygon],
    borders: list[list[tuple[float, float]]],
    state: MultiPolygon,
    directory: str,
) -> None:
    for uri, (geometry, place_counties) in tqdm(places.items(), file=sys.stdout):
        ncgid = uri.removeprefix(NCP)
        filename_c = f"{directory}/{ncgid}-counties.png"
        filename_p = f"{directory}/{ncgid}.png"

        if not path.exists(filename_c):
            county_geometries = [counties[c] for c in place_counties if c in counties]
            if not len(county_geometries) == len(place_counties):
                err(f"Not all counties of {ncgid} have geometries")

            shape, lines = make_shape_and_lines(
                geometry,
                place_counties,
                county_geometries,
                borders,
                state,
                directory,
                filename_c,
            )

            if shape is not None:
                axes = setup_plot(shape, padding=0.050)
                axes.add_patch(PolygonPatch(shape, fc="#fefb00", ec="#959595", lw=LW))
                if lines is not None:
                    axes.add_collection(lines)
                if geometry is not None:
                    if isinstance(geometry, Point):
                        axes.plot(
                            geometry.x,
                            geometry.y,
                            marker="o",
                            markersize=1.5,
                            color="k",
                        )
                    # TODO plot polygon geometries
                plt.savefig(filename_p, dpi=DPI, transparent=True)
                plt.clf()
                plt.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", help="map images output directory")
    parser.add_argument("dataset", help="NCG dataset in Turtle format")
    parser.add_argument("geodbs", nargs="+", help="GDB files with geometry data")
    parser.add_argument(
        "--geometry-check",
        help="check that geometries make sense",
        choices=["none", "warn", "error"],
        default="warn",
    )
    args = parser.parse_args()

    Path(args.directory).mkdir(exist_ok=True)

    g = Graph()
    bind_prefixes(g)
    g.parse(args.dataset)
    info("Loading state geometry ...")
    state = load_state(args.geodbs[0])  # assume NC is the first
    info("Loading county geometries ...")
    counties = load_counties(g, args.geodbs)
    info("Loading place data ...")
    places = load_places(g)
    if not args.geometry_check == "none":
        info("Checking place geometries")
        check_geometries(
            places, counties, on_problem=warn if args.geometry_check == "warn" else err
        )
    info("Calculating borders ...")
    borders = get_borders(list(counties.values()))
    info("Generating county maps ...")
    make_county_maps(counties, borders, state, args.directory)
    info("Generating place maps ...")
    make_place_maps(places, counties, borders, state, args.directory)


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
