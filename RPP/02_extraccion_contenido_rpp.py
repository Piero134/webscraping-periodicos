"""
Extraccion de contenido (Web Scraping) para noticias de RPP Noticias.

Lee el CSV de enlaces generado por 01_recoleccion_links_rpp.py, descarga cada
articulo, limpia el ruido (tarjetas de noticias relacionadas, byline, embeds) y
extrae el texto principal en una sola celda ('texto_completo').

Como el listado del archivo NO trae autor / resumen / tags, este paso tambien
los completa a partir del HTML del articulo, para mantener el mismo esquema que
los otros medios.
"""

import pandas as pd
import requests
import os
import re
import json
import time
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================
# CONFIGURACION
# ==========================

# Carpeta donde vive este script. Anclamos las rutas aqui para que el script
# funcione sin importar desde donde se ejecute (CWD independiente).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_ENTRADA = os.path.join(BASE_DIR, "rpp_politica.csv")
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "rpp_noticias_completas.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Pausa entre requests para no saturar el servidor (segundos)
PAUSA_ENTRE_REQUESTS = 0.5

# Frases de modulos de recomendacion que se filtran del cuerpo por seguridad
FRASES_RUIDO = [
    "TE SUGERIMOS", "TE RECOMENDAMOS", "LEE TAMBIÉN", "LEE TAMBIEN",
    "LEER RESUMEN", "MÁS SOBRE", "MAS SOBRE", "SIGUIENTE NOTA", "NEWSLETTER",
]

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

def _texto_limpio(elemento):
    """Devuelve el texto de un elemento normalizando espacios."""
    return re.sub(r"\s+", " ", elemento.get_text(" ", strip=True)).strip()


def _esta_vacio(valor):
    """True si el valor de una celda esta vacio (incluye NaN de pandas)."""
    return pd.isna(valor) or not str(valor).strip()


def _tags_desde_keywords(soup):
    """
    Fallback de tags cuando el articulo no trae el bloque propio de etiquetas:
    usa las palabras clave que el sitio expone en <meta name="keywords"> y,
    si no hay, en el JSON-LD ("keywords"). Devuelve un string "a, b, c" sin
    duplicados (mismo formato que los tags normales) o "" si no encuentra nada.
    """
    m = soup.find("meta", attrs={"name": re.compile(r"^keywords$", re.I)})
    if m and m.get("content", "").strip():
        partes = [p.strip() for p in m["content"].split(",") if p.strip()]
        if partes:
            return ", ".join(dict.fromkeys(partes))

    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(s.string or "")
        except Exception:
            continue
        for obj in (data if isinstance(data, list) else [data]):
            k = obj.get("keywords") if isinstance(obj, dict) else None
            if k:
                partes = k if isinstance(k, list) else [p.strip() for p in str(k).split(",")]
                partes = [p for p in partes if p and str(p).strip()]
                if partes:
                    return ", ".join(dict.fromkeys(partes))
    return ""


def extraer_datos_noticia(url):
    """
    Descarga el articulo y devuelve un dict con:
      texto_completo, autor, resumen, tags
    (autor/resumen/tags pueden venir vacios si no se encuentran).
    """
    vacio = {"texto_completo": "", "autor": "", "resumen": "", "tags": ""}

    if not isinstance(url, str) or not url.strip():
        return vacio

    try:
        response = session.get(url, headers=HEADERS, timeout=20)
        if response.status_code != 200:
            print(f"Error {response.status_code} al acceder a {url}")
            return vacio

        soup = BeautifulSoup(response.text, "html.parser")

        # --------------------------------------
        # METADATOS (autor / resumen / tags)
        # Se extraen ANTES de limpiar el contenedor.
        # --------------------------------------

        # Autor: primer enlace a /autor/ con texto
        autor = ""
        for a in soup.find_all("a", href=re.compile(r"/autor/")):
            t = a.get_text(strip=True)
            if t:
                autor = t
                break
        if not autor:
            el_autor = soup.find(class_=re.compile(r"article__author-name", re.I))
            if el_autor:
                autor = re.sub(r"^\s*por\s+", "", el_autor.get_text(" ", strip=True), flags=re.I).strip()

        # Resumen / bajada: meta[name=description]
        resumen = ""
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            resumen = meta_desc["content"].strip()

        # Tags: enlaces dentro del bloque de etiquetas del articulo
        tags = ""
        bloque_tags = soup.find(class_=re.compile(r"article__block--tags", re.I))
        if bloque_tags:
            nombres = [a.get_text(strip=True) for a in bloque_tags.find_all("a") if a.get_text(strip=True)]
            tags = ", ".join(dict.fromkeys(nombres))  # sin duplicados, preservando orden

        # Fallback: si el articulo no trae el bloque propio de etiquetas, usar
        # las keywords que expone el sitio (meta[name=keywords] / JSON-LD).
        if not tags:
            tags = _tags_desde_keywords(soup)

        # --------------------------------------
        # CONTENEDOR PRINCIPAL DEL CUERPO
        # --------------------------------------
        contenedor = soup.find("div", class_="article__content")
        if not contenedor:
            contenedor = soup.find("article", class_="article")
        if not contenedor:
            contenedor = soup.find("article")
        if not contenedor:
            return {"texto_completo": "", "autor": autor, "resumen": resumen, "tags": tags}

        # --------------------------------------
        # FASE DE DESTRUCCION DE RUIDO (DECOMPOSE)
        # --------------------------------------

        # A) Tarjetas de noticias relacionadas incrustadas (<article class="news ...">)
        for tarjeta in contenedor.find_all("article"):
            tarjeta.decompose()

        # B) Embeds: tuits, videos, figuras, scripts
        for embed in contenedor.find_all(["blockquote", "iframe", "script", "style", "figure", "aside"]):
            embed.decompose()

        # C) Modulos de video/podcast embebidos (contenedor 'gray-media'), que dejan
        #    titulos y descripciones tipo "EP232 | INFORMES | ...". Se eliminan enteros.
        for el in contenedor.find_all(class_=re.compile(r"gray-media", re.I)):
            el.decompose()

        # D) Restos de modulos por clase (relacionados, mas leido, recirculacion, tags)
        for el in contenedor.find_all(class_=re.compile(r"news__|related|mas-leido|recirc|paginator|tags", re.I)):
            el.decompose()

        # E) La bajada/resumen (primer <h2> sin clase) ya la tenemos en 'resumen'
        primera_bajada = contenedor.find("h2", class_=False)
        if primera_bajada:
            primera_bajada.decompose()

        # --------------------------------------
        # EXTRACCION DE TEXTO
        # --------------------------------------
        elementos = contenedor.find_all(["p", "h2", "h3", "li"])
        texto_limpio = []

        for el in elementos:
            texto = _texto_limpio(el)
            if not texto:
                continue

            # Filtrar el byline ("por Redacción RPP") que aparece como <p> corto
            if el.name == "p" and len(texto) < 60 and re.match(r"(?i)^por\s+", texto):
                continue

            # Filtro de modulos de recomendacion que hayan esquivado el decompose
            texto_mayus = texto.upper()
            if any(frase in texto_mayus for frase in FRASES_RUIDO):
                continue

            if el.name == "li":
                texto = f"- {texto}"

            texto_limpio.append(texto)

        texto_final = " ".join(texto_limpio)

        return {
            "texto_completo": texto_final,
            "autor": autor,
            "resumen": resumen,
            "tags": tags,
        }

    except Exception as e:
        print(f"Error procesando la URL {url}: {e}")
        return vacio


