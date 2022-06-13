import argparse
import fiona
import itertools
import json
import matplotlib.pyplot as plt
import shutil
import sys
from math import factorial
from matplotlib.collections import LineCollection
from os import path
from patch import PolygonPatch
from pathlib import Path
from rdflib import Graph, Namespace, URIRef
from shapely.geometry import shape, Point, Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from tqdm import tqdm
from typing import Optional

DPI = 560
LW = 0.2
MAPSIZE = (3.0, 1.05)  # w, h

NCP = Namespace("http://n2t.net/ark:/39333/ncg/place/")
NCV = Namespace("http://n2t.net/ark:/39333/ncg/vocab#")
NCT = Namespace("http://n2t.net/ark:/39333/ncg/type#")
GEOJSON = Namespace("https://purl.org/geojson/vocab#")

# USGS data is EPSG:4269, we could reproject to EPSG:32019


def info(s: str):
    print(s, file=sys.stderr)


def warn(s: str):
    print(f"Warning: {s}", file=sys.stderr)


def err(s: str):
    raise Exception(f"Error: {s}")


def load_state(geodb: str) -> MultiPolygon:
    with fiona.open(geodb, layer="GU_StateOrTerritory") as c:
        for r in c:
            if r["properties"]["State_Name"] == "North Carolina":
                return MultiPolygon(shape(r["geometry"]))
    return MultiPolygon()


def get_county_uri(g: Graph, name: str) -> URIRef:
    results = g.query(
        f"""
SELECT ?county WHERE {{
  ?county
    a nct:County ;
    skos:prefLabel "{name} County" .
}}
"""
    )
    assert len(results) == 1
    return list(results)[0].county


def load_counties(g: Graph, geodb: str) -> dict[URIRef, MultiPolygon]:
    counties = {}
    with fiona.open(geodb, layer="GU_CountyOrEquivalent") as c:
        for r in tqdm(c):
            if r["properties"]["State_Name"] == "North Carolina":
                counties[
                    get_county_uri(g, r["properties"]["County_Name"])
                ] = MultiPolygon(shape(r["geometry"]))
    return counties


def load_places(g: Graph) -> dict[URIRef, tuple[Optional[BaseGeometry], list[URIRef]]]:
    places = {}
    results = g.query(
        """
SELECT ?place ?county ?geojson WHERE {
  ?place ncv:county ?county .
  ?county a nct:County .
  OPTIONAL { ?place geojson:geometry ?geojson }
}
"""
    )
    for row in tqdm(results):
        if row.place not in places:
            geometry = None
            if row.geojson is not None:
                geojson = json.loads(str(row.geojson))
                if geojson["type"] == "Point":
                    geometry = Point(*geojson["coordinates"])
                elif geojson["type"] == "Polygon":
                    geometry = Polygon(*geojson["coordinates"])

            places[row.place] = (geometry, [])

        places[row.place][1].append(row.county)

    return places


def check_geometries(
    places: dict[URIRef, tuple[Optional[BaseGeometry], list[URIRef]]],
    counties: dict[URIRef, MultiPolygon],
) -> None:
    for uri, (geometry, place_counties) in tqdm(places.items()):
        ncgid = uri.removeprefix(NCP)
        if geometry is None:
            pass
        elif isinstance(geometry, Point):
            county_geometries = [counties[c] for c in place_counties if c in counties]
            if not any(
                (cg.buffer(0.01).contains(geometry) for cg in county_geometries)
            ):
                warn(f"Point for {ncgid} is not in any of its counties")
        elif isinstance(geometry, Polygon):
            explicit_counties = set(place_counties)
            implicit_counties = {
                c for c, mp in counties.items() if mp.overlaps(geometry)
            }
            if not explicit_counties == implicit_counties:
                msg = f"Polygon for {ncgid} does not correspond to its counties"
                msg += "\n  overlapping counties are:"
                msg += f"\n  {'|'.join(uri.removeprefix(NCP) for uri in implicit_counties)}"
                err(msg)
        else:
            err(f"{ncgid} has an unsupported geometry type")


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
    ):
        if p1.touches(p2):
            i = p1.intersection(p2)
            if i.geom_type == "MultiLineString":
                for line in i.geoms:
                    x, y = line.xy
                    borders.append(list(zip(x, y)))
    return borders


