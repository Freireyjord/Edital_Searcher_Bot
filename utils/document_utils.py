import os, sys, requests
if getattr(sys, 'frozen', False):
    DIR_TESS = os.path.join(sys._MEIPASS, "tesseract_bin")
else:
    DIR_TESS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tesseract_bin")

import pytesseract
pytesseract.pytesseract.tesseract_cmd = os.path.join(DIR_TESS, "tesseract.exe")
os.environ["TESSDATA_PREFIX"] = os.path.join(DIR_TESS, "tessdata")

from pypdf import PdfReader
from pdf2image import convert_from_path
from pdfminer.high_level import extract_text
import io
import config

def baixar_e_ler_pdf_ocr(url_pdf, nome_arquivo, termos_ignorados):
    if any(t in url_pdf.lower() for t in termos_ignorados): 
        return ""
    caminho = os.path.join(config.DIRETORIO_PDFS, nome_arquivo)
    try:
        resp = requests.get(url_pdf, timeout=15)
        with open(caminho, 'wb') as f: 
            f.write(resp.content)
    except: 
        return ""
    
    texto = ""
    try:
        leitor = PdfReader(caminho)
        for p in leitor.pages: 
            texto += p.extract_text() or ""
    except: 
        pass
        
    if len(texto.strip()) < 50:
        try:
            imgs = convert_from_path(caminho, first_page=1, last_page=10, dpi=150)
            for img in imgs: 
                texto += pytesseract.image_to_string(img, lang='por') + "\n"
        except: 
            pass
    return texto

def extrair_texto_pdf_miner(url_pdf, log):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url_pdf, headers=headers, timeout=25)
        if resp.status_code == 200:
            with io.BytesIO(resp.content) as stream_pdf:
                texto = extract_text(stream_pdf)
                return texto if texto else ""
    except Exception as e:
        log(f"        [⚠️] Erro ao extrair PDF ({url_pdf}): {e}")
    return ""
