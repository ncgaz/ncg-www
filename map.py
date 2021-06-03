import fiona
import itertools
import matplotlib.pyplot as plt
from typing import Optional
from shapely.geometry import shape, MultiPolygon
from matplotlib.collections import LineCollection
from descartes import PolygonPatch

# USGS data is EPSG:4269, we could reproject to EPSG:32019


def load_state() -> Optional[MultiPolygon]:
    with fiona.open(
        "GovtUnit_North_Carolina_State_GDB.zip", layer="GU_StateOrTerritory"
    ) as c:
        for r in c:
            if r["properties"]["State_Name"] == "North Carolina":
                return MultiPolygon(shape(r["geometry"]))
    return None


def load_counties() -> MultiPolygon:
    polygons = []
    with fiona.open(
        "GovtUnit_North_Carolina_State_GDB.zip", layer="GU_CountyOrEquivalent"
    ) as c:
        for r in c:
            if r["properties"]["State_Name"] == "North Carolina":
                polygons.extend(list(MultiPolygon(shape(r["geometry"]))))
    return MultiPolygon(polygons)


def get_borders(mp: MultiPolygon) -> list[list[tuple[float, float]]]:
    borders = []
    for p1, p2 in itertools.combinations(mp, 2):
        if p1.touches(p2):
            i = p1.intersection(p2)
            if i.geom_type == "MultiLineString":
                for line in i:
                    x, y = line.xy
                    borders.append(list(zip(x, y)))
    return borders


state = load_state()
counties = load_counties()
county_borders = get_borders(counties)

minx, miny, maxx, maxy = state.bounds  # type: ignore
w, h = maxx - minx, maxy - miny

fig = plt.figure(frameon=False)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(minx - 0.2 * w, maxx + 0.2 * w)
ax.set_ylim(miny - 0.2 * h, maxy + 0.2 * h)
ax.set_aspect(1)
ax.axis("off")
ax.add_collection(LineCollection(county_borders, colors="#959595", lw=0.2))
ax.add_patch(PolygonPatch(state, fc="none", ec="#959595", lw=0.2))

plt.savefig("map.png", dpi=168.75, transparent=True)
# plt.show()
