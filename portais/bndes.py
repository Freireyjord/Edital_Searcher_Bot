"""
Motor de Varredura Provisório: Portal do BNDES (Projetos em Andamento).
Lê a estrutura de links colapsáveis e despacha para a esteira do Supabase.
"""
import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from utils import scraper_utils as web_utils

NOME_PORTAL = "BNDES - Desestatização"
URL_REAL_BNDES = "https://www.bndes.gov.br/wps/portal/site/home/transparencia/desestatizacao/projetos-em-andamento"


def recuperar(page, url):
    """
    Função padrão exigida pelo core.ai_engine para retrabalho.
    Força a re-extração do texto de uma página interna caso o primeiro scraping falhe.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=35000)
        time.sleep(2.0)
        return page.evaluate("() => document.body.innerText")
    except Exception:
        return page.evaluate("() => document.body.innerText")


def varrer(log, atualizar_tabela_func=None, html_conteudo=None):
    """
    Ponto de entrada do orquestrador main_busca.py.
    
    html_conteudo: Parâmetro provisório para aceitar a string do HTML injetada 
                   diretamente a partir do seu arquivo .txt.
    """
    log(f"\n===> [INÍCIO] Iniciando varredura provisória no portal do BNDES")
    log(f"    [ALVO DE SINALIZAÇÃO] Referência: {URL_REAL_BNDES}")
    
    urls_validas = set()
    
    # 1. VALIDAÇÃO DA FONTE DE ENTRADA (Injeção de texto ou Requisição HTTP de fallback)
    if html_conteudo:
        log("    [HTML] Processando dados a partir do arquivo de auditoria .txt fornecido.")
        conteudo_html = html_conteudo
    else:
        log("    [HTTP] Nenhuma string manual injetada. Tentando requisição via Session...")
        try:
            from utils.http_utils import SESSAO
            resp = SESSAO.get(URL_REAL_BNDES, timeout=30)
            if resp.status_code == 200 and len(resp.text) > 500:
                conteudo_html = resp.text
            else:
                log(f"    [⚠️ ABORTADO] HTTP {resp.status_code} ou resposta vazia na requisição real.")
                return
        except Exception as e:
            log(f"    [❌ ERRO] Falha de comunicação direta com o BNDES: {e}")
            return

    # 2. MINERAÇÃO E EXTRAÇÃO DOS LINKS DE PROJETOS
    try:
        soup = BeautifulSoup(conteudo_html, "html.parser")
        
        # Mapeia os blocos colapsáveis que isolam as categorias de projetos
        blocos_projetos = soup.find_all("div", class_="colapsavel")
        
        for bloco in blocos_projetos:
            # Captura o título da categoria para log/auditoria contextual, se necessário
            header_categoria = bloco.find("div", class_="collapsible-header")
            nome_categoria = header_categoria.get_text(strip=True) if header_categoria else "Geral"
            
            # Localiza todas as âncoras de links que apontam para os editais/projetos
            links = bloco.find_all("a", href=True)
            for link in links:
                href = link["href"].strip()
                
                # Ignora links âncoras locais ou placeholders vazios
                if href.startswith("#") or not href:
                    continue
                
                # Reconstrói a URL completa usando a base oficial do Plone do BNDES
                url_completa = urljoin(URL_REAL_BNDES, href)
                urls_validas.add(url_completa)
                
    except Exception as e_parse:
        log(f"    [❌ PARSE ERRO] Falha ao analisar a árvore DOM do HTML: {e_parse}")
        return

    log(f"    [✓] Triagem concluída! Localizados {len(urls_validas)} links de projetos sob análise.")

    if not urls_validas:
        log("    [⚠️ ALERTA] Nenhum link ativo foi extraído da árvore de colapsáveis.")
        return

    # 3. DISPACHO DO LOTE PARA GRAVAÇÃO NO SUPABASE (Fila PENDENTE)
    for idx, url_projeto in enumerate(sorted(urls_validas), start=1):
        log(f"        [Fila {idx}/{len(urls_validas)}] Despachando edital do BNDES: {url_projeto}")
        
        # O utilitário checará duplicidades, extrairá o HTML interno/PDFs e salvará como PENDENTE
        web_utils.processar_pagina_interna(
            url_edital=url_projeto,
            ignorar_links=[],
            nome_portal=NOME_PORTAL,
            log=log,
            atualizar_tabela_func=None
        )
        
        # Delay regulamentar antibloqueio
        time.sleep(2.0)

    log(f"[✓] O motor integrado da '{NOME_PORTAL}' finalizou suas operações.")
