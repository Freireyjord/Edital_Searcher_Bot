import time
import requests
import re

from utils import scraper_utils as web_utils

NOME_PORTAL = "Fundep - Projetos"
URL_REAL_FUNDEP = "https://fundep.ufmg.br/projetos"

def varrer(log, atualizar_tabela_func=None):
    log(f"\n===> [INÍCIO REAL] Iniciando varredura profunda e otimizada (Single-Request) na Fundep")
    log(f"    [DOMÍNIO SEGURO] Alvo fixado exclusivamente em: {URL_REAL_FUNDEP}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://fundep.ufmg.br/"
    }
    
    urls_validas = set()
    
    try:
        inicio_req = time.time()
        # Faz uma única chamada na URL principal que carrega os 340KB de dados completos
        resp = requests.get(URL_REAL_FUNDEP, headers=headers, timeout=30)
        fim_req = time.time()
        
        log(f"    [HTTP API] Status: {resp.status_code} | Tamanho da Base: {len(resp.text)} caracteres | Tempo: {fim_req - inicio_req:.2f}s")
        
        if resp.status_code != 200 or len(resp.text) < 500:
            log("    [⚠️ CRÍTICO] O portal retornou uma página inválida ou vazia.")
            return
            
        conteudo_dados = resp.text
        
        # ESTRATÉGIA DE EXTRAÇÃO DUPLA (HTML + JSON INTERNO DO NEXT.JS)
        # 1. Captura os IDs que estão em links HTML tradicionais: /projetos/17
        ids_via_link = re.findall(r'/projetos/(\d+)', conteudo_dados)
        
        # 2. Captura os IDs que estão escondidos no JSON de estado do Next.js: "id":46 ou \"id\":32
        ids_via_json = re.findall(r'(?:\\"id\\"|\\?"id\\?"):(\d+)', conteudo_dados)
        
        # Une todas as capturas em uma lista única para filtragem
        todos_os_ids = ids_via_link + ids_via_json
        
        for id_projeto in todos_os_ids:
            # Filtro de segurança para ignorar lixos de renderização ou IDs falsos
            if id_projeto == "0" or len(id_projeto) > 4:
                continue
                
            url_completa = f"https://fundep.ufmg.br/projetos/{id_projeto}"
            urls_validas.add(url_completa)
            
    except Exception as e:
        log(f"    [X] Erro crítico de comunicação com o portal: {e}")
        return

    log(f"\n    [✓] Triagem concluída! Extraídos com sucesso: {len(urls_validas)} editais únicos das 8 páginas integradas.")

    if len(urls_validas) == 0:
        log("    [⚠️ CRÍTICO] Falha na mineração. Nenhum edital foi localizado nos barramentos do Next.js.")
        return

    # Despacha a fila completa purificada para o Supabase via web_utils
    for idx, url_edital in enumerate(urls_validas, start=1):
        log(f"        [Fila {idx}/{len(urls_validas)}] Despachando para processamento: {url_edital}")
        
        web_utils.processar_pagina_interna(
            url_edital, [], NOME_PORTAL, log, None
        )
        time.sleep(2.0)

        
    log(f"[✓] O motor da {NOME_PORTAL} processou e salvou todos os registros com sucesso!")
