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
from shapely.ops import unary_union
from tqdm import tqdm
from typing import Union, Optional

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


def err(s: str):
    print(f"Error: {s}", file=sys.stderr)


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
    rdf:type nct:County ;
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


def load_places(g: Graph) -> dict[URIRef, tuple[Optional[Point], list[URIRef]]]:
    places = {}
    results = g.query(
        """
SELECT ?place ?county ?geojson WHERE {
  ?place ncv:county ?county .
  OPTIONAL { ?place geojson:geometry ?geojson }
}
"""
    )
    for row in tqdm(results):
        if row.place not in places:
            point = None
            if row.geojson is not None:
                geometry = json.loads(str(row.geojson))
                if geometry["type"] == "Point":
                    point = Point(*geometry["coordinates"])

            places[row.place] = (point, [])

        places[row.place][1].append(row.county)

    return places


def get_borders(counties: list[MultiPolygon]) -> list[list[tuple[float, float]]]:
    mp = MultiPolygon(list(itertools.chain(*[mp.geoms for mp in counties])))
    n = len(mp.geoms)
    borders = []
    for p1, p2 in tqdm(
        itertools.combinations(mp.geoms, 2),
        total=(factorial(n) / factorial(2) / factorial(n - 2)),
    ):
        if p1.touches(p2):
            i = p1.intersection(p2)
            if i.geom_type == "MultiLineString":
                for line in i.geoms:
                    x, y = line.xy
                    borders.append(list(zip(x, y)))
    return borders


def setup_plot(shape: Union[Polygon, MultiPolygon], padding: float = 0.0):
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
    multicounty: Polygon,
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
    places: dict[URIRef, tuple[Optional[Point], list[URIRef]]],
    counties: dict[URIRef, MultiPolygon],
    borders: list[list[tuple[float, float]]],
    state: MultiPolygon,
    directory: str,
) -> None:

    for uri, (point, place_counties) in tqdm(places.items()):

        ncgid = uri.removeprefix(NCP)
        filename_c = f"{directory}/{ncgid}-counties.png"
        filename_p = f"{directory}/{ncgid}.png"

        if path.exists(filename_c):
            continue

        county_geometries = [counties[c] for c in place_counties if c in counties]
        shape, lines = None, None

        if len(place_counties) > 1:
            if len(county_geometries) == 0:
                continue

            multicounty = Polygon(unary_union(county_geometries))
            make_multicounty_map(multicounty, borders, state, filename_c)

            if point is not None:
                shape = multicounty
                lines = LineCollection(
                    get_borders(county_geometries), colors="#959595", lw=LW
                )
        else:
            county = counties.get(place_counties[0])
            if county is None:
                continue

            shutil.copyfile(
                f"{directory}/{place_counties[0].removeprefix(NCP)}.png", filename_c
            )

            if point is not None:
                shape = county

        if shape is not None:
            axes = setup_plot(shape, padding=0.025)
            axes.add_patch(PolygonPatch(shape, fc="#fefb00", ec="#959595", lw=LW))
            if lines is not None:
                axes.add_collection(lines)
            axes.plot(point.x, point.y, marker="o", markersize=1.5, color="k")
            plt.savefig(filename_p, dpi=DPI, transparent=True)
            plt.close()

            if not any((cg.buffer(0.01).contains(point) for cg in county_geometries)):
                err(f"Point for {ncgid} is not in any of its counties")


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
    info("Calculating borders ...")
    borders = get_borders(list(counties.values()))
    info("Loading place data ...")
    places = load_places(g)
    info("Generating county maps ...")
    make_county_maps(counties, borders, state, args.directory)
    info("Generating place maps ...")
    make_place_maps(places, counties, borders, state, args.directory)


if __name__ == "__main__":
    main()
