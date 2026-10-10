"""Descoberta e priorização de PDFs anexos em páginas de editais (sem I/O de rede)."""
import re
import unicodedata
from urllib.parse import urljoin, urlparse, unquote

# Palavras que sugerem que o PDF é o documento principal / relevante
RELEVANTES = (
    "edital", "chamada", "regulamento", "termo de referencia", "anexo", "instrucoes",
    "diretrizes", "carta convite", "selecao", "errata", "retificacao",
)

# PDFs que só atrapalham (comparado por "palavra inteira": 'ata' não casa com 'data')
_IGNORAR = re.compile(
    r"(?<![a-z])(resultado|resultados|homologacao|homologado|recurso|recursos|"
    r"ata|atas|cartilha|logo|banner|folder)(?![a-z])"
)

_EXT_NAO_PDF = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".doc", ".docx",
                ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".rar", ".mp4", ".mp3")


def _norm(txt):
    txt = unicodedata.normalize("NFD", (txt or "").lower())
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return re.sub(r"[-_.+%/]+", " ", txt)


def _parece_pdf(url_abs):
    p = urlparse(url_abs)
    caminho = unquote(p.path).lower()
    if caminho.endswith(_EXT_NAO_PDF):
        return False
    return (
        caminho.endswith(".pdf")
        or ".pdf" in unquote(p.query).lower()
        or "@@download" in caminho      # gov.br (Plone)
        or "/documents/" in caminho     # Liferay (Finep)
    )


def pares_de_soup(soup):
    """Extrai (href, rótulo) de todos os <a href> de um BeautifulSoup."""
    return [(a["href"], a.get_text(" ", strip=True)) for a in soup.find_all("a", href=True)]


def coletar_candidatos(pares, url_base):
    """
    pares: iterável de (href, rótulo). Retorna lista de dicts {url, rotulo, score},
    sem duplicatas e sem PDFs de resultado/ata/etc.
    """
    vistos, candidatos = set(), []
    for href, rotulo in pares or []:
        href = (href or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        url_abs = urljoin(url_base, href).split("#")[0]
        if url_abs in vistos or not _parece_pdf(url_abs):
            continue
        vistos.add(url_abs)

        nome = unquote(urlparse(url_abs).path.rsplit("/", 1)[-1])
        texto = _norm(f"{nome} {rotulo}")
        if _IGNORAR.search(texto):
            continue

        score = sum(1 for palavra in RELEVANTES if palavra in texto)
        if urlparse(url_abs).path.lower().endswith(".pdf"):
            score += 1   # extensão explícita: mais provável de ser PDF de verdade
        candidatos.append({"url": url_abs, "rotulo": rotulo, "score": score})
    return candidatos


def selecionar_pdfs(candidatos, maximo):
    """Os `maximo` mais relevantes (ordem original preservada em caso de empate)."""
    ordenados = sorted(candidatos, key=lambda c: -c["score"])
    return ordenados[:maximo]