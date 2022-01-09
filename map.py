import fiona
import itertools
import json
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from patch import PolygonPatch
from pathlib import Path
from rdflib import Graph, Namespace, URIRef
from shapely.geometry import shape, Point, MultiPolygon

NCP = Namespace("http://n2t.net/ark:/39333/ncg/place/")
NCV = Namespace("http://n2t.net/ark:/39333/ncg/vocab#")
NCT = Namespace("http://n2t.net/ark:/39333/ncg/type#")
GEOJSON = Namespace("https://purl.org/geojson/vocab#")

# USGS data is EPSG:4269, we could reproject to EPSG:32019


def load_state() -> MultiPolygon:
    with fiona.open(
        "GovtUnit_North_Carolina_State_GDB.zip", layer="GU_StateOrTerritory"
    ) as c:
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


def load_counties(g: Graph) -> dict[URIRef, MultiPolygon]:
    counties = {}
    with fiona.open(
        "GovtUnit_North_Carolina_State_GDB.zip", layer="GU_CountyOrEquivalent"
    ) as c:
        for r in c:
            if r["properties"]["State_Name"] == "North Carolina":
                counties[
                    get_county_uri(g, r["properties"]["County_Name"])
                ] = MultiPolygon(shape(r["geometry"]))
    return counties


def get_borders(mp: MultiPolygon) -> list[list[tuple[float, float]]]:
    borders = []
    for p1, p2 in itertools.combinations(mp.geoms, 2):
        if p1.touches(p2):
            i = p1.intersection(p2)
            if i.geom_type == "MultiLineString":
                for line in i.geoms:
                    x, y = line.xy
                    borders.append(list(zip(x, y)))
    return borders


def setup_plot(outline: MultiPolygon):
    minx, miny, maxx, maxy = outline.bounds  # type: ignore
    w, h = maxx - minx, maxy - miny
    fig = plt.figure(frameon=False)
    axes = fig.add_axes([0, 0, 1, 1])
    axes.set_xlim(minx - 0.2 * w, maxx + 0.2 * w)
    axes.set_ylim(miny - 0.2 * h, maxy + 0.2 * h)
    axes.set_aspect(1)
    axes.axis("off")
    return axes


def make_county_maps(counties: dict[URIRef, MultiPolygon]) -> None:
    county_borders = get_borders(
        MultiPolygon(list(itertools.chain(*[mp.geoms for mp in counties.values()])))
    )
    state = load_state()
    axes = setup_plot(state)
    axes.add_patch(PolygonPatch(state, fc="none", ec="#959595", lw=0.2))
    axes.add_collection(LineCollection(county_borders, colors="#959595", lw=0.2))

    for uri, mp in counties.items():
        patch = PolygonPatch(mp, fc="#fefb00", ec="none")
        axes.add_patch(patch)
        plt.savefig(f"maps/{uri.removeprefix(NCP)}.png", dpi=168.75, transparent=True)
        patch.remove()

    plt.close()


def make_place_maps(county: MultiPolygon, places: list[tuple[URIRef, Point]]) -> None:
    axes = setup_plot(county)
    axes.add_patch(PolygonPatch(county, fc="#fefb00", ec="#959595", lw=0.2))

    for uri, point in places:
        marker = axes.plot(point.x, point.y, marker="*", color="k")[0]
        plt.savefig(f"maps/{uri.removeprefix(NCP)}.png", dpi=168.75, transparent=True)
        marker.remove()

    plt.close()


def load_places_by_county(
    g: Graph, counties: dict[URIRef, MultiPolygon]
) -> dict[URIRef, tuple[MultiPolygon, list[tuple[URIRef, Point]]]]:
    places_by_county = {county: (mp, []) for county, mp in counties.items()}
    results = g.query(
        """
SELECT ?place ?county ?geojson WHERE {
  ?place
    ncv:county ?county ;
    geojson:geometry ?geojson .
}
"""
    )
    for row in results:
        if row.county not in counties:
            continue

        geometry = json.loads(str(row.geojson))
        if not geometry["type"] == "Point":
            continue

        point = Point(*geometry["coordinates"])

        if counties[row.county].contains(point):
            places_by_county[row.county][1].append((row.place, point))

    return places_by_county


Path("maps").mkdir(exist_ok=True)

g = Graph()
g.parse("dataset.ttl")
counties = load_counties(g)
places_by_county = load_places_by_county(g, counties)
make_county_maps(counties)
for county, places in places_by_county.values():
    make_place_maps(county, places)