# ==========================
# EJECUCION (reanudable)
# ==========================

print("Iniciando extraccion de texto para RPP...")

# Si ya existe un archivo de salida, continuar desde alli
if os.path.exists(ARCHIVO_SALIDA):
    print(f"Archivo de progreso encontrado: {ARCHIVO_SALIDA}")
    try:
        df_final = pd.read_csv(ARCHIVO_SALIDA)
        if "texto_completo" not in df_final.columns:
            df_final["texto_completo"] = ""
    except Exception as e:
        print(f"Error leyendo archivo de progreso: {e}")
        exit()
else:
    try:
        df_final = pd.read_csv(ARCHIVO_ENTRADA)
        df_final["texto_completo"] = ""
    except FileNotFoundError:
        print(f"Error: No se encontro el archivo {ARCHIVO_ENTRADA}.")
        exit()

# Asegurar que existan las columnas que vamos a completar y que sean de tipo
# 'object' (texto). Si el CSV las trae todas vacias, pandas las infiere como
# float64 (NaN) y rechazaria asignarles un string; por eso forzamos 'object'.
for col in ["autor", "resumen", "tags", "texto_completo"]:
    if col not in df_final.columns:
        df_final[col] = ""
    df_final[col] = df_final[col].astype("object")

# Normalizar el orden de columnas (mismo esquema en todos los medios)
df_final = df_final.reindex(columns=["medio", "fecha", "titulo", "autor", "url", "resumen", "tags", "texto_completo"])

total = len(df_final)

for index, row in df_final.iterrows():

    texto_actual = row.get("texto_completo", "")
    tags_actual = row.get("tags", "")

    # Saltar noticias ya completas: solo si YA tienen texto Y tags. Las que
    # tienen texto pero no tags se reprocesan para rellenar los tags faltantes.
    if (pd.notna(texto_actual) and str(texto_actual).strip()) and not _esta_vacio(tags_actual):
        continue

    url = row["url"]
    print(f"[{index + 1}/{total}] Extrayendo: {url}")

    datos = extraer_datos_noticia(url)

    # No pisar el texto ya extraido cuando reprocesamos una fila solo por tags
    if _esta_vacio(row.get("texto_completo", "")) and datos["texto_completo"]:
        df_final.at[index, "texto_completo"] = datos["texto_completo"]
    # Completar metadatos solo si el listado no los traia
    if datos["autor"] and _esta_vacio(row.get("autor", "")):
        df_final.at[index, "autor"] = datos["autor"]
    if datos["resumen"] and _esta_vacio(row.get("resumen", "")):
        df_final.at[index, "resumen"] = datos["resumen"]
    if datos["tags"] and _esta_vacio(row.get("tags", "")):
        df_final.at[index, "tags"] = datos["tags"]

    # Guardar progreso cada 20 noticias
    if (index + 1) % 20 == 0:
        df_final.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")
        print(f"Progreso guardado ({index + 1}/{total})")

    time.sleep(PAUSA_ENTRE_REQUESTS)

# ==========================
# EXPORTACION FINAL
# ==========================

df_final.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")

print("\n=== RESUMEN ===")
print(f"Total procesadas: {len(df_final)}")
print(f"Con texto extraido: {(df_final['texto_completo'].fillna('') != '').sum()}")
print(f"Archivo: {ARCHIVO_SALIDA}")
