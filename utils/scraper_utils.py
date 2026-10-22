import os, time, requests
from bs4 import BeautifulSoup
from datetime import datetime
import config
from utils.http_utils import SESSAO
from utils.texto_utils import (  # noqa: F401  (limpar_texto_extraido reexportado p/ compatibilidade)
    limpar_texto_extraido, montar_texto_com_fontes, tamanho_util, texto_parece_pagina_erro,
)
from utils.url_utils import canonicalizar_url
from utils.pdf_links import pares_de_soup, coletar_candidatos, selecionar_pdfs
from utils.document_utils import extrair_texto_pdf_url, extrair_texto_pdf_bytes


def baixar_pagina(url, log):
    """
    Retorna (tipo, conteudo): ('html', str) | ('pdf', bytes) | (None, None).
    Detecta PDFs servidos em URLs sem extensão .pdf pelo Content-Type.
    """
    try:
        resp = SESSAO.get(url, timeout=20)
        if resp.status_code != 200:
            log(f"        [⚠️] HTTP {resp.status_code} ao abrir {url}")
            return None, None
        if "application/pdf" in resp.headers.get("Content-Type", "").lower():
            return "pdf", resp.content
        return "html", resp.text
    except requests.RequestException as e:
        log(f"        [⚠️] Erro ao baixar página ({url}): {e}")
        return None, None


def analisar_html(html, url_base):
    """Retorna (texto_da_pagina, pares_de_links). Links são coletados ANTES de remover nav/footer."""
    soup = BeautifulSoup(html, "html.parser")
    pares = pares_de_soup(soup)
    for s in soup(["script", "style", "nav", "footer", "header"]):
        s.decompose()
    return soup.get_text(separator=" ", strip=True), pares


def extrair_texto_html(url_html, log):
    """Mantida por compatibilidade: apenas o texto da página."""
    tipo, conteudo = baixar_pagina(url_html, log)
    if tipo == "html":
        return analisar_html(conteudo, url_html)[0]
    return ""


def _salvar_auditoria(url_edital, nome_portal, texto, log):
    try:
        pasta = os.path.join(config.DIRETORIO_PAI, "logs_auditoria")
        os.makedirs(pasta, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = "".join(c for c in nome_portal if c.isalnum() or c in (' ', '_', '-')).strip().replace(" ", "_")
        with open(os.path.join(pasta, f"{nome}_raw_texto_{timestamp}.txt"), "w", encoding="utf-8") as f:
            f.write(f"URL: {url_edital}\nPORTAL: {nome_portal}\n\n{texto}")
    except Exception as e:
        log(f"        [⚠️] Falha ao salvar auditoria: {e}")


def processar_pagina_interna(url_edital, ignorar_links, nome_portal, log, atualizar_tabela_func=None,
                             texto_pre_extraido="", links_extra=None):
    """
    Registra um edital novo no Supabase com status PENDENTE.

    texto_pre_extraido: texto já renderizado (portais SPA via Playwright).
    links_extra: lista de (href, rótulo) coletada pelo portal (SPA), para achar PDFs anexos.
    """
    try:
        url_edital = canonicalizar_url(url_edital)   # '#aba-x' e '#aba-y' são a mesma página

        if any(ign in url_edital.lower() for ign in ignorar_links):
            return False

        res_banco = config.supabase.table("editais").select("url").eq("url", url_edital).execute()
        if res_banco.data:
            return False

        log(f"        [+] Novo edital localizado: {url_edital}")

        fontes = []        # (tipo, origem, texto)
        pares_links = list(links_extra or [])

        # --- 1. Conteúdo principal (página ou PDF direto) ---
        if texto_pre_extraido:
            fontes.append(("PAGINA", url_edital, texto_pre_extraido))
        elif url_edital.lower().split("?")[0].endswith(".pdf"):
            fontes.append(("PDF", url_edital, extrair_texto_pdf_url(url_edital, log)))
        else:
            tipo, conteudo = baixar_pagina(url_edital, log)
            if tipo == "pdf":
                fontes.append(("PDF", url_edital, extrair_texto_pdf_bytes(conteudo, log)))
            elif tipo == "html":
                texto_pagina, pares = analisar_html(conteudo, url_edital)
                fontes.append(("PAGINA", url_edital, texto_pagina))
                pares_links += pares

        # --- 2. PDFs anexos (os mais relevantes, até MAX_PDFS_POR_EDITAL) ---
        candidatos = coletar_candidatos(pares_links, url_edital)
        candidatos = [c for c in candidatos if c["url"] != url_edital]
        escolhidos = selecionar_pdfs(candidatos, config.MAX_PDFS_POR_EDITAL)

        if candidatos:
            log(f"        [📎] {len(candidatos)} possíveis anexos; lendo {len(escolhidos)}.")
        for cand in escolhidos:
            texto_pdf = extrair_texto_pdf_url(cand["url"], log)
            if len(texto_pdf.strip()) >= 100:
                log(f"        [📎✓] Anexo lido ({len(texto_pdf)} chars): {cand['url']}")
                fontes.append(("PDF", cand["url"], texto_pdf))
            else:
                log(f"        [📎✗] Anexo sem texto aproveitável: {cand['url']}")
            time.sleep(0.5)

        texto_final = montar_texto_com_fontes(fontes, config.MAX_CHARS_TEXTO_BRUTO)

        # --- 3. Sem conteúdo suficiente (página + anexos): registra falha ---
        if tamanho_util(texto_final) < 100 or texto_parece_pagina_erro(texto_final):
            log("        [⚠️] Conteúdo vazio. Registrando falha para o retrabalho.")
            config.supabase.table("editais").insert({
                "url": url_edital, "portal": nome_portal, "titulo": "Edital Inválido",
                "palavra_chave": "Busca Ampla", "status_ia": "erro_sem_texto",
                "datas": "Texto não renderizado", "escopo": "Erro: Limitação de leitura.",
                "vigencia_projeto": "Não identificada", "prazo_iso": None,
                "texto_extracao": None,
            }).execute()
            return False

        _salvar_auditoria(url_edital, nome_portal, texto_final, log)

        config.supabase.table("editais").insert({
            "url": url_edital, "portal": nome_portal, "titulo": "Processando...",
            "palavra_chave": "Busca Ampla", "status_ia": "PENDENTE",
            "datas": "Processando...", "pesquisa": "Processando...",
            "escopo": "Processando...", "subvencao": "Processando...",
            "vigencia_projeto": "Processando...", "prazo_iso": None,
            "tags_ia": "Processando...",
            "texto_extracao": texto_final,
        }).execute()
        log(f"        [✓] Edital registrado no Supabase ({len(fontes)} fonte(s), {len(texto_final)} chars).")
        return True
    except Exception as e:
        log(f"        [X] Erro processamento ({url_edital}): {e}")
        return False