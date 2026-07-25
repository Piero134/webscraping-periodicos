"""
Une todos los CSV '*_noticias_completas.csv' de los distintos medios en un
unico archivo normalizado al esquema:

    medio, fecha, titulo, autor, url, resumen, tags, texto_completo

- Busca automaticamente cada carpeta de medio (El Comercio, El Peruano,
  La Republica, Peru21, RPP).
- Si a algun CSV le falta una de las columnas (p. ej. El Comercio sin 'tags'),
  la crea vacia; y descarta columnas extra que no esten en el esquema.
- Convierte los NaN en cadena vacia para que el CSV final quede limpio.
- Deduplica por 'url' (conserva la primera aparicion) e informa cuantas quito.
"""

import os
import glob
import pandas as pd

# Carpeta donde vive este script (raiz del proyecto). Rutas ancladas aqui.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Esquema final (orden exacto de columnas de salida)
COLUMNAS = ["medio", "fecha", "titulo", "autor", "url", "resumen", "tags", "texto_completo"]

# Archivo de salida
ARCHIVO_SALIDA = os.path.join(BASE_DIR, "noticias_completas_unificado.csv")


def cargar_normalizado(ruta):
    """Lee un CSV y lo devuelve con exactamente las COLUMNAS, en ese orden."""
    df = pd.read_csv(ruta, encoding="utf-8-sig", dtype=str)

    # Avisar de columnas que se descartan (algo fuera del esquema)
    extra = [c for c in df.columns if c not in COLUMNAS]
    if extra:
        print(f"   (columnas ignoradas: {extra})")

    # reindex crea como NaN las columnas que falten y respeta el orden pedido
    df = df.reindex(columns=COLUMNAS)
    return df


def main():
    # Buscar todos los *_noticias_completas.csv en subcarpetas de un nivel
    patron = os.path.join(BASE_DIR, "*", "*_noticias_completas.csv")
    rutas = sorted(glob.glob(patron))

    if not rutas:
        print("No se encontro ningun '*_noticias_completas.csv'.")
        return

    print("Uniendo archivos:")
    partes = []
    for ruta in rutas:
        df = cargar_normalizado(ruta)
        rel = os.path.relpath(ruta, BASE_DIR)
        print(f" - {rel}: {len(df)} filas")
        partes.append(df)

    unido = pd.concat(partes, ignore_index=True)

    # Limpieza: NaN -> "" y espacios sobrantes en los extremos
    unido = unido.fillna("")
    for col in COLUMNAS:
        unido[col] = unido[col].astype(str).str.strip()

    # Deduplicar por url (solo cuando la url no esta vacia)
    total_antes = len(unido)
    con_url = unido["url"] != ""
    dup = unido[con_url].duplicated(subset="url", keep="first")
    if dup.any():
        idx_dup = unido[con_url].index[dup]
        unido = unido.drop(index=idx_dup).reset_index(drop=True)

    unido.to_csv(ARCHIVO_SALIDA, index=False, encoding="utf-8-sig")

    print("\n=== RESUMEN ===")
    print(f"Filas totales unidas: {total_antes}")
    print(f"Duplicados por url eliminados: {total_antes - len(unido)}")
    print(f"Filas finales: {len(unido)}")
    print("Por medio:")
    for medio, n in unido["medio"].value_counts().items():
        con_tags = (unido[(unido["medio"] == medio) & (unido["tags"] != "")]).shape[0]
        print(f"   {medio}: {n} filas  ({con_tags} con tags)")
    print(f"\nArchivo: {ARCHIVO_SALIDA}")


if __name__ == "__main__":
    main()
