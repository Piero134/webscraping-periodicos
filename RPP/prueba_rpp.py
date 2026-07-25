"""
Script de sondeo para RPP Noticias.
Descarga el HTML real (1) del archivo diario y (2) de un articulo, e imprime
pistas sobre los selectores (contenedores, clases, byline, tags) para poder
escribir 01 y 02 con selectores correctos.
"""

import requests
from bs4 import BeautifulSoup
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

URL_ARCHIVO = "https://rpp.pe/archivo/politica/2026-07-16"
URL_ARTICULO = (
    "https://rpp.pe/politica/congreso/"
    "karla-schaefer-aseguro-que-el-fujimorismo-respeto-el-orden-constitucional-"
    "y-la-investidura-presidencial-durante-los-ultimos-gobiernos-noticia-1697599"
)


def sondear_archivo():
    print("=" * 70)
    print("ARCHIVO DIARIO:", URL_ARCHIVO)
    print("=" * 70)
    r = requests.get(URL_ARCHIVO, headers=HEADERS, timeout=20)
    print("STATUS", r.status_code, "| URL final:", r.url)
    soup = BeautifulSoup(r.text, "html.parser")

    # Enlaces de noticia
    enlaces = soup.find_all("a", href=re.compile(r"-noticia-\d+"))
    print(f"\nAnchors '-noticia-<id>' encontrados: {len(enlaces)}")
    for a in enlaces[:8]:
        clases_padres = []
        p = a.parent
        for _ in range(3):
            if p is None:
                break
            clases_padres.append((p.name, p.get("class"), p.get("id")))
            p = p.parent
        print("  href:", a.get("href"))
        print("   texto:", (a.get_text(strip=True) or "")[:80])
        print("   cadena de padres:", clases_padres)
        print()


def sondear_articulo():
    print("=" * 70)
    print("ARTICULO:", URL_ARTICULO)
    print("=" * 70)
    r = requests.get(URL_ARTICULO, headers=HEADERS, timeout=20)
    print("STATUS", r.status_code, "| URL final:", r.url)
    soup = BeautifulSoup(r.text, "html.parser")

    # H1 / titulo
    h1 = soup.find("h1")
    print("\nH1:", h1.get_text(strip=True) if h1 else None, "| class:", h1.get("class") if h1 else None)

    # Candidatos a contenedor del cuerpo: el div/article/section con mas <p>
    candidatos = []
    for tag in soup.find_all(["div", "article", "section"]):
        n_p = len(tag.find_all("p", recursive=False)) + len(tag.find_all("p"))
        if n_p >= 3:
            candidatos.append((n_p, tag.name, tag.get("class"), tag.get("id")))
    candidatos.sort(key=lambda x: x[0], reverse=True)
    print("\nTop contenedores por # de <p>:")
    for c in candidatos[:8]:
        print("  ", c)

    # Byline / autor
    print("\nPosibles autores (links a /autor... o class con 'author'):")
    for a in soup.find_all("a", href=re.compile(r"/autor|/blog", re.I))[:5]:
        print("  ", a.get("href"), "|", a.get_text(strip=True)[:50])
    for el in soup.find_all(class_=re.compile(r"author|autor|byline", re.I))[:5]:
        print("   class:", el.get("class"), "->", el.get_text(" ", strip=True)[:60])

    # Fecha / time
    print("\nElementos <time>:")
    for t in soup.find_all("time")[:5]:
        print("  ", t.get("datetime"), "|", t.get_text(strip=True)[:40])

    # Tags
    print("\nPosibles tags (links a /tag o /buscar o class 'tag'):")
    for a in soup.find_all("a", href=re.compile(r"/tag|/temas|/buscar", re.I))[:10]:
        print("  ", a.get("href"), "|", a.get_text(strip=True)[:40])
    for el in soup.find_all(class_=re.compile(r"tag", re.I))[:5]:
        print("   class:", el.get("class"))

    # Meta descripcion (posible resumen/lead)
    meta_desc = soup.find("meta", attrs={"name": "description"})
    print("\nmeta[name=description]:", meta_desc.get("content")[:120] if meta_desc else None)
    h2 = soup.find("h2")
    print("Primer H2 (posible bajada):", h2.get_text(strip=True)[:120] if h2 else None, "| class:", h2.get("class") if h2 else None)


if __name__ == "__main__":
    sondear_archivo()
    print("\n")
    sondear_articulo()
