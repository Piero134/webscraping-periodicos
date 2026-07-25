import requests
import pandas as pd
import json
import os
from datetime import datetime, timezone

# ==========================
# CONFIGURACION
# ==========================

# Carpeta donde vive este script. Todas las rutas se anclan aqui para que
# el script funcione sin importar desde donde se ejecute (CWD independiente).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Archivo de salida (dentro de la misma carpeta del script)
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "elcomercio_politica.csv")

# Maximo de antiguedad de noticias a recolectar (en anos)
ANIOS_MAXIMOS = 2

# Endpoint principal de la API de El Comercio (Arc / PageBuilder)
BASE_URL = "https://elcomercio.pe/pf/api/v3/content/fetch/story-feed-by-section"

# Cantidad de noticias por pagina (offset avanza de STORIES_QTY en STORIES_QTY)
STORIES_QTY = 100

# Campos que le pedimos a la API (reducido a lo que realmente usamos,
# para que la respuesta pese menos y sea mas rapida)
INCLUDED_FIELDS = (
    "headlines.basic,"
    "subheadlines.basic,"
    "credits.by._id,"
    "credits.by.name,"
    "websites.elcomercio.website_url,"
    "content_restrictions.content_code,"
    "display_date,"
    "taxonomy.tags.text"
)

# Valores de 'content_restrictions.content_code' que consideramos "de paga".
# 'metered' = notas con medidor de lecturas gratis / paywall dinamico.
# Se agrega tambien 'premium' por si la API lo usa en otras secciones.
CODIGOS_DE_PAGA = {"metered", "premium"}

# Si es True, las notas de paga se descartan del CSV.
# Si es False, se incluyen pero con una columna 'es_paga' marcada.
EXCLUIR_NOTAS_DE_PAGA = True

# ==========================
# ESTRUCTURA DE LA API (Arc / PageBuilder)
# ==========================
"""
La API responde con un objeto JSON que, en el formato estandar de Arc,
trae la lista de noticias en la clave 'content_elements':

{
  "content_elements": [
    {
      "_id": "...",
      "display_date": "2026-05-11T17:25:59.123Z",
      "headlines": {
        "basic": "Titulo de la noticia"
      },
      "subheadlines": {
        "basic": "Bajada / resumen"
      },
      "credits": {
        "by": [
          { "_id": "...", "name": "Nombre del Autor" }
        ]
      },
      "websites": {
        "elcomercio": {
          "website_url": "/politica/2026/05/11/ruta-de-la-noticia"
        }
      },
      "content_restrictions": {
        "content_code": "metered"
      }
    }
  ],
  "count": 100,
  "next": 100
}

Nota sobre 'content_code': se confirmo en produccion que las notas de pago
(medidor / paywall) traen "content_code": "metered". Las notas libres
simplemente no traen la clave 'content_restrictions' o el campo viene vacio.

NOTA: si al correr el script ves un KeyError en 'content_elements',
imprime response.json().keys() para ver la clave raiz real y avisame
para ajustar el parser.
"""


def dentro_del_rango(fecha_str, anios=2):
    """
    Convierte la fecha entregada por la API (ISO 8601, ej: 2026-05-11T17:25:59.123Z)
    a datetime y verifica si esta dentro del rango de tiempo permitido.
    """
    fecha_str = fecha_str.replace("Z", "+00:00")
    fecha = datetime.fromisoformat(fecha_str)
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)

    ahora = datetime.now(timezone.utc)
    dias = (ahora - fecha).days

    return dias <= anios * 365


def construir_query(feed_offset):
    """
    Arma el parametro 'query' (JSON) que la API espera, igual que
    se ve en la URL capturada desde el navegador.
    """
    query = {
        "section": "/politica",
        "feedOffset": feed_offset,
        "stories_qty": STORIES_QTY,
        "includedFields": INCLUDED_FIELDS
    }
    return json.dumps(query, separators=(",", ":"))


def obtener_noticias_pagina(feed_offset):
    """
    Realiza una peticion GET a la API de El Comercio para un offset especifico.
    """
    params = {
        "query": construir_query(feed_offset),
        "_website": "elcomercio"
    }

    try:
        response = requests.get(
            BASE_URL,
            params=params,
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            }
        )

        print(f"GET {response.url}")
        print(f"STATUS {response.status_code}")

        if response.status_code != 200:
            print(f"El offset {feed_offset} fallo. Se detiene el scraping.")
            return None

        return response.json()

    except Exception as e:
        print(f"Error procesando el offset {feed_offset}: {e}")
        return None


# ==========================
# RECOLECCION
# ==========================

noticias = []

feed_offset = 0

while True:

    print(f"\nProcesando offset {feed_offset}...")

    data = obtener_noticias_pagina(feed_offset)

    if data is None:
        print("Fin del scraping por error o limite de API.")
        break

    articulos = data.get("content_elements", [])

    if not articulos:
        print("No hay mas articulos.")
        break

    noticias_validas = 0
    detener = False

    for articulo in articulos:

        fecha = articulo.get("display_date")

        if not fecha:
            continue

        if not dentro_del_rango(fecha, ANIOS_MAXIMOS):
            detener = True
            continue

        autor = ""
        creditos = articulo.get("credits", {}).get("by", [])
        if creditos:
            autor = creditos[0].get("name", "")

        titulo = articulo.get("headlines", {}).get("basic", "")
        resumen = articulo.get("subheadlines", {}).get("basic", "")

        # Tags: la API de Arc expone las etiquetas editoriales en taxonomy.tags
        # (cada una es un objeto con 'text'). Se guardan sin duplicados,
        # concatenadas con ", " (mismo formato que los demas medios).
        taxonomia = articulo.get("taxonomy", {}) or {}
        tags_texto = ", ".join(dict.fromkeys(
            t["text"] for t in (taxonomia.get("tags") or []) if t.get("text")
        ))

        url_relativa = (
            articulo.get("websites", {})
            .get("elcomercio", {})
            .get("website_url", "")
        )

        url_completa = (
            "https://elcomercio.pe" + url_relativa
            if url_relativa.startswith("/")
            else url_relativa
        )

        content_code = (
            articulo.get("content_restrictions", {}) or {}
        ).get("content_code", "")

        es_paga = content_code in CODIGOS_DE_PAGA

        if es_paga and EXCLUIR_NOTAS_DE_PAGA:
            continue

        noticia = {
            "medio": "El Comercio",
            "fecha": fecha,
            "titulo": titulo,
            "autor": autor,
            "url": url_completa,
            "resumen": resumen,
            "tags": tags_texto,
        }

        noticias.append(noticia)
        noticias_validas += 1

    print(f"Noticias validas encontradas: {noticias_validas}")

    if detener:
        print("Noticias demasiado antiguas detectadas. Fin del scraping.")
        break

    # La API indica el siguiente offset en 'next'. Si no viene, ya no hay mas paginas.
    siguiente = data.get("next")

    if siguiente is None:
        print("Ultima pagina alcanzada (la API no devolvio 'next').")
        break

    feed_offset = siguiente

# ==========================
# EXPORTAR
# ==========================

df = pd.DataFrame(noticias)

# Normalizar el orden de columnas (mismo esquema en todos los medios)
df = df.reindex(columns=["medio", "fecha", "titulo", "autor", "url", "resumen", "tags"])

df.to_csv(
    ARCHIVO_SALIDA,
    index=False,
    encoding="utf-8-sig"
)

print("\n=== RESUMEN ===")
print(f"Total noticias: {len(df)}")
print(f"Archivo: {ARCHIVO_SALIDA}")
