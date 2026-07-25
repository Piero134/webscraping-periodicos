"""
Web Scraping de la seccion Actualidad de Canal N (canaln.pe/actualidad).

Canal N (app Next.js) no expone un listado historico paginable: su feed se capa en
~50 noticias recientes. Pero cada noticia tiene un ID numerico secuencial en su URL
(.../-n<ID>) y se puede abrir cualquier articulo por ID con un slug arbitrario:
    https://canaln.pe/actualidad/x-n<ID>   -> redirige a la URL canonica
El articulo trae todos sus datos en el JSON embebido <script id="__NEXT_DATA__">
(props.pageProps.compacto): titulo, fecha (pubtime), bajada, tags, categoria y el
cuerpo en 'bloques'.

Asi que recorremos los IDs hacia atras desde el mas reciente hasta cubrir 2 anos,
nos quedamos con los de la categoria Actualidad y guardamos el mismo esquema de 8
columnas que los demas medios. Reanudable mediante un archivo de checkpoint.

Salida: canaln_noticias_completas.csv
Columnas: medio, fecha, titulo, autor, url, resumen, tags, texto_completo
"""

import requests
import pandas as pd
import os
import re
import json
import time
import html as htmllib
from datetime import date, datetime, timezone, timedelta
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================
# CONFIGURACION
# ==========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "canaln_noticias_completas.csv")
ARCHIVO_CHECKPOINT = os.path.join(BASE_DIR, "canaln_checkpoint.txt")

# Antiguedad maxima de noticias a recolectar (en anos)
ANIOS_MAXIMOS = 2
COLUMNAS = ["medio", "fecha", "titulo", "autor", "url", "resumen", "tags", "texto_completo"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
# Frases de modulos de recomendacion que se filtran del cuerpo por seguridad
FRASES_RUIDO = [
    "TE SUGERIMOS", "TE RECOMENDAMOS", "LEE TAMBIÉN", "LEE TAMBIEN", "LEER RESUMEN",
    "MÁS SOBRE", "MAS SOBRE", "SIGUIENTE NOTA", "NEWSLETTER", "TE PUEDE INTERESAR",
    "MIRA TAMBIÉN", "MIRA TAMBIEN", "VER MÁS", "VER MAS",
]

# Sesion robusta con reintentos y backoff
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504], allowed_methods=["GET"])))

# Fecha a partir de la cual dejamos de recolectar (hace ANIOS_MAXIMOS anos)
fecha_limite = (date.today() - timedelta(days=ANIOS_MAXIMOS * 365)).strftime("%Y-%m-%d")


def limpiar_html(texto):
    """Decodifica entidades HTML, quita etiquetas y normaliza espacios."""
    plano = BeautifulSoup(htmllib.unescape(str(texto)), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", plano).strip()


def obtener_nota(id_nota):
    """
    Descarga el articulo con ese ID y devuelve:
      - un dict con la fila lista (si es de la categoria Actualidad),
      - "DETENER"  si la nota ya es mas vieja que el limite de 2 anos,
      - None       si el ID no sirve (404, otra categoria, error, sin datos).
    """
    try:
        r = session.get(f"https://canaln.pe/actualidad/n-n{id_nota}", headers=HEADERS, timeout=20)
    except Exception as e:
        print(f"  [n{id_nota}] error de red: {e}")
        return None

    # 404 = ese ID no existe (hueco/eliminado); otros errores tambien se saltan
    if r.status_code != 200:
        if r.status_code != 404:
            print(f"  [n{id_nota}] status {r.status_code}")
        return None

    # Extraer el JSON embebido de Next.js, donde vienen todos los datos de la nota
    r.encoding = "utf-8"
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text, re.S)
    if not m:
        return None
    try:
        compacto = json.loads(m.group(1))["props"]["pageProps"].get("compacto")
    except Exception:
        compacto = None
    if not compacto:
        return None

    # Fecha de publicacion: sirve de marcador para cortar a los 2 anos
    try:
        fecha = datetime.fromtimestamp(int(compacto["pubtime"]), tz=timezone.utc).strftime("%Y-%m-%d")
    except (KeyError, TypeError, ValueError):
        fecha = ""
    if fecha and fecha < fecha_limite:
        print(f"[n{id_nota}] fecha {fecha} < limite {fecha_limite}. Fin del recorrido.")
        return "DETENER"

    # Solo nos interesa la categoria Actualidad
    if (compacto.get("categoria") or {}).get("url") != "actualidad":
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Autor: nombre visible del primer enlace /autor/ (sin simbolos decorativos al final)
    autor = ""
    enlace_autor = soup.find("a", href=re.compile(r"/autor/"))
    if enlace_autor:
        autor = re.sub(r"[\s»·>›|]+$", "", limpiar_html(enlace_autor.get_text(" ", strip=True)))

    # Tags: nombres sin duplicados, separados por coma
    tags = ", ".join(dict.fromkeys(
        limpiar_html(t["name"]) for t in (compacto.get("tags") or []) if t.get("name")))

    # Cuerpo: se arma con los bloques de tipo texto (los de imagen/video se ignoran)
    lineas = []
    for bloque in compacto.get("bloques") or []:
        if bloque.get("tipo") not in ("texto", "subtitulo", "sumario", "cita", "lista", "html"):
            continue
        html_bloque = bloque.get("data")
        if not isinstance(html_bloque, str) or not html_bloque.strip():
            continue
        bloque_soup = BeautifulSoup(htmllib.unescape(html_bloque), "html.parser")
        # Quitar figuras, embeds y modulos incrustados antes de leer el texto
        for basura in bloque_soup.find_all(["figure", "figcaption", "iframe", "script", "style", "blockquote"]):
            basura.decompose()
        for basura in bloque_soup.find_all(class_=re.compile(r"imagen|adicional|related|embed|advert|banner|social", re.I)):
            basura.decompose()
        for elem in bloque_soup.find_all(["p", "h2", "h3", "li"]) or [bloque_soup]:
            texto = limpiar_html(elem.get_text(" ", strip=True))
            if not texto or any(frase in texto.upper() for frase in FRASES_RUIDO):
                continue
            lineas.append(f"- {texto}" if elem.name == "li" else texto)

    return {
        "medio": "Canal N",
        "fecha": fecha,
        "titulo": limpiar_html(compacto.get("titulo", "")),
        "autor": autor,
        "url": r.url.split("?")[0],           # URL canonica (tras la redireccion)
        "resumen": limpiar_html(compacto.get("bajada", "")),
        "tags": tags,
        "texto_completo": " ".join(lineas),
    }