def setup_plot(shape: BaseGeometry, padding: float = 0.0):
    minx, miny, maxx, maxy = shape.bounds  # type: ignore
    w, h = maxx - minx, maxy - miny
    fig = plt.figure(figsize=MAPSIZE, frameon=False)
    axes = fig.add_axes([0, 0, 1, 1])
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

    for uri, mp in tqdm(counties.items()):
        filename = f"{directory}/{uri.removeprefix(NCP)}.png"
        if not path.exists(filename):
            patch = PolygonPatch(mp, fc="#fefb00", ec="none", zorder=0)
            axes.add_patch(patch)
            plt.savefig(filename, dpi=DPI, transparent=True)
            patch.remove()

    plt.close()


def make_multicounty_map(
    multicounty: BaseGeometry,
    borders: list[list[tuple[float, float]]],
    state: MultiPolygon,
    filename: str,
) -> None:
    axes = setup_plot(state)
    axes.add_patch(PolygonPatch(multicounty, fc="#fefb00", ec="none"))
    axes.add_patch(PolygonPatch(state, fc="none", ec="#959595", lw=LW))
    axes.add_collection(LineCollection(borders, colors="#959595", lw=LW))
    plt.savefig(filename, dpi=DPI, transparent=True)
    plt.close()


def make_place_maps(
    places: dict[URIRef, tuple[Optional[BaseGeometry], list[URIRef]]],
    counties: dict[URIRef, MultiPolygon],
    borders: list[list[tuple[float, float]]],
    state: MultiPolygon,
    directory: str,
) -> None:

    for uri, (geometry, place_counties) in tqdm(places.items()):

        ncgid = uri.removeprefix(NCP)
        filename_c = f"{directory}/{ncgid}-counties.png"
        filename_p = f"{directory}/{ncgid}.png"

        if not path.exists(filename_c):

            shape, lines = None, None

            county_geometries = [counties[c] for c in place_counties if c in counties]
            if not len(county_geometries) == len(place_counties):
                err(f"Not all counties of {ncgid} have geometries")

            if len(place_counties) > 1:
                union = unary_union(county_geometries)
                make_multicounty_map(union, borders, state, filename_c)

                if geometry is not None:
                    shape = union
                    lines = LineCollection(
                        get_borders(county_geometries, show_progress=False),
                        colors="#959595",
                        lw=LW,
                    )
            else:
                county = county_geometries[0]

                shutil.copyfile(
                    f"{directory}/{place_counties[0].removeprefix(NCP)}.png", filename_c
                )

                if geometry is not None:
                    shape = county

            if shape is not None:
                axes = setup_plot(shape, padding=0.025)
                axes.add_patch(PolygonPatch(shape, fc="#fefb00", ec="#959595", lw=LW))
                if lines is not None:
                    axes.add_collection(lines)
                if isinstance(geometry, Point):
                    axes.plot(
                        geometry.x, geometry.y, marker="o", markersize=1.5, color="k"
                    )
                plt.savefig(filename_p, dpi=DPI, transparent=True)
                plt.close()


def main() -> None:

    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", help="NCG dataset in Turtle format")
    parser.add_argument("geodb", help="GDB file with geometry data")
    parser.add_argument("directory", help="map images output directory")
    args = parser.parse_args()

    Path(args.directory).mkdir(exist_ok=True)

    g = Graph()
    g.parse(args.dataset)
    info("Loading state geometry ...")
    state = load_state(args.geodb)
    info("Loading county geometries ...")
    counties = load_counties(g, args.geodb)
    info("Loading place data ...")
    places = load_places(g)
    info("Checking place geometries")
    check_geometries(places, counties)
    info("Calculating borders ...")
    borders = get_borders(list(counties.values()))
    info("Generating county maps ...")
    make_county_maps(counties, borders, state, args.directory)
    info("Generating place maps ...")
    make_place_maps(places, counties, borders, state, args.directory)


if __name__ == "__main__":
    main()
