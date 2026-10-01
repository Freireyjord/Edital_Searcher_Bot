import os, json, time, requests
from datetime import datetime
from playwright.sync_api import sync_playwright
import config

# Motores de Contingência do Retrabalho
def rec_petrobras(page, url): page.goto(url, wait_until="networkidle"); return page.evaluate("() => document.body.innerText")
def rec_fundep(page, url): page.goto(url, wait_until="domcontentloaded"); return page.evaluate("() => document.body.innerText")
def rec_cnpq(page, url): page.goto(url, wait_until="domcontentloaded"); return page.evaluate("() => document.body.innerText")
def rec_finep(page, url): page.goto(url, wait_until="domcontentloaded"); return page.evaluate("() => document.body.innerText")

DICIONARIO_MOTORES_RECOVERY = {
    "Petrobras - Sigitec": rec_petrobras, "Fundep - Projetos": rec_fundep, "CNPq": rec_cnpq, "FINEP": rec_finep
}

def extrair_dados_com_ia(texto_analise, url_edital="N/A", nome_portal="Portal"):
    prompt_completo = f"{config.PROMPT_BASE_IA}\n\nTexto do Edital:\n{texto_analise}"
    
    # Log de auditoria
    try:
        pasta = os.path.join(config.DIRETORIO_PAI, "logs_auditoria")
        os.makedirs(pasta, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_limpo = "".join(c for c in nome_portal if c.isalnum() or c in (' ', '_', '-')).strip().replace(" ", "_")
        with open(os.path.join(pasta, f"{nome_limpo}_ia_prompt_{timestamp}.txt"), "w", encoding="utf-8") as f:
            f.write(f"URL: {url_edital}\n\n{prompt_completo}")
    except: pass

    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt_completo,
        "stream": False,
        "format": "json",
        "options": {
            "num_ctx": 16384  # Janela de contexto ampliada para ler editais longos na RTX 5070
        }
    }
    
    try:
        response = requests.post(config.OLLAMA_URL, json=payload, timeout=180)
        if response.status_code == 200:
            resposta_texto = response.json().get("response", "{}")
            return json.loads(resposta_texto)
        return {"erro": f"OLLAMA_HTTP_{response.status_code}"}
    except Exception as e:
        return {"erro": f"ERRO_CONEXAO_OLLAMA: {e}"}