# ==========================
# PREPARACION (reanudar)
# ==========================
# Cargar lo ya recolectado, si existe
filas = []
urls_vistas = set()
if os.path.exists(ARCHIVO_SALIDA):
    prev = pd.read_csv(ARCHIVO_SALIDA).reindex(columns=COLUMNAS)
    filas = prev.to_dict("records")
    urls_vistas = set(prev["url"].dropna().astype(str))
    print(f"Reanudando: {len(filas)} noticias ya guardadas.")

# ID por donde empezar: el del checkpoint, o el mas reciente del sitemap de noticias
if os.path.exists(ARCHIVO_CHECKPOINT):
    nid = int(open(ARCHIVO_CHECKPOINT).read().strip())
    print(f"Checkpoint encontrado: continua desde n{nid}")
else:
    sitemap = session.get("https://canaln.pe/sitemap/news", headers=HEADERS, timeout=20).text
    nid = max(int(x) for x in re.findall(r"-n(\d+)", sitemap))
    print(f"ID inicial (mas reciente) detectado: n{nid}")

print(f"Recorriendo IDs desde n{nid} hacia atras hasta cubrir hasta {fecha_limite} (categoria actualidad)...")

# ==========================
# RECORRIDO POR ID
# ==========================
procesados = 0
while nid > 0 and procesados < 60000:   # el 60000 es solo un tope de seguridad
    nota = obtener_nota(nid)
    time.sleep(0.15)                    # pausa tras cada peticion para no saturar

    if nota == "DETENER":
        break
    if isinstance(nota, dict) and nota["url"] not in urls_vistas:
        urls_vistas.add(nota["url"])
        filas.append(nota)

    if nota is None:
        print(f"  [n{nid}] no disponible o no es actualidad")
    else:
        print(f"  procesando n{nid} | recolectadas {len(filas):<5} | {nota['fecha']:<10} | {nota['titulo']}")

    procesados += 1
    nid -= 1

    # Guardar progreso cada 50 IDs (nid queda apuntando al proximo a procesar)
    if procesados % 50 == 0:
        pd.DataFrame(filas).reindex(columns=COLUMNAS).to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")
        open(ARCHIVO_CHECKPOINT, "w").write(str(nid))
        print(f"  [checkpoint] guardado n{nid} | {len(filas)} noticias hasta ahora")

# ==========================
# EXPORTACION FINAL
# ==========================
df = pd.DataFrame(filas).reindex(columns=COLUMNAS)
df.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")
open(ARCHIVO_CHECKPOINT, "w").write(str(nid))

print("\n=== RESUMEN ===")
print(f"IDs procesados: {procesados}")
print(f"Noticias de Actualidad recolectadas: {len(df)}")
if len(df):
    print(f"Rango de fechas: {df['fecha'].min()} a {df['fecha'].max()}")
print(f"Archivo: {ARCHIVO_SALIDA}")
