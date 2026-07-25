import requests
import pandas as pd
import os
from datetime import datetime
import re

# ==========================
# CONFIGURACIÓN
# ==========================

# Carpeta donde vive este script. Anclamos las rutas aquí para que el script
# funcione sin importar desde dónde se ejecute (CWD independiente).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Archivo de salida (dentro de la misma carpeta del script)
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "elperuano_politica.csv")

# Máximo de antigüedad de noticias a recolectar (en años)
ANIOS_MAXIMOS = 2

# Endpoint principal de la API de El Peruano
BASE_URL = "https://elperuano.pe/portal/_GetNoticiasSeccionPagingWorker"

# Parámetros base de la consulta a la API
PARAMS_BASE = {
    "idsec": 1,        # ID de la sección (1 = Política)
    "pageSize": 100     # Cantidad de noticias devueltas por página
}

# ==========================
# FUNCIONES
# ==========================

def parsear_fecha_asp(fecha_str):
    """
    Extrae los milisegundos de un formato JSON ASP.NET como '/Date(1781758800000)/'
    y lo convierte en un objeto datetime de Python.
    """
    if not fecha_str:
        return datetime.now()

    match = re.search(r'\d+', fecha_str)
    if match:
        timestamp_ms = int(match.group())
        # Convertimos milisegundos a segundos para fromtimestamp
        return datetime.fromtimestamp(timestamp_ms / 1000.0)

    return datetime.now()

def dentro_del_rango(fecha_obj, anios=2):
    """
    Verifica si el objeto datetime se encuentra dentro del rango permitido.
    """
    dias = (datetime.now() - fecha_obj).days
    return dias <= anios * 365

def obtener_noticias_pagina(page):
    """
    Petición GET a la API de El Peruano para un pageIndex específico.
    """
    params = PARAMS_BASE.copy()
    params["pageIndex"] = page

    try:
        response = requests.get(BASE_URL, params=params, timeout=30)
        print(f"GET {response.url}")
        print(f"STATUS {response.status_code}")

        if response.status_code != 200:
            print(f"La página {page} falló. Se detiene el scraping.")
            return None

        return response.json()

    except Exception as e:
        print(f"Error procesando la página {page}: {e}")
        return None

# ==========================
# RECOLECCIÓN
# ==========================

noticias = []
pagina = 1

while True:
    print(f"\nProcesando página {pagina}...")

    articulos = obtener_noticias_pagina(pagina)

    if not articulos:  # Si la lista está vacía o hubo error
        print("Fin del scraping o no hay más artículos.")
        break

    noticias_validas = 0
    detener = False

    for articulo in articulos:
        # Extraer y transformar fecha
        fecha_obj = parsear_fecha_asp(articulo.get("dtmFecha", ""))

        if not dentro_del_rango(fecha_obj, ANIOS_MAXIMOS):
            detener = True
            continue

        # Formateo de la URL final
        url_amigable = articulo.get("URLFriendLy", "")
        url_completa = f"https://elperuano.pe/{url_amigable}" if url_amigable else ""

        # Construcción del diccionario MANTENIENDO la estructura de La República
        noticia = {
            "medio": "El Peruano",
            "fecha": fecha_obj.strftime("%Y-%m-%d %H:%M:%S"),
            "titulo": articulo.get("vchTitulo", "").strip(),
            "autor": "", # El Peruano no devuelve autor en esta API
            "url": url_completa,
            "resumen": articulo.get("vchDescripcion", "").strip(),
            "tags": ""   # El Peruano no devuelve tags en esta API
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
