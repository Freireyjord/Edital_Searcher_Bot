import re, os, requests
from bs4 import BeautifulSoup
from datetime import datetime
import config
from utils.document_utils import extrair_texto_pdf_miner

def limpar_texto_extraido(texto):
    if not texto: return ""
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'[\r\n]+', '\n', texto)
    linhas = [linha.strip() for linha in texto.split('\n') if linha.strip()]
    return '\n'.join(linhas)

def extrair_texto_html(url_html, log):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url_html, headers=headers, timeout=20)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for s in soup(["script", "style", "nav", "footer", "header"]):
                s.decompose()
            return soup.get_text(separator=" ", strip=True)
    except Exception as e:
        log(f"        [⚠️] Erro ao extrair HTML ({url_html}): {e}")
    return ""

def processar_pagina_interna(url_edital, ignorar_links, nome_portal, log, atualizar_tabela_func=None, texto_pre_extraido=""):
    try:
        if any(ign in url_edital.lower() for ign in ignorar_links): return False

        res_banco = config.supabase.table("editais").select("url").eq("url", url_edital).execute()
        if res_banco.data and len(res_banco.data) > 0:
            return False

        log(f"        [+] Novo edital localizado: {url_edital}")
        
        if texto_pre_extraido:
            texto_bruto = texto_pre_extraido
        else:
            if url_edital.lower().endswith(".pdf"):
                texto_bruto = extrair_texto_pdf_miner(url_edital, log)
            else:
                texto_bruto = extrair_texto_html(url_edital, log)

        texto_limpo = limpar_texto_extraido(texto_bruto)

        if not texto_limpo.strip() or len(texto_limpo.strip()) < 100:
            log(f"        [⚠️] Conteúdo vazio. Registrando falha para evitar re-busca.")
            dados_erro = {
                "url": url_edital, "portal": nome_portal, "titulo": "Edital Inválido",
                "palavra_chave": "Busca Ampla", "status_ia": "erro_sem_texto", 
                "datas": "Texto não renderizado", "escopo": "Erro: Limitação de leitura.", 
                "vigencia_projeto": "Não identificada", "prazo_iso": "9999-12-31 23:59"
            }
            config.supabase.table("editais").insert(dados_erro).execute()
            return False

        try:
            pasta_auditoria = os.path.join(config.DIRETORIO_PAI, "logs_auditoria")
            os.makedirs(pasta_auditoria, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome_portal_limpo = "".join(c for c in nome_portal if c.isalnum() or c in (' ', '_', '-')).strip().replace(" ", "_")
            with open(os.path.join(pasta_auditoria, f"{nome_portal_limpo}_raw_texto_{timestamp}.txt"), "w", encoding="utf-8") as f_audit:
                f_audit.write(f"URL: {url_edital}\nPORTAL: {nome_portal}\n\n{texto_limpo}")
        except Exception as e_txt:
            log(f"        [⚠️] Falha ao salvar auditoria: {e_txt}")

        if len(texto_limpo) > 25000:
            texto_final = f"{texto_limpo[:15000]}\n\n[... SUCINTADO ...]\n\n{texto_limpo[-10000:]}"
        else:
            texto_final = texto_limpo

        dados_edital = {
            "url": url_edital, "portal": nome_portal, "titulo": "Processando...", "palavra_chave": "Busca Ampla",
            "status_ia": "PENDENTE", "datas": "Processando...", "pesquisa": "Processando...",
            "escopo": texto_final, "subvencao": "Processando...", "vigencia_projeto": "Processando...",
            "prazo_iso": None, "tags_ia": "Processando..."     
        }
        config.supabase.table("editais").insert(dados_edital).execute()
        log(f"        [✓] Edital registrado no Supabase.")
        return True
    except Exception as e:
        log(f"        [X] Erro processamento ({url_edital}): {e}")
        return False
