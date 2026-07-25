"""
Recoleccion de links de la seccion Politica de Peru21.

Peru21 usa el CMS "Sirius Publisher" (Drupal) y NO expone una API JSON de listados,
pero su seccion de politica tiene paginacion por ruta numerica:
    https://peru21.pe/politica/      (pagina 1)
    https://peru21.pe/politica/2/    (pagina 2)
    https://peru21.pe/politica/3/    ...
Una pagina inexistente devuelve 0 noticias, lo que sirve como corte natural.

Cada tarjeta del listado trae la fecha (<time datetime>), asi que se filtra por
antiguedad (ANIOS_MAXIMOS) igual que en los otros medios. Como las paginas van de
la noticia mas nueva a la mas vieja, al aparecer una fuera de rango se detiene.

El listado solo entrega titulo + url + fecha. Los campos 'autor', 'resumen' y
'tags' se dejan vacios aqui y se completan en el paso 02, para mantener el mismo
esquema de columnas que los otros medios.
"""

import requests
import pandas as pd
import os
import re
import time
from datetime import datetime
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================
# CONFIGURACION
# ==========================

# Carpeta donde vive este script. Anclamos las rutas aqui para que el script
# funcione sin importar desde donde se ejecute (CWD independiente).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "peru21_politica.csv")

# Maximo de antiguedad de noticias a recolectar (en anos)
ANIOS_MAXIMOS = 2

# Plantilla del listado paginado. La pagina 1 es "" y el resto "N/".
BASE_LISTADO = "https://peru21.pe/politica/{page}"

# Pausa entre peticiones (segundos) para no saturar el servidor
PAUSA_ENTRE_PAGINAS = 0.4

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ==========================
# SESION ROBUSTA (reintentos con backoff)
# ==========================
session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[500, 502, 503, 504],
    allowed_methods=["GET"]
)
session.mount("https://", HTTPAdapter(max_retries=retries))
session.mount("http://", HTTPAdapter(max_retries=retries))

# ==========================
# FUNCIONES
# ==========================

def parsear_fecha(fecha_str):
    """
    Extrae la fecha de un texto que puede venir "sucio" (con etiquetas como
    'Fecha Publicado' o nombres de dia). Soporta:
      - ISO/maquina: '2026-07-16 14:17' o '2026-07-16T17:26:07Z'
      - formato local: 'Jue, 16/07/2026 - 12:26' (DD/MM/YYYY)
    Devuelve un datetime naive (hora local) o None si no encuentra fecha.
    """
    if not fecha_str:
        return None

    texto = fecha_str.strip()

    # 1) Patron maquina: AAAA-MM-DD [HH:MM(:SS)]
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?", texto)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4)) if m.group(4) else 0
        mi = int(m.group(5)) if m.group(5) else 0
        ss = int(m.group(6)) if m.group(6) else 0
        try:
            return datetime(y, mo, d, hh, mi, ss)
        except ValueError:
            return None

    # 2) Patron local: DD/MM/AAAA [- HH:MM]
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:\s*-\s*(\d{2}):(\d{2}))?", texto)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4)) if m.group(4) else 0
        mi = int(m.group(5)) if m.group(5) else 0
        try:
            return datetime(y, mo, d, hh, mi)
        except ValueError:
            return None

    return None


def dentro_del_rango(fecha_str, anios=2):
    """
    Verifica si la fecha esta dentro del rango de tiempo permitido.
    Si la fecha no se puede parsear, no se descarta por antiguedad.
    """
    fecha = parsear_fecha(fecha_str)
    if fecha is None:
        return True

    dias = (datetime.now() - fecha).days
    return dias <= anios * 365


