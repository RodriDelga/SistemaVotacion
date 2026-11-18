"""Convierte el GeoJSON de entidades (mexicoHigh.json) en rutas SVG compactas.

Uso:  python scripts/build_map.py
Entrada: scripts/mexicoHigh.source.json  (https://github.com/angelnmara/geojson, mexicoHigh.json)
Salida:  src/assets/mexico-states.json   -> {width, height, states:[{id, name, key, d}]}
`key` es el nombre normalizado (mayusculas, sin acentos), igual que normalizeRegionName de backend.py.
"""
import json, math, unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = 640.0
MIN_STEP = 0.6      # px: descarta vertices mas cercanos (simplificacion)
MIN_AREA = 1.5      # px^2: descarta islotes diminutos


def norm(name: str) -> str:
    d = unicodedata.normalize("NFD", name)
    return " ".join("".join(c for c in d if unicodedata.category(c) != "Mn").upper().split())


def rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]] + []
    out = []
    for poly in geom["coordinates"]:
        out.append(poly[0])
    return out


def main():
    data = json.loads((HERE / "mexicoHigh.source.json").read_text(encoding="utf-8"))
    lon0 = 24.0
    k = math.cos(math.radians(lon0))
    pts = [(x * k, -y) for f in data["features"] for r in rings(f["geometry"]) for x, y in r]
    minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
    miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
    scale = W / (maxx - minx)
    H = (maxy - miny) * scale
    states = []
    for f in data["features"]:
        parts = []
        for ring in rings(f["geometry"]):
            proj = [((x * k - minx) * scale, (-y - miny) * scale) for x, y in ring]
            area = abs(sum(proj[i][0] * proj[(i + 1) % len(proj)][1] - proj[(i + 1) % len(proj)][0] * proj[i][1]
                           for i in range(len(proj)))) / 2
            if area < MIN_AREA:
                continue
            kept = [proj[0]]
            for p in proj[1:]:
                if math.hypot(p[0] - kept[-1][0], p[1] - kept[-1][1]) >= MIN_STEP:
                    kept.append(p)
            if len(kept) < 3:
                continue
            parts.append("M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in kept) + "Z")
        name = f["properties"]["name"]
        states.append({"id": f["properties"]["id"], "name": name, "key": norm(name), "d": "".join(parts)})
    states.sort(key=lambda s: s["name"])
    out = {"width": round(W), "height": round(H), "states": states}
    (HERE.parent / "src" / "assets" / "mexico-states.json").write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("estados:", len(states), "tamano:", round(len(json.dumps(out)) / 1024), "KB", "viewBox", out["width"], out["height"])


main()
