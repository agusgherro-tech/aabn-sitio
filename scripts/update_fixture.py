"""
Script de actualización automática de fixture y posiciones.
Scrapea altoquedeportes.com.ar para obtener datos de AABN (Liga Regional Río Cuarto).
Actualiza las secciones marcadas en index.html.
"""

import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

# ── Configuración ─────────────────────────────────────────────────────────────
AABN_NOMBRE = "Banda Norte"
HTML_PATH = "index.html"
URL_ESTADISTICAS = "https://altoquedeportes.com.ar/estadisticas/"
URL_FIXTURE = "https://altoquedeportes.com.ar/fixture/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ── Helpers HTML ──────────────────────────────────────────────────────────────

def generar_fila_posiciones(pos, equipo, pj, g, e, p, gf, gc, pts, es_aabn=False):
    """Genera una fila <tr> para la tabla de posiciones."""
    clases_fila = ' class="bg-verde-600 font-bold"' if es_aabn else ""
    color_pts = "text-green-300 font-extrabold text-base" if es_aabn else "text-white font-bold"
    nombre_celda = f'<img src="images.jpeg" alt="" class="h-5 w-auto rounded"> {equipo}' if es_aabn else equipo
    return f"""            <tr{clases_fila}>
              <td class="py-3 px-4 text-green-200">{pos}</td>
              <td class="py-3 px-4 text-white flex items-center gap-2">{nombre_celda}</td>
              <td class="py-3 px-2 text-center text-white">{pj}</td>
              <td class="py-3 px-2 text-center text-white">{g}</td>
              <td class="py-3 px-2 text-center text-white">{e}</td>
              <td class="py-3 px-2 text-center text-white">{p}</td>
              <td class="py-3 px-2 text-center text-white">{gf}</td>
              <td class="py-3 px-2 text-center text-white">{gc}</td>
              <td class="py-3 px-4 text-center {color_pts}">{pts}</td>
            </tr>"""


def generar_card_partido(fecha_num, dia, hora, local, visitante, estadio, es_proximo=False, resultado=None):
    """Genera una card de partido (próximo o resultado)."""
    es_local_aabn = "Banda Norte" in local or "AABN" in local
    es_visit_aabn = "Banda Norte" in visitante or "AABN" in visitante

    nombre_local = "AABN" if es_local_aabn else local
    nombre_visit = "AABN" if es_visit_aabn else visitante

    img_local = '<img src="images.jpeg" alt="AABN" class="h-7 w-auto rounded"> ' if es_local_aabn else ""
    img_visit = ' <img src="images.jpeg" alt="AABN" class="h-7 w-auto rounded">' if es_visit_aabn else ""

    ring = ' ring-2 ring-green-400 ring-offset-2 ring-offset-verde-800' if es_proximo else ""

    # Marcador central: resultado o "vs"
    if resultado:
        goles_l, goles_v = resultado
        marcador = f'<div class="bg-white text-verde-800 font-extrabold text-xl px-4 py-2 rounded-lg text-center leading-none"><span>{goles_l}</span><span class="text-green-600 mx-1">-</span><span>{goles_v}</span></div>'
    else:
        marcador = '<div class="bg-white text-verde-800 font-extrabold text-xl px-4 py-2 rounded-lg">vs</div>'

    badge = '<span class="mt-1 inline-block bg-green-400 text-verde-900 text-xs font-bold px-3 py-0.5 rounded-full">Próximo</span>' if es_proximo else ""

    return f"""      <div class="bg-verde-700 rounded-2xl p-5 flex flex-col sm:flex-row items-center gap-4 border border-verde-500{ring}">
        <div class="text-center sm:w-28 flex-shrink-0">
          <div class="text-green-300 text-xs font-bold uppercase">{dia}</div>
          <div class="text-white font-bold text-lg">{hora}</div>
          <div class="text-green-300 text-xs">Fecha {fecha_num}</div>
        </div>
        <div class="flex-1 flex items-center justify-center gap-3">
          <div class="text-right">
            <div class="font-bold text-white text-sm flex items-center justify-end gap-2">{img_local}{nombre_local}</div>
            <div class="text-green-200 text-xs">Local</div>
          </div>
          {marcador}
          <div>
            <div class="font-bold text-white text-sm flex items-center gap-2">{nombre_visit}{img_visit}</div>
            <div class="text-green-200 text-xs">Visitante</div>
          </div>
        </div>
        <div class="text-center sm:w-32 flex-shrink-0">
          <div class="text-green-200 text-xs">Estadio</div>
          <div class="text-white text-sm font-semibold">{estadio}</div>
          {badge}
        </div>
      </div>"""


# ── Scraping ──────────────────────────────────────────────────────────────────

def scrapear_posiciones(soup):
    """Extrae la tabla de posiciones de Primera A del LRFRC."""
    filas = []
    tablas = soup.find_all("table")
    for tabla in tablas:
        headers = [th.get_text(strip=True).upper() for th in tabla.find_all("th")]
        if "PTS" in headers and "EQUIPO" in headers:
            for i, tr in enumerate(tabla.find_all("tr")[1:], 1):
                celdas = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(celdas) >= 8:
                    equipo = celdas[1] if len(celdas) > 1 else celdas[0]
                    try:
                        datos = {
                            "pos": i,
                            "equipo": equipo,
                            "pj": int(celdas[2]),
                            "g":  int(celdas[3]),
                            "e":  int(celdas[4]),
                            "p":  int(celdas[5]),
                            "gf": int(celdas[6]),
                            "gc": int(celdas[7]),
                            "pts": int(celdas[8]) if len(celdas) > 8 else int(celdas[2]) * 3,
                        }
                        filas.append(datos)
                    except (ValueError, IndexError):
                        continue
            if filas:
                break
    return filas


