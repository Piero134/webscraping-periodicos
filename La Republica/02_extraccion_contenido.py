"""
Script de extraccion de contenido (Web Scraping) para noticias.
Este script lee un archivo CSV con enlaces a noticias, descarga el codigo HTML de
cada enlace, limpia los elementos basura (publicidad, sugerencias, tags, modulos de IA)
y extrae el texto principal de la noticia en un formato continuo (una sola celda).
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
ARCHIVO_ENTRADA = os.path.join(BASE_DIR, "larepublica_politica.csv")
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "larepublica_noticias_completas.csv")

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
    Descarga el HTML, elimina todo el ruido (IA, tags, enlaces recomendados) y extrae
    el texto util preservando los espacios entre etiquetas HTML anidadas.

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

        # Localizamos el contenedor principal que envuelve el cuerpo del articulo
        contenedor_principal = soup.find('div', id='interna_content')

        # Fallback en caso el id principal no exista en esta noticia especifica
        if not contenedor_principal:
            contenedor_principal = soup.find('article')

        # Si definitivamente no existe contenedor de texto, retornamos vacio
        if not contenedor_principal:
            return ""

        # ==========================================
        # FASE DE DESTRUCCION DE RUIDO (DECOMPOSE)
        # ==========================================
        # Se buscan elementos especificos del arbol HTML y se destruyen
        # para que no interfieran con la extraccion de texto.

        # A) Destruimos la bajada/resumen principal (ya lo tenemos en el CSV)
        teaser = contenedor_principal.find('h2', class_=re.compile(r'teaser'))
        if teaser:
            teaser.decompose()

        # B) Bloque de interlinking (noticias incrustadas que redirigen a otros lados)
        for link in contenedor_principal.find_all('ul', class_=re.compile(r'Interlinking')):
            link.decompose()

        # C) Citas de recomendacion "PUEDES VER"
        for cita in contenedor_principal.find_all('div', class_=re.compile(r'Quote_wrapper')):
            cita.decompose()

        # D) Modulo flotante de Inteligencia Artificial ("Leer resumen")
        for bloque in contenedor_principal.find_all(class_=re.compile(r'aiContent')):
            bloque.decompose()

        # E) Lista de tags (etiquetas) al final de la pagina
        for bloque_tag in contenedor_principal.find_all('ul', class_=re.compile(r'tags-list')):
            bloque_tag.decompose()

        # ==========================================
        # FASE DE EXTRACCION DE TEXTO CORREGIDA
        # ==========================================

        # Filtramos unicamente parrafos, subtitulos y viñetas
        elementos = contenedor_principal.find_all(['p', 'h2', 'h3', 'li'])

        texto_limpio = []

        for el in elementos:
            # 1. Agregamos separator=" " para evitar palabras pegadas (ej. negritas o enlaces)
            texto = el.get_text(separator=" ", strip=True)

            # 2. Limpiamos cualquier doble espacio accidental que se haya generado usando regex
            texto = re.sub(r'\s+', ' ', texto).strip()

            # Evita agregar lineas vacias
            if not texto:
                continue

            # Filtro de seguridad adicional para atrapar modulos que hayan esquivado el decompose
            texto_mayusculas = texto.upper()
            if "PUEDES VER" in texto_mayusculas or "TE RECOMENDAMOS" in texto_mayusculas or "LEER RESUMEN" in texto_mayusculas:
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
    # Carga de la base de datos de enlaces
    df = pd.read_csv(ARCHIVO_ENTRADA)
except FileNotFoundError:
    print(f"Error: No se encontro el archivo {ARCHIVO_ENTRADA}.")
    exit()

contenidos = []

for index, row in df.iterrows():
    url = row['url']
    print(f"[{index + 1}/{len(df)}] Extrayendo de: {url}")

    # Llamada a la funcion por cada iteracion
    texto = extraer_contenido_noticia(url)
    contenidos.append(texto)

    # Pausa para no saturar el servidor y evitar bloqueos
    time.sleep(PAUSA_ENTRE_REQUESTS)


# ==========================
# EXPORTACION
# ==========================

# Copia del DataFrame para adjuntar la nueva columna
df_final = df.copy()
df_final['texto_completo'] = contenidos

# Normalizar el orden de columnas (mismo esquema en todos los medios)
df_final = df_final.reindex(columns=["medio", "fecha", "titulo", "autor", "url", "resumen", "tags", "texto_completo"])

# Exportacion final aplicando codificacion UTF-8 con BOM para una visualizacion correcta en Excel
df_final.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")

print("\nExtraccion completada con exito. Limpieza de tags aplicada.")
