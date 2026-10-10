"""
Leitura de PDFs: download seguro em memória + pdfminer + OCR como fallback.

- pdfminer é o extrator principal (melhor que pypdf para texto corrido).
- OCR (Tesseract) só roda se o PDF não tiver texto nativo (escaneado).
- Tesseract/Poppler são opcionais: sem eles, PDFs escaneados são apenas ignorados.
"""
import io
import os
import sys
import shutil

import requests
from pdfminer.high_level import extract_text

import config
from utils.http_utils import SESSAO

if getattr(sys, 'frozen', False):
    DIR_TESS = os.path.join(sys._MEIPASS, "tesseract_bin")
else:
    DIR_TESS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tesseract_bin")

# Abaixo disso consideramos que o PDF não tem texto nativo (provavelmente escaneado)
MIN_CHARS_TEXTO_NATIVO = 200

_OCR = {"verificado": False, "disponivel": False}


def _configurar_ocr(log):
    """Localiza o Tesseract uma única vez (multiplataforma). Retorna True se utilizável."""
    if _OCR["verificado"]:
        return _OCR["disponivel"]
    _OCR["verificado"] = True

    try:
        import pytesseract

        cmd = os.getenv("TESSERACT_CMD")
        if not cmd:
            nome = "tesseract.exe" if os.name == "nt" else "tesseract"
            embutido = os.path.join(DIR_TESS, nome)
            cmd = embutido if os.path.exists(embutido) else shutil.which("tesseract")
        if not cmd:
            raise FileNotFoundError("executável do Tesseract não encontrado (defina TESSERACT_CMD)")

        pytesseract.pytesseract.tesseract_cmd = cmd
        tessdata = os.path.join(DIR_TESS, "tessdata")
        if os.path.isdir(tessdata):
            os.environ["TESSDATA_PREFIX"] = tessdata

        pytesseract.get_tesseract_version()
        _OCR["disponivel"] = True
    except Exception as e:
        log(f"        [⚠️ OCR] Indisponível, PDFs escaneados serão ignorados: {e}")
    return _OCR["disponivel"]


def baixar_pdf(url_pdf, log=print):
    """Baixa o PDF em memória. Retorna bytes ou None (erro, grande demais ou não é PDF)."""
    limite = config.MAX_PDF_MB * 1024 * 1024
    buffer = bytearray()
    try:
        with SESSAO.get(url_pdf, timeout=(10, 60), stream=True) as resp:
            if resp.status_code != 200:
                log(f"        [⚠️] PDF indisponível (HTTP {resp.status_code}): {url_pdf}")
                return None

            tamanho = resp.headers.get("Content-Length", "")
            if tamanho.isdigit() and int(tamanho) > limite:
                log(f"        [⚠️] PDF ignorado (>{config.MAX_PDF_MB} MB): {url_pdf}")
                return None

            for pedaco in resp.iter_content(chunk_size=65536):
                buffer.extend(pedaco)
                if len(buffer) > limite:
                    log(f"        [⚠️] PDF ignorado (>{config.MAX_PDF_MB} MB): {url_pdf}")
                    return None
    except requests.RequestException as e:
        log(f"        [⚠️] Erro ao baixar PDF ({url_pdf}): {e}")
        return None

    if b"%PDF" not in bytes(buffer[:1024]):
        log(f"        [⚠️] Link não retornou um PDF válido: {url_pdf}")
        return None
    return bytes(buffer)


def _ocr_pdf(conteudo, log):
    if not _configurar_ocr(log):
        return ""
    try:
        import pytesseract
        from pdf2image import convert_from_bytes

        kwargs = {"first_page": 1, "last_page": config.OCR_MAX_PAGINAS, "dpi": 150}
        if os.getenv("POPPLER_PATH"):
            kwargs["poppler_path"] = os.getenv("POPPLER_PATH")

        log(f"        [OCR] PDF sem texto nativo; aplicando OCR nas primeiras {config.OCR_MAX_PAGINAS} páginas...")
        imagens = convert_from_bytes(conteudo, **kwargs)
        return "\n".join(pytesseract.image_to_string(img, lang="por") for img in imagens)
    except Exception as e:
        log(f"        [⚠️ OCR] Falha no OCR (Poppler instalado?): {e}")
        return ""


def extrair_texto_pdf_bytes(conteudo, log=print):
    """Texto nativo via pdfminer; se vier (quase) vazio, tenta OCR."""
    texto = ""
    try:
        texto = extract_text(io.BytesIO(conteudo)) or ""
    except Exception as e:
        log(f"        [⚠️] pdfminer falhou ({e}); tentando OCR.")

    if len(texto.strip()) < MIN_CHARS_TEXTO_NATIVO:
        texto_ocr = _ocr_pdf(conteudo, log)
        if len(texto_ocr.strip()) > len(texto.strip()):
            texto = texto_ocr
    return texto


def extrair_texto_pdf_url(url_pdf, log=print):
    conteudo = baixar_pdf(url_pdf, log)
    if not conteudo:
        return ""
    return extrair_texto_pdf_bytes(conteudo, log)


# Nome antigo mantido para compatibilidade com código existente
extrair_texto_pdf_miner = extrair_texto_pdf_url