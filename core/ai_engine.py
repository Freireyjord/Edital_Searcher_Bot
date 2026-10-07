import os, json, time, requests, importlib, pkgutil
from datetime import datetime
from playwright.sync_api import sync_playwright
import config
import portais


# ---------------------------------------------------------------------------
# Motores de contingência (retrabalho) — montados dinamicamente
# ---------------------------------------------------------------------------
def recuperar_generico(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    return page.evaluate("() => document.body.innerText")


def montar_motores_recovery(log_func=None):
    """
    Descobre os módulos em portais/ e mapeia NOME_PORTAL -> função de recuperação.
    Se o módulo exporta `recuperar(page, url)`, usa essa; senão, o extrator genérico.
    Assim o nome salvo no banco e a chave do dicionário nunca ficam dessincronizados.
    """
    motores = {}
    for info in pkgutil.iter_modules(portais.__path__):
        try:
            modulo = importlib.import_module(f"portais.{info.name}")
        except Exception as e:
            if log_func:
                log_func(f"    [⚠️] Não foi possível carregar portais.{info.name}: {e}")
            continue
        nome = getattr(modulo, "NOME_PORTAL", None)
        if nome:
            motores[nome] = getattr(modulo, "recuperar", recuperar_generico)
    return motores


# ---------------------------------------------------------------------------
# IA local (Ollama)
# ---------------------------------------------------------------------------
def extrair_dados_com_ia(texto_analise, url_edital="N/A", nome_portal="Portal"):
    prompt_completo = f"{config.PROMPT_BASE_IA}\n\nTexto do Edital:\n{texto_analise}"

    try:
        pasta = os.path.join(config.DIRETORIO_PAI, "logs_auditoria")
        os.makedirs(pasta, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_limpo = "".join(c for c in nome_portal if c.isalnum() or c in (' ', '_', '-')).strip().replace(" ", "_")
        with open(os.path.join(pasta, f"{nome_limpo}_ia_prompt_{timestamp}.txt"), "w", encoding="utf-8") as f:
            f.write(f"URL: {url_edital}\n\n{prompt_completo}")
    except Exception:
        pass

    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt_completo,
        "stream": False,
        "format": "json",
        "options": {"num_ctx": 16384}
    }

    try:
        response = requests.post(config.OLLAMA_URL, json=payload, timeout=180)
        if response.status_code == 200:
            res_json = response.json()

            eval_count = res_json.get("eval_count", 0)
            eval_duration_ns = res_json.get("eval_duration", 0)
            prompt_eval_count = res_json.get("prompt_eval_count", 0)

            if eval_duration_ns > 0:
                eval_duration_s = eval_duration_ns / 1e9
                tps = eval_count / eval_duration_s
                print(f"      [⚡ Ollama Metrics] Contexto: {prompt_eval_count} tokens | Saída: {eval_count} tokens | Velocidade: {tps:.2f} t/s ({eval_duration_s:.2f}s)")

            resposta_texto = res_json.get("response", "{}")
            return json.loads(resposta_texto)
        return {"erro": f"OLLAMA_HTTP_{response.status_code}"}
    except Exception as e:
        return {"erro": f"ERRO_CONEXAO_OLLAMA: {e}"}


# ---------------------------------------------------------------------------
# Esteira principal
# ---------------------------------------------------------------------------
def _texto_do_edital(edital):
    """
    Fonte do texto bruto: texto_extracao (novo padrão).
    Fallback para 'escopo' apenas em registros antigos (antes da correção),
    ignorando placeholders.
    """
    texto = (edital.get("texto_extracao") or "").strip()
    if texto:
        return texto

    legado = (edital.get("escopo") or "").strip()
    if legado and legado != "Processando..." and not legado.startswith("Erro:"):
        return legado
    return ""


def consumir_fila_pendente_ia(log_func, atualizar_tabela_func=None):
    try:
        itens_pendentes = config.supabase.table("editais").select("*").in_("status_ia", ["PENDENTE", "erro_sem_texto"]).execute().data
    except Exception as e_bd:
        log_func(f"    [X] Erro ao consultar banco: {e_bd}")
        return "erro"

    if not itens_pendentes:
        return "vazio"

    log_func(f"    [Esteira IA Local] Processando {len(itens_pendentes)} editais via Ollama...")

    for idx, edital in enumerate(itens_pendentes, start=1):
        texto_para_ia = _texto_do_edital(edital)

        if len(texto_para_ia) < 100:
            log_func(f"    [⚠️] Texto ausente para o edital ({edital['url']}). Enviando para recuperação...")
            config.supabase.table("editais").update({"status_ia": "erro_sem_texto"}).eq("url", edital["url"]).execute()
            continue

        log_func(f"    [Ollama] Analisando edital ({idx}/{len(itens_pendentes)}): {edital['url']}")
        resultado_ia = extrair_dados_com_ia(texto_para_ia, edital['url'], edital['portal'])

        if "erro" in resultado_ia:
            log_func(f"    [⚠️] Falha de leitura local ({edital['url']}): {resultado_ia['erro']}")
            continue

        prazo_iso = resultado_ia.get("prazo_iso") or ""
        fim_projeto_iso = resultado_ia.get("fim_projeto_iso") or ""
        data_corte = prazo_iso if (prazo_iso and "não" not in str(prazo_iso).lower()) else fim_projeto_iso

        if data_corte and "9999" not in data_corte:
            try:
                if datetime.strptime(data_corte.strip(), "%Y-%m-%d").date() < datetime.now().date():
                    config.supabase.table("editais").update({"datas": "Expirado", "status_ia": "descartado_vencido"}).eq("url", edital["url"]).execute()
                    continue
            except Exception:
                pass

        config.supabase.table("editais").update({
            "titulo": resultado_ia.get("titulo") or "Edital sem título",
            "datas": resultado_ia.get("datas") or "A consultar",
            "pesquisa": resultado_ia.get("pesquisa") or "Não encontrada",
            "subvencao": resultado_ia.get("subvencao") or "Não encontrada",
            "escopo": resultado_ia.get("escopo") or "Não encontrado",   # agora é só o resumo; o bruto fica em texto_extracao
            "prazo_iso": prazo_iso if (prazo_iso and "não" not in str(prazo_iso).lower()) else (fim_projeto_iso if fim_projeto_iso else "9999-12-31 23:59"),
            "vigencia_projeto": resultado_ia.get("vigencia_projeto") or "Não encontrada",
            "tags_ia": resultado_ia.get("tags_ia") or "Geral",
            "status_ia": "CONCLUIDO"
        }).eq("url", edital["url"]).execute()

    return "sucesso"


def executar_retrabalho_editais_com_erro(log_func):
    try:
        itens_com_erro = config.supabase.table("editais").select("*").eq("status_ia", "erro_sem_texto").execute().data
    except Exception:
        return

    if not itens_com_erro:
        return

    motores = montar_motores_recovery(log_func)
    log_func(f"    [Retrabalho] Tentando raspar novamente {len(itens_com_erro)} editais sem texto...")

    with sync_playwright() as p_retro:
        browser = p_retro.chromium.launch(headless=True, args=["--headless=shell"])
        page = browser.new_context(user_agent="Mozilla/5.0", locale="pt-BR").new_page()

        for edital in itens_com_erro:
            func = motores.get(edital["portal"])
            if not func:
                log_func(f"    [⚠️] Sem motor de recuperação para o portal '{edital['portal']}'.")
                continue

            try:
                txt = func(page, edital["url"])
                if txt and len(txt.strip()) >= 100:
                    res = extrair_dados_com_ia(txt, edital["url"], edital["portal"])
                    if "erro" not in res:
                        config.supabase.table("editais").update({
                            "texto_extracao": txt,
                            "titulo": res.get("titulo") or "Recuperado",
                            "datas": res.get("datas") or "A consultar",
                            "pesquisa": res.get("pesquisa") or "N/A",
                            "subvencao": res.get("subvencao") or "N/A",
                            "escopo": res.get("escopo") or "N/A",
                            "vigencia_projeto": res.get("vigencia_projeto") or "Não encontrada",
                            "prazo_iso": res.get("prazo_iso") or "9999-12-31 23:59",
                            "tags_ia": res.get("tags_ia") or "Geral",
                            "status_ia": "CONCLUIDO"
                        }).eq("url", edital["url"]).execute()
            except Exception as e:
                log_func(f"    [X] Falha no retrabalho ({edital['url']}): {e}")
            time.sleep(2)
        browser.close()