def obtener_noticias_pagina(pagina):
    """
    Descarga una pagina del listado y devuelve una lista de dicts con
    (titulo, url, fecha) de cada tarjeta de noticia encontrada.
    """
    sufijo = "" if pagina == 1 else f"{pagina}/"
    url_pagina = BASE_LISTADO.format(page=sufijo)

    try:
        response = session.get(url_pagina, headers=HEADERS, timeout=20)
        print(f"GET {response.url} -> STATUS {response.status_code}")
        if response.status_code != 200:
            return []
    except Exception as e:
        print(f"Error procesando la pagina {pagina}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    resultados = []
    # Las tarjetas de noticia son <article class="node node--type-article ...">
    # (vistas 'teaser-2-col' y 'teaser-liquido'). Los <article class="media"> son
    # solo imagenes y se ignoran al no tener enlace de noticia.
    for card in soup.select("article.node--type-article"):
        # Enlace del articulo: /politica/<slug>/ (excluye la paginacion /politica/N/)
        a = card.find("a", href=re.compile(r"^/politica/[a-z0-9-]+/?$"))
        if a is None:
            continue
        href = a.get("href", "")
        if re.match(r"^/politica/\d+/?$", href):
            continue  # es un enlace de paginacion, no una noticia

        url_completa = href if href.startswith("http") else "https://peru21.pe" + href

        # Titulo: heading con clase 'titulo-teaser-...' (2col o liquido)
        titulo_el = card.find(class_=re.compile(r"titulo-teaser"))
        titulo = titulo_el.get_text(strip=True) if titulo_el else a.get_text(strip=True)

        # Fecha: elemento con clase 'fecha-teaser-...' (o <time datetime> como respaldo)
        fecha = ""
        fecha_el = card.find(class_=re.compile(r"fecha-teaser"))
        if fecha_el:
            fecha = fecha_el.get_text(strip=True)
        else:
            time_el = card.find("time")
            if time_el:
                fecha = time_el.get("datetime", "")

        resultados.append({"titulo": titulo, "url": url_completa, "fecha": fecha})

    return resultados


# ==========================
# RECOLECCION
# ==========================

noticias = []
urls_vistas = set()

pagina = 1
paginas_sin_nuevos = 0

print("Recolectando Peru21 - Politica (paginacion numerica)...")

while True:

    print(f"\nProcesando pagina {pagina}...")

    encontrados = obtener_noticias_pagina(pagina)

    # Sin tarjetas: fin del listado (paginacion agotada)
    if not encontrados:
        print("No hay mas noticias. Fin del scraping.")
        break

    nuevos = 0
    detener = False

    for item in encontrados:
        if not dentro_del_rango(item["fecha"], ANIOS_MAXIMOS):
            detener = True
            continue

        url = item["url"]
        if url in urls_vistas:
            continue
        urls_vistas.add(url)

        # Guardar la fecha normalizada (limpia) si se pudo parsear
        fecha_dt = parsear_fecha(item["fecha"])
        fecha_norm = fecha_dt.strftime("%Y-%m-%d %H:%M:%S") if fecha_dt else item["fecha"]

        noticias.append({
            "medio": "Perú21",
            "fecha": fecha_norm,
            "titulo": item["titulo"],
            "autor": "",      # se completa en el paso 02
            "url": url,
            "resumen": "",    # se completa en el paso 02
            "tags": ""        # se completa en el paso 02
        })
        nuevos += 1

    print(f"Noticias nuevas: {nuevos} | acumulado: {len(noticias)}")

    if detener:
        print("Noticias demasiado antiguas detectadas. Fin del scraping.")
        break

    # Salvaguarda: si dos paginas seguidas no aportan URLs nuevas, cortar
    if nuevos == 0:
        paginas_sin_nuevos += 1
        if paginas_sin_nuevos >= 2:
            print("Dos paginas seguidas sin noticias nuevas. Fin del scraping.")
            break
    else:
        paginas_sin_nuevos = 0

    pagina += 1
    time.sleep(PAUSA_ENTRE_PAGINAS)

# ==========================
# EXPORTAR
# ==========================

df = pd.DataFrame(noticias)

# Normalizar el orden de columnas (mismo esquema en todos los medios)
df = df.reindex(columns=["medio", "fecha", "titulo", "autor", "url", "resumen", "tags"])

df.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")

print("\n=== RESUMEN ===")
print(f"Paginas recorridas: {pagina}")
print(f"Total noticias: {len(df)}")
print(f"Archivo: {ARCHIVO_SALIDA}")
