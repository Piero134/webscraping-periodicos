import requests
import pandas as pd
import os
from datetime import datetime

# ==========================
# CONFIGURACION
# ==========================

# Carpeta donde vive este script. Anclamos las rutas aqui para que el script
# funcione sin importar desde donde se ejecute (CWD independiente).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Archivo de salida (dentro de la misma carpeta del script)
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "larepublica_politica.csv")

# Maximo de antiguedad de noticias a recolectar (en anos)
ANIOS_MAXIMOS = 2

# Endpoint principal de la API de La Republica
# Esta API devuelve listados de noticias filtrados por categoria y paginacion
BASE_URL = "https://larepublica.pe/api/search/articles"

# Parametros base de la consulta a la API
PARAMS_BASE = {
    "category_slug": "politica",   # Categoria objetivo (politica)
    "limit": 24,                   # Cantidad de noticias devueltas por pagina
    "order_by": "update_date",     # Ordenamiento por fecha de actualizacion (mas recientes primero)
    "view": "section"              # Tipo de vista requerida por la API
}

# Cabeceras de navegador. IMPORTANTE: sin el 'Referer' la API responde 403,
# por eso simulamos que la peticion proviene de la seccion de politica del sitio.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-PE,es;q=0.9",
    "Referer": "https://larepublica.pe/politica",
}

# ==========================
# ESTRUCTURA DE LA API
# ==========================
"""
La API responde con un objeto JSON principal que contiene la clave 'articles'.
Dentro de 'articles', la clave 'data' contiene una lista de diccionarios con la
siguiente estructura exhaustiva:

{
  "articles": {
    "data": [
      {
        "_id": "6a0257796b546b65f809bfb3",
        "title": "Titulo de la noticia",
        "type": "article",
        "date": "2026-05-11 17:25:59",
        "updated_at": "2026-05-11 19:39:10",
        "created_at": "2026-05-11 17:26:01",
        "update_date": "2026-05-11 19:39:10",
        "slug": "/politica/2026/05/11/ruta-de-la-noticia",
        "data": {
          "teaser": "Resumen de la noticia",
          "authors": [
            {
              "fullname": "Nombre del Autor",
              "slug": "/autor/nombre-autor",
              "metadata": [
                {
                  "key": "email",
                  "value": null,
                  "__typename": "MetadataType"
                },
                {
                  "key": "url_photo",
                  "value": "https://ruta-imagen-autor.png",
                  "__typename": "MetadataType"
                }
              ],
              "__typename": "AuthorType"
            }
          ],
          "tags": [
            {
              "name": "Nombre Etiqueta",
              "slug": "/tag/nombre-etiqueta",
              "__typename": "TagType"
            }
          ],
          "categories": [
            {
              "name": "Politica",
              "slug": "/politica",
              "primary": true,
              "__typename": "CategoryReferenceType"
            }
          ],
          "__typename": "ArticleDataType",
          "multimedia": [
            {
              "type": "image",
              "path": "https://ruta-imagen-noticia.jpg",
              "data": {
                "type_video": null,
                "title": "Leyenda de la foto",
                "alt": "Texto alternativo",
                "source": null,
                "image_path": null,
                "embed": null,
                "credits": null,
                "__typename": "MultimediaDataType"
              },
              "__typename": "MultimediaType"
            }
          ]
        },
        "metadata_seo": {
          "keywords": "palabra clave 1, palabra clave 2",
          "__typename": "ArticleMetadataSeoType"
        },
        "metadata": [
          {
            "key": "censored",
            "value": "0",
            "__typename": "MetadataType"
          },
          {
            "key": "commercial_template",
            "value": "no",
            "__typename": "MetadataType"
          }
        ],
        "has_video": false,
        "__typename": "ArticleType"
      }
    ]
  }
}
"""

# ==========================
# FUNCIONES
# ==========================

def dentro_del_rango(fecha_str, anios=2):
    """
    Convierte la fecha entregada por la API a formato datetime y verifica
    si la noticia se encuentra dentro del rango de tiempo permitido.
    """
    fecha = datetime.strptime(fecha_str, "%Y-%m-%d %H:%M:%S")
    dias = (datetime.now() - fecha).days

    return dias <= anios * 365


def obtener_noticias_pagina(page):
    """
    Realiza una peticion GET a la API de noticias para una pagina en especifico.
    """
    params = PARAMS_BASE.copy()
    params["page"] = page

    try:
        response = requests.get(
            BASE_URL,
            params=params,
            headers=HEADERS,
            timeout=30
        )

        print(f"GET {response.url}")
        print(f"STATUS {response.status_code}")

        if response.status_code != 200:
            print(f"La pagina {page} fallo. Se detiene el scraping.")
            return None

        return response.json()

    except Exception as e:
        print(f"Error procesando la pagina {page}: {e}")
        return None


# ==========================
# RECOLECCION
# ==========================

noticias = []

pagina = 1

while True:

    print(f"\nProcesando pagina {pagina}...")

    data = obtener_noticias_pagina(pagina)

    if data is None:
        print("Fin del scraping por error o limite de API.")
        break

    # Extraer los artículos de la respuesta
    articulos = data["articles"]["data"]

    if not articulos:
        print("No hay más artículos.")
        break

    noticias_validas = 0
    detener = False

    for articulo in articulos:
        fecha = articulo["date"]

        if not dentro_del_rango(fecha, ANIOS_MAXIMOS):
            detener = True
            continue

        autores = articulo["data"].get("authors", [])
        autor = autores[0].get("fullname", "") if autores else ""

        tags = articulo["data"].get("tags", [])
        tags_texto = ", ".join(tag["name"] for tag in tags)

        noticia = {
            "medio": "La República",
            "fecha": fecha,
            "titulo": articulo["title"],
            "autor": autor,
            "url": "https://larepublica.pe" + articulo["slug"],
            "resumen": articulo["data"].get("teaser", ""),
            "tags": tags_texto,
        }

        noticias.append(noticia)
        noticias_validas += 1

    print(f"Noticias válidas encontradas: {noticias_validas}")

    if detener:
        print("Noticias demasiado antiguas detectadas. Fin del scraping.")
        break

    pagina += 1

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
