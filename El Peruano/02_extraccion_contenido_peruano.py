import pandas as pd
import requests
import os
from bs4 import BeautifulSoup
import re
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==========================
# CONFIGURACION
# ==========================

# Carpeta donde vive este script. Anclamos las rutas aquí para que el script
# funcione sin importar desde dónde se ejecute (CWD independiente).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ARCHIVO_ENTRADA = os.path.join(BASE_DIR, "elperuano_politica.csv")
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "elperuano_noticias_completas.csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Pausa entre requests (segundos) para no saturar el servidor
PAUSA_ENTRE_REQUESTS = 0.5

# ==========================
# CONFIGURACION DE SESIÓN ROBUSTA
# ==========================
# Esto le dice a Python: "Si la conexión falla, intenta hasta 5 veces más,
# esperando cada vez más tiempo entre cada intento para no saturar al servidor".
session = requests.Session()
retries = Retry(
    total=5,                      # Número máximo de reintentos
    backoff_factor=1,             # Tiempo de espera incremental (1s, 2s, 4s...)
    status_forcelist=[500, 502, 503, 504], # Reintentar si el servidor da estos errores
    allowed_methods=["GET"]
)
session.mount('https://', HTTPAdapter(max_retries=retries))
session.mount('http://', HTTPAdapter(max_retries=retries))

# ==========================
# FUNCIONES
# ==========================

def extraer_contenido_noticia(url):
    """
    Descarga el HTML de El Peruano, limpia elementos basura específicos
    (tuits, "Lea también", fechas) y extrae el texto usando los divs.
    """
    if not url:
        return ""

    try:
        response = session.get(url, headers=HEADERS, timeout=20)

        if response.status_code != 200:
            return ""

        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. Buscamos el contenedor principal (ID "contenido" según tu HTML)
        contenedor_principal = soup.find('div', id='contenido')

        # Fallbacks por si alguna nota antigua cambia de ID
        if not contenedor_principal:
            contenedor_principal = soup.find('div', class_='nota-contenido')
        if not contenedor_principal:
            return ""

        # ==========================================
        # FASE DE LIMPIEZA (DECOMPOSE)
        # ==========================================

        # A) Eliminar el bloque de la fecha (<time>)
        for tiempo in contenedor_principal.find_all('time'):
            tiempo.decompose()

        # B) Eliminar los tuits incrustados: por la clase estandar 'twitter-tweet'
        #    y por las clases internas que usa el codigo de Twitter/X.
        for tuit in contenedor_principal.find_all(['div', 'blockquote'], class_=re.compile(r'twitter-tweet', re.I)):
            tuit.decompose()
        for bt in contenedor_principal.find_all(class_=re.compile(r'css-901oao|r-poiln3|css-16my406')):
            bt.decompose()

        # C) Eliminar la sección "Lea también en El Peruano"
        patron_relacionados = re.compile(
            r'(Lea también en El Peruano|También lea en El Peruano)',
            re.IGNORECASE
        )

        textos_relacionados = contenedor_principal.find_all(string=patron_relacionados)

        for texto_basura in textos_relacionados:
            padre = texto_basura.parent

            # eliminar también el contenedor superior si existe
            if padre:
                contenedor = padre.find_parent(['div', 'p', 'section'])
                if contenedor:
                    contenedor.decompose()
                else:
                    padre.decompose()

        # ==========================================
        # FASE DE EXTRACCION DE TEXTO
        # ==========================================

        # Como los párrafos son <div>, extraemos el texto de todo el contenedor YA LIMPIO.
        # 'separator=" "' evita que las palabras de etiquetas juntas se peguen.
        # 'strip=True' ignora automáticamente los saltos de línea y divs vacíos como <div><br></div>.
        texto_crudo = contenedor_principal.get_text(separator=" ", strip=True)

        # Limpiamos dobles o triples espacios que se puedan haber generado en la extracción
        texto_final = re.sub(r'\s+', ' ', texto_crudo).strip()

        return texto_final

    except Exception as e:
        print(f"Error crítico procesando {url}: {e}")
        return ""

# ==========================
# EJECUCION
# ==========================

print("Iniciando extracción de texto para El Peruano...")

# Reanudar si ya existe la salida; si no, partir del CSV de enlaces del paso 01
if os.path.exists(ARCHIVO_SALIDA):
    print(f"Archivo de progreso encontrado: {ARCHIVO_SALIDA}")
    try:
        df_final = pd.read_csv(ARCHIVO_SALIDA)
    except Exception as e:
        print(f"Error leyendo archivo de progreso: {e}")
        exit()
    if 'texto_completo' not in df_final.columns:
        df_final['texto_completo'] = ""
else:
    try:
        df_final = pd.read_csv(ARCHIVO_ENTRADA)
    except FileNotFoundError:
        print(f"Error: No se encontró el archivo {ARCHIVO_ENTRADA}.")
        exit()
    df_final['texto_completo'] = ""

# Normalizar el orden de columnas (mismo esquema en todos los medios)
df_final = df_final.reindex(columns=["medio", "fecha", "titulo", "autor", "url", "resumen", "tags", "texto_completo"])

total = len(df_final)

for index, row in df_final.iterrows():
    # Saltar noticias ya procesadas
    texto_actual = row.get('texto_completo', '')
    if pd.notna(texto_actual) and str(texto_actual).strip():
        continue

    url = row['url']
    print(f"[{index + 1}/{total}] Extrayendo: {url}")
    df_final.at[index, 'texto_completo'] = extraer_contenido_noticia(url)
    time.sleep(PAUSA_ENTRE_REQUESTS)

    # Guardar progreso cada 20 noticias
    if (index + 1) % 20 == 0:
        df_final.to_csv(ARCHIVO_SALIDA, index=False, encoding='utf-8-sig')
        print(f"Progreso guardado ({index + 1}/{total})")

# ==========================
# EXPORTACION
# ==========================
df_final.to_csv(ARCHIVO_SALIDA, index=False, encoding='utf-8-sig')

print("\nExtracción completada con éxito.")
print("Archivo guardado en:", ARCHIVO_SALIDA)