def scrapear_fixture(soup):
    """Extrae próximos partidos de AABN."""
    partidos = []
    hoy = datetime.now()

    # Busca tablas de fixture que contengan a Banda Norte
    tablas = soup.find_all("table")
    for tabla in tablas:
        texto = tabla.get_text()
        if AABN_NOMBRE in texto or "AABN" in texto:
            for tr in tabla.find_all("tr")[1:]:
                celdas = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(celdas) >= 4 and (AABN_NOMBRE in celdas or "AABN" in celdas):
                    partidos.append(celdas)

    return partidos


# ── Datos de respaldo (cuando no hay scraping disponible) ─────────────────────

def datos_posiciones_respaldo():
    return [
        {"pos": 1, "equipo": "AABN",              "pj": 8, "g": 6, "e": 1, "p": 1, "gf": 18, "gc":  8, "pts": 19},
        {"pos": 2, "equipo": "Dep. Norte",         "pj": 8, "g": 5, "e": 2, "p": 1, "gf": 14, "gc":  9, "pts": 17},
        {"pos": 3, "equipo": "Atlético Sur",       "pj": 8, "g": 4, "e": 1, "p": 3, "gf": 11, "gc": 12, "pts": 13},
        {"pos": 4, "equipo": "Racing Club Norte",  "pj": 8, "g": 3, "e": 2, "p": 3, "gf": 10, "gc": 13, "pts": 11},
        {"pos": 5, "equipo": "Independiente Este", "pj": 8, "g": 2, "e": 1, "p": 5, "gf":  8, "gc": 17, "pts":  7},
    ]


def datos_fixture_respaldo():
    return [
        {"fecha_num": 9,  "dia": "Sáb 14/03", "hora": "16:00 hs", "local": "AABN",        "visitante": "Dep. Norte",      "estadio": "Predio AABN",      "es_proximo": True},
        {"fecha_num": 10, "dia": "Sáb 21/03", "hora": "15:30 hs", "local": "Atlético Sur", "visitante": "AABN",            "estadio": "Est. Atlético Sur","es_proximo": False},
        {"fecha_num": 11, "dia": "Sáb 28/03", "hora": "17:00 hs", "local": "AABN",        "visitante": "Racing Club Norte","estadio": "Predio AABN",      "es_proximo": False},
    ]


# ── Actualizar HTML ───────────────────────────────────────────────────────────

def reemplazar_entre_marcadores(html, inicio, fin, nuevo_contenido):
    patron = re.compile(
        rf'({re.escape(inicio)})(.*?)({re.escape(fin)})',
        re.DOTALL
    )
    return patron.sub(rf'\1\n{nuevo_contenido}\n            \3', html)


def actualizar_html(posiciones, fixture):
    with open(HTML_PATH, encoding="utf-8") as f:
        html = f.read()

    # ── Posiciones ────────────────────────────────────────────────────────────
    filas_html = "\n".join(
        generar_fila_posiciones(
            d["pos"], d["equipo"], d["pj"], d["g"], d["e"], d["p"],
            d["gf"], d["gc"], d["pts"],
            es_aabn=("Banda Norte" in d["equipo"] or d["equipo"] == "AABN")
        )
        for d in posiciones
    )
    html = reemplazar_entre_marcadores(html, "<!-- POSICIONES_START -->", "<!-- POSICIONES_END -->", filas_html)

    # ── Fixture ───────────────────────────────────────────────────────────────
    cards_html = "\n".join(
        generar_card_partido(
            p["fecha_num"], p["dia"], p["hora"],
            p["local"], p["visitante"], p["estadio"],
            es_proximo=p.get("es_proximo", False),
            resultado=p.get("resultado")
        )
        for p in fixture
    )
    html = reemplazar_entre_marcadores(html, "<!-- FIXTURE_START -->", "<!-- FIXTURE_END -->", cards_html)

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] HTML actualizado — {datetime.now().strftime('%Y-%m-%d %H:%M')}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    posiciones = []
    fixture = []

    # Intentar scrapear posiciones
    try:
        print("Scrapeando estadisticas...")
        resp = requests.get(URL_ESTADISTICAS, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        posiciones = scrapear_posiciones(soup)
        print(f"  Posiciones obtenidas: {len(posiciones)} equipos")
    except Exception as e:
        print(f"  [WARN] No se pudo scrapear posiciones: {e}")

    # Intentar scrapear fixture
    try:
        print("Scrapeando fixture...")
        resp = requests.get(URL_FIXTURE, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup_f = BeautifulSoup(resp.text, "html.parser")
        fixture = scrapear_fixture(soup_f)
        print(f"  Partidos encontrados: {len(fixture)}")
    except Exception as e:
        print(f"  [WARN] No se pudo scrapear fixture: {e}")

    # Usar respaldo si no se obtuvo datos
    if not posiciones:
        print("  Usando datos de respaldo para posiciones")
        posiciones = datos_posiciones_respaldo()
    if not fixture:
        print("  Usando datos de respaldo para fixture")
        fixture = datos_fixture_respaldo()

    actualizar_html(posiciones, fixture)


if __name__ == "__main__":
    main()
