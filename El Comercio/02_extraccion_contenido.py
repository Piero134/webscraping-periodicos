"""
Script de extraccion de contenido (Web Scraping) para noticias de El Comercio.
Este script lee un archivo CSV con enlaces a noticias, descarga el codigo HTML de
cada enlace, limpia los elementos basura (publicidad, sugerencias, tags, tuits,
modulos de IA) y extrae el texto principal de la noticia en un formato continuo
(una sola celda).
"""

import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import re
import os

# ==========================
# CONFIGURACION
# ==========================

# Carpeta donde vive este script. Anclamos las rutas aqui para que el script
# funcione sin importar desde donde se ejecute (CWD independiente).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Archivos de lectura (generado en el paso anterior) y de escritura
ARCHIVO_ENTRADA = os.path.join(BASE_DIR, "elcomercio_politica.csv")
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "elcomercio_noticias_completas.csv")

# Cabeceras para simular que la peticion viene de un navegador web real y evitar bloqueos del servidor
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Pausa entre requests para no saturar el servidor (segundos)
PAUSA_ENTRE_REQUESTS = 1.0


# ==========================
# FUNCIONES
# ==========================

def extraer_contenido_noticia(url):
    """
    Descarga el HTML, elimina todo el ruido (tuits, videos, enlaces recomendados,
    tags) y extrae el texto util preservando los espacios entre etiquetas HTML
    anidadas (negritas, enlaces, marcadores).

    Parametros:
    - url (str): Enlace de la noticia a extraer.

    Retorna:
    - str: El cuerpo de la noticia en una sola cadena de texto continuo.
    """
    try:
        # Peticion GET al servidor web
        response = requests.get(url, headers=HEADERS, timeout=15)

        # Verificacion de exito en la conexion
        if response.status_code != 200:
            print(f"Error {response.status_code} al acceder a {url}")
            return ""

        # Parseo del DOM utilizando BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')

        # ==========================================
        # LOCALIZACION DEL CONTENEDOR PRINCIPAL
        # ==========================================
        # El Comercio marca los parrafos del cuerpo con itemprop="description"
        # y clase "sc__font-paragraph". Buscamos el contenedor mas cercano que
        # agrupe a todos esos parrafos; si no se encuentra, caemos a <article>.

        parrafo_muestra = soup.find(
            'p',
            attrs={'itemprop': 'description'}
        )

        if parrafo_muestra:
            # Subimos al padre que agrupa todos los parrafos del cuerpo
            contenedor_principal = parrafo_muestra.find_parent(
                ['div', 'article', 'section']
            )
        else:
            contenedor_principal = None

        if not contenedor_principal:
            contenedor_principal = soup.find('article')

        if not contenedor_principal:
            return ""

        # ==========================================
        # FASE DE DESTRUCCION DE RUIDO (DECOMPOSE)
        # ==========================================

        # A) Tuits, videos y otros embeds incrustados.
        # Incluye los blockquote de "LEE:" / "MAS:" (recomendaciones), que tambien se botan.
        for embed in contenedor_principal.find_all(
            ['blockquote', 'iframe', 'script', 'style', 'figure']
        ):
            embed.decompose()

        # B) Bloques de "TE PUEDE INTERESAR" / listas de enlaces relacionados
        relacionados = contenedor_principal.find_all(
            ['ul', 'div'],
            class_=re.compile(r'related|interlinking|recommend|tags-list', re.I)
        )
        for bloque in relacionados:
            bloque.decompose()

        # C) Cualquier resto de redes sociales / widgets
        for widget in contenedor_principal.find_all(
            class_=re.compile(r'twitter|social|embed|advert|banner', re.I)
        ):
            widget.decompose()

        # ==========================================
        # FASE DE EXTRACCION DE TEXTO
        # ==========================================

        # Priorizamos los parrafos marcados explicitamente como cuerpo de noticia
        elementos = contenedor_principal.find_all(
            ['p', 'h2', 'h3', 'li'],
            attrs={'itemprop': 'description'}
        )

        # Fallback: si por algun motivo no hay parrafos con itemprop
        # (nota con otra plantilla), tomamos todos los p/h2/h3/li del contenedor
        if not elementos:
            elementos = contenedor_principal.find_all(['p', 'h2', 'h3', 'li'])

        texto_limpio = []

        for el in elementos:
            # 1. separator=" " evita palabras pegadas (ej. negritas o enlaces)
            texto = el.get_text(separator=" ", strip=True)

            # 2. Limpiamos dobles espacios accidentales
            texto = re.sub(r'\s+', ' ', texto).strip()

            if not texto:
                continue

            # Filtro de seguridad adicional para modulos que hayan esquivado el decompose
            texto_mayusculas = texto.upper()
            if any(
                frase in texto_mayusculas
                for frase in ["LEE:", "MÁS:", "MAS:", "TE PUEDE INTERESAR", "LEER RESUMEN", "TE RECOMENDAMOS"]
            ):
                continue

            # Formateo de lista: agrega un guion a los elementos <li>
            if el.name == 'li':
                texto = f"- {texto}"

            texto_limpio.append(texto)

        # Une toda la extraccion en un solo bloque de texto continuo
        texto_final = " ".join(texto_limpio)

        return texto_final

    except Exception as e:
        # En caso de falla critica, se atrapa el error para no detener el bucle
        print(f"Error procesando la URL {url}: {e}")
        return ""


# ==========================
# EJECUCION
# ==========================

print("Iniciando extraccion de texto definitivo...")

try:
    df = pd.read_csv(ARCHIVO_ENTRADA)
except FileNotFoundError:
    print(f"Error: No se encontro el archivo {ARCHIVO_ENTRADA}.")
    exit()

contenidos = []

for index, row in df.iterrows():
    url = row['url']
    print(f"[{index + 1}/{len(df)}] Extrayendo de: {url}")

    texto = extraer_contenido_noticia(url)
    contenidos.append(texto)

    time.sleep(PAUSA_ENTRE_REQUESTS)


# ==========================
# EXPORTACION
# ==========================

df_final = df.copy()
df_final['texto_completo'] = contenidos

# Normalizar el orden de columnas (mismo esquema en todos los medios)
df_final = df_final.reindex(columns=["medio", "fecha", "titulo", "autor", "url", "resumen", "tags", "texto_completo"])

df_final.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")

print("\n=== RESUMEN ===")
print(f"Total procesadas: {len(df_final)}")
print(f"Con texto extraido: {(df_final['texto_completo'] != '').sum()}")
print(f"Archivo: {ARCHIVO_SALIDA}")
