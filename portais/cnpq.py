import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from utils import scraper_utils as web_utils

NOME_PORTAL = "CNPq - Chamadas Abertas"
URL_REAL_CNPQ = "https://www.gov.br/cnpq/pt-br/chamadas/abertas-para-submissao"

def varrer(log, atualizar_tabela_func=None):
    log(f"\n===> [INÍCIO REAL] Iniciando varredura filtrada e otimizada no CNPq")
    log(f"    [DOMÍNIO SEGURO] Alvo fixado exclusivamente em: {URL_REAL_CNPQ}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.gov.br/cnpq/pt-br/chamadas/abertas-para-submissao"
    }
    
    urls_validas = set()
    
    try:
        inicio_req = time.time()
        # Faz a requisição única para ler a página do CNPq
        resp = requests.get(URL_REAL_CNPQ, headers=headers, timeout=30)
        fim_req = time.time()
        
        log(f"    [HTTP API] Status: {resp.status_code} | Tamanho da Base: {len(resp.text)} caracteres | Tempo: {fim_req - inicio_req:.2f}s")
        
        if resp.status_code != 200 or len(resp.text) < 500:
            log("    [⚠️ CRÍTICO] O portal retornou uma página inválida ou vazia.")
            return
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # MINERAÇÃO CIRÚRGICA: Busca apenas os títulos das chamadas
        titulos_chamadas = soup.find_all("h2", class_="headline")
        
        for titulo in titulos_chamadas:
            link = titulo.find("a", href=True)
            if link:
                href = link["href"]
                
                # Garante que não é um link vazio ou a própria página principal
                if href.strip("/") == URL_REAL_CNPQ.strip("/") or href.startswith("#"):
                    continue
                
                # Reconstrói se for link relativo (padrão de segurança)
                url_completa = urljoin(URL_REAL_CNPQ, href)
                urls_validas.add(url_completa)
                
    except Exception as e:
        log(f"    [X] Erro crítico de comunicação com o portal: {e}")
        return

    log(f"\n    [✓] Triagem concluída! Extraídos com sucesso: {len(urls_validas)} editais únicos do CNPq.")

    if len(urls_validas) == 0:
        log("    [⚠️ CRÍTICO] Falha na mineração. Nenhum edital foi localizado na estrutura alvo.")
        return

    # Despacha a fila purificada e sem duplicados
    for idx, url_edital in enumerate(urls_validas, start=1):
        log(f"        [Fila {idx}/{len(urls_validas)}] Despachando para processamento: {url_edital}")
        
        web_utils.processar_pagina_interna(
            url_edital, [], NOME_PORTAL, log, None
        )
        time.sleep(2.5)

        
    log(f"[✓] O motor da {NOME_PORTAL} finalizou com sucesso!")
