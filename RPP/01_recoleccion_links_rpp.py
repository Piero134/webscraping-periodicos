"""
Recoleccion de links de la seccion Politica de RPP Noticias.

A diferencia de los otros medios, RPP no expone una API JSON de listados, pero si
un ARCHIVO por fecha:  https://rpp.pe/archivo/politica/AAAA-MM-DD
Este script recorre el archivo dia por dia hacia atras (desde hoy) hasta cubrir
ANIOS_MAXIMOS anos, recolectando los enlaces de cada noticia.

El listado solo entrega titulo + url + la fecha del dia. Los campos 'autor',
'resumen' y 'tags' se dejan vacios aqui y se completan en el paso 02 (extraccion),
para mantener el mismo esquema de columnas que los otros medios.
"""

import requests
import pandas as pd
import os
import re
import time
from datetime import date, timedelta
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================
# CONFIGURACION
# ==========================

# Carpeta donde vive este script. Anclamos las rutas aqui para que el script
# funcione sin importar desde donde se ejecute (CWD independiente).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "rpp_politica.csv")

# Maximo de antiguedad de noticias a recolectar (en anos)
ANIOS_MAXIMOS = 2

# Plantilla del archivo diario de la seccion Politica
BASE_ARCHIVO = "https://rpp.pe/archivo/politica/{fecha}"   # fecha = AAAA-MM-DD

# Pausa entre peticiones (segundos) para no saturar el servidor
PAUSA_ENTRE_DIAS = 0.4

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

def obtener_noticias_dia(fecha):
    """
    Descarga el archivo de un dia y devuelve una lista de (titulo, url) de las
    noticias encontradas. Cada noticia esta dentro de <article class="news">,
    con el titulo enlazado en <h2 class="news__title"> a.
    """
    url_dia = BASE_ARCHIVO.format(fecha=fecha.strftime("%Y-%m-%d"))

    try:
        response = session.get(url_dia, headers=HEADERS, timeout=20)
        if response.status_code != 200:
            print(f"  [{fecha}] STATUS {response.status_code}, se omite el dia.")
            return []
    except Exception as e:
        print(f"  [{fecha}] Error de red: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    resultados = []
    for art in soup.select("article.news"):
        # El anchor con el titulo esta dentro de h2.news__title
        a = art.select_one("h2.news__title a")
        if a is None:
            a = art.find("a", href=re.compile(r"-noticia-\d+"))
        if a is None:
            continue

        href = a.get("href", "")
        if "-noticia-" not in href:
            continue

        url_completa = href if href.startswith("http") else "https://rpp.pe" + href
        titulo = a.get_text(strip=True)

        resultados.append((titulo, url_completa))

    return resultados


# ==========================
# RECOLECCION
# ==========================

noticias = []
urls_vistas = set()

hoy = date.today()
fecha_limite = hoy - timedelta(days=ANIOS_MAXIMOS * 365)
fecha_actual = hoy

print(f"Recolectando desde {hoy} hasta {fecha_limite} (RPP - Politica)...")

while fecha_actual >= fecha_limite:

    encontrados = obtener_noticias_dia(fecha_actual)

    nuevos = 0
    for titulo, url in encontrados:
        if url in urls_vistas:
            continue
        urls_vistas.add(url)

        noticias.append({
            "medio": "RPP",
            "fecha": fecha_actual.strftime("%Y-%m-%d"),
            "titulo": titulo,
            "autor": "",      # se completa en el paso 02
            "url": url,
            "resumen": "",    # se completa en el paso 02
            "tags": ""        # se completa en el paso 02
        })
        nuevos += 1

    print(f"[{fecha_actual}] noticias nuevas: {nuevos} | acumulado: {len(noticias)}")

    fecha_actual -= timedelta(days=1)
    time.sleep(PAUSA_ENTRE_DIAS)

# ==========================
# EXPORTAR
# ==========================

df = pd.DataFrame(noticias)

# Normalizar el orden de columnas (mismo esquema en todos los medios)
df = df.reindex(columns=["medio", "fecha", "titulo", "autor", "url", "resumen", "tags"])

df.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")

print("\n=== RESUMEN ===")
print(f"Total noticias: {len(df)}")
print(f"Archivo: {ARCHIVO_SALIDA}")
