"""
Reordena las columnas de los CSV ya generados al esquema estandar, SIN volver
a scrapear. Util si algun archivo se genero con las columnas en otro orden.

Esquema:
  *_politica.csv           -> medio, fecha, titulo, autor, url, resumen, tags
  *_noticias_completas.csv -> medio, fecha, titulo, autor, url, resumen, tags, texto_completo

Lee cada archivo, reordena en memoria y lo reescribe en el mismo sitio
(idempotente: si ya esta bien, no cambia el contenido). Solo toca el orden de
las columnas; no altera los datos.
"""

import os
import glob
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

COLS_POLITICA = ["medio", "fecha", "titulo", "autor", "url", "resumen", "tags"]
COLS_COMPLETAS = COLS_POLITICA + ["texto_completo"]


def normalizar(ruta, columnas):
    rel = os.path.relpath(ruta, BASE_DIR)
    # dtype=str evita que las celdas vacias se conviertan en el texto "nan"
    df = pd.read_csv(ruta, encoding="utf-8-sig", dtype=str)

    orden_actual = list(df.columns)
    faltantes = [c for c in columnas if c not in orden_actual]
    sobrantes = [c for c in orden_actual if c not in columnas]

    # reindex deja exactamente 'columnas' en ese orden (crea faltantes vacias,
    # descarta sobrantes) y luego pasamos los NaN a "" para no escribir "nan"
    df = df.reindex(columns=columnas)
    df = df.fillna("")

    df.to_csv(ruta, index=False, encoding="utf-8-sig")

    if orden_actual == columnas:
        print(f"OK (sin cambios)  {rel}")
    else:
        print(f"REORDENADO        {rel}")
        print(f"    antes: {orden_actual}")
        print(f"    ahora: {columnas}")
        if faltantes:
            print(f"    (columnas creadas vacias: {faltantes})")
        if sobrantes:
            print(f"    (columnas descartadas: {sobrantes})")


def main():
    print("== *_politica.csv ==")
    for ruta in sorted(glob.glob(os.path.join(BASE_DIR, "*", "*_politica.csv"))):
        normalizar(ruta, COLS_POLITICA)

    print("\n== *_noticias_completas.csv ==")
    for ruta in sorted(glob.glob(os.path.join(BASE_DIR, "*", "*_noticias_completas.csv"))):
        normalizar(ruta, COLS_COMPLETAS)


if __name__ == "__main__":
    main()