def consumir_fila_pendente_ia(log_func, atualizar_tabela_func=None):
    try:
        hoje_str = datetime.now().date().isoformat()
        verificar_hoje = config.supabase.table("chaves_api").select("id").eq("ultima_renovacao", hoje_str).execute()
        
        if not verificar_hoje.data:
            log_func("    [🔄 Auto-Renovação] Reativando chaves para o novo dia...")
            todas = config.supabase.table("chaves_api").select("id").execute()
            for c in todas.data:
                config.supabase.table("chaves_api").update({"status": "ativa", "ultima_renovacao": hoje_str, "falhas_seguidas": 0}).eq("id", c["id"]).execute()
            
        lista_chaves_banco = config.supabase.table("chaves_api").select("*").eq("status", "ativa").order("id").execute().data
    except Exception as e_bd:
        log_func(f"    [X] Erro chaves: {e_bd}"); return "vazio"

    if not lista_chaves_banco: return "bloqueio_diario"

    itens_pendentes = config.supabase.table("editais").select("*").eq("status_ia", "PENDENTE").execute().data
    if not itens_pendentes: return "vazio"

    log_func(f"    [Esteira IA] Processando {len(itens_pendentes)} editais...")
    indice_chave_atual = 0
    
    for idx, edital in enumerate(itens_pendentes, start=1):
        texto_para_ia = edital.get("escopo", "") or edital.get("texto_extracao", "")
        if not texto_para_ia.strip() or texto_para_ia == "Processando...":
            config.supabase.table("editais").update({"status_ia": "erro_sem_texto", "escopo": "Erro: Texto indisponivel."}).eq("url", edital["url"]).execute()
            continue

        edital_processado_com_sucesso = False
        while indice_chave_atual < len(lista_chaves_banco):
            chave_obj = lista_chaves_banco[indice_chave_atual]
            
            for tentativa in range(1, 4):
                resultado_ia = extrair_dados_com_ia(texto_para_ia, chave_obj["chave"], edital['url'], edital['portal'])
                if "erro" not in resultado_ia: edital_processado_com_sucesso = True; break
                err_msg = str(resultado_ia["erro"]).upper()
                if "503" in err_msg or "HIGH DEMAND" in err_msg: time.sleep(20)
                else: break
            
            if edital_processado_com_sucesso: break
            
            if "RESOURCE_EXHAUSTED" in err_msg or "QUOTA" in err_msg or "429" in err_msg:
                config.supabase.table("chaves_api").update({"status": "esgotada"}).eq("id", chave_obj["id"]).execute()
            indice_chave_atual += 1

        if not edital_processado_com_sucesso: return "bloqueio_diario"

        # --- NOVA ESTEIRA DE ANÁLISE DE STATUS DA IA LOCAL ---
        status_projeto_ia = str(resultado_ia.get("status_projeto", "")).strip().upper()
        
        # Cenário 1: Descartes Críticos (Encerrados, Erros de Página ou Páginas Institucionais)
        if status_projeto_ia in ["ENCERRADO", "PAGINA_ERRO", "NAO_EDITAL"]:
            motivo_log = {
                "ENCERRADO": "Inscrições encerradas/vencidas",
                "PAGINA_ERRO": "Erro HTTP ou falha de carregamento no portal",
                "NAO_EDITAL": "Página institucional ou manual administrativo (Não edital)"
            }.get(status_projeto_ia, "Critério de descarte automático")
            
            config.supabase.table("editais").update({
                "titulo": resultado_ia.get("titulo") or f"Descartado ({status_projeto_ia})",
                "datas": "Descartado",
                "status_ia": "descartado_vencido",
                "escopo": f"Edital movido para lixeira automatizada por motivo de: {motivo_log}."
            }).eq("url", edital["url"]).execute()
            
            log_func(f"    [🗑️ DESCARTE IA] URL limpa da fila ({status_projeto_ia}): {edital['url']}")
            continue

        # Cenário 2: Falha Crítica de Informações (Texto vazio/incompleto para mapeamento)
        elif status_projeto_ia == "N/A INFO":
            config.supabase.table("editais").update({
                "status_ia": "erro_sem_texto",
                "escopo": "Erro: A IA leu o conteúdo, mas não localizou escopo ou linhas de pesquisa válidas."
            }).eq("url", edital["url"]).execute()
            
            log_func(f"    [⚠️ ALERTA IA] Edital marcado com erro de leitura (N/A INFO): {edital['url']}")
            continue

        # Cenário 3: Validação de Calendário (Segunda Camada de Segurança para ATIVO e ATEMPORAL)
        prazo_iso = resultado_ia.get("prazo_iso") or ""
        fim_projeto_iso = resultado_ia.get("fim_projeto_iso") or ""
        data_corte = prazo_iso if (prazo_iso and "não" not in str(prazo_iso).lower()) else fim_projeto_iso
        
        if data_corte and "9999" not in data_corte:
            try:
                if datetime.strptime(data_corte.strip(), "%Y-%m-%d").date() < datetime.now().date():
                    config.supabase.table("editais").update({
                        "datas": "Expirado", 
                        "status_ia": "descartado_vencido",
                        "escopo": "Edital descartado retroativamente pela checagem de calendário (data_corte retroativa)."
                    }).eq("url", edital["url"]).execute()
                    log_func(f"    [⏳ DESCARTE DATA] Edital vencido no calendário cronológico: {edital['url']}")
                    continue
            except: pass

        # Cenário 4: Registro Aprovado com Sucesso (Status ATIVO ou ATEMPORAL)
        # Força um fallback caso a data seja atemporal
        prazo_iso_final = prazo_iso if (prazo_iso and "não" not in str(prazo_iso).lower()) else (fim_projeto_iso if fim_projeto_iso else "9999-12-31 23:59")
        if status_projeto_ia == "ATEMPORAL":
            prazo_iso_final = "9999-12-31 23:59"

        config.supabase.table("editais").update({
            "titulo": resultado_ia.get("titulo") or "Edital sem título",
            "datas": resultado_ia.get("datas") or "A consultar",
            "pesquisa": resultado_ia.get("pesquisa") or "Não encontrada",
            "subvencao": resultado_ia.get("subvencao") or "Não encontrada",
            "escopo": resultado_ia.get("escopo") or "Não encontrado",
            "prazo_iso": prazo_iso_final,
            "vigencia_projeto": resultado_ia.get("vigencia_projeto") or "Não encontrada",
            "tags_ia": resultado_ia.get("tags_ia") or "Geral", 
            "status_ia": "CONCLUIDO"
        }).eq("url", edital["url"]).execute()
        
        log_func(f"    [✓ APROVADO] Edital processado com sucesso como {status_projeto_ia}: {resultado_ia.get('titulo')}")
        if idx < len(itens_pendentes): time.sleep(4)
        
    return "sucesso"

def executar_retrabalho_editais_com_erro(log_func):
    try:
        itens_com_erro = config.supabase.table("editais").select("*").eq("status_ia", "erro_sem_texto").execute().data
    except:
        return

    if not itens_com_erro: return

    with sync_playwright() as p_retro:
        browser = p_retro.chromium.launch(headless=True, args=["--headless=shell"])
        page = browser.new_context(user_agent="Mozilla/5.0", locale="pt-BR").new_page()
        
        for edital in itens_com_erro:
            func = DICIONARIO_MOTORES_RECOVERY.get(edital["portal"])
            if not func: continue
            
            try:
                txt = func(page, edital["url"])
                if txt and len(txt.strip()) >= 100:
                    res = extrair_dados_com_ia(txt, edital["url"], edital["portal"])
                    if "erro" not in res:
                        config.supabase.table("editais").update({
                            "titulo": res.get("titulo") or "Recuperado", "datas": res.get("datas") or "A consultar",
                            "pesquisa": res.get("pesquisa") or "N/A", "subvencao": res.get("subvencao") or "N/A",
                            "escopo": res.get("escopo") or "N/A", "prazo_iso": res.get("prazo_iso") or "9999-12-31 23:59",
                            "tags_ia": res.get("tags_ia") or "Geral", "status_ia": "CONCLUIDO"
                        }).eq("url", edital["url"]).execute()
            except: pass
            time.sleep(2)
        browser.close()
