"""
Relatório semanal de editais.

- Agendado (padrão: toda segunda às 07:00, horário da máquina). Roda numa thread PRÓPRIA
  (iniciar_agendador_relatorio), independente do ciclo de scraping/IA de 2 em 2 horas:
  um ciclo longo nunca atrasa nem pula o relatório.
- Envio em paralelo para todos os assinantes pendentes (cada um com seu próprio conteúdo/filtro).
- Cada relatório traz os editais INICIADOS em [segunda anterior, segunda do slot) (`inicio_edital`).
  Edital sem data de início identificada entra como "recente": vale o momento em que ficou
  CONCLUIDO (`concluido_em`) dentro da mesma janela. Cada edital cai em exatamente uma semana.
- `ultima_semana_enviada` controla a agenda; `ultimo_envio` fica só como histórico.
  (O envio manual da UI não mexe na agenda.)
"""
import html
import smtplib
import threading
import time
import traceback
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from supabase import create_client

import config
from core.agenda_relatorio import (
    classificar_assinante, descrever_slot, janela_do_relatorio,
    momento_agendado_atual, proximo_momento,
)

# Colunas usadas no e-mail. Nunca select("*"): texto_extracao guarda o texto bruto de editais e PDFs.
COLUNAS_RELATORIO = "titulo,portal,datas,vigencia_projeto,subvencao,tags_ia,escopo,url,inicio_edital"
TAMANHO_PAGINA = 1000

# Estado em memória (por processo): evita reenvio em loop se a gravação no banco falhar
# e limita tentativas de quem está com SMTP falhando.
_ESTADO = {"falhas": {}, "enviados": set()}


def _e(valor):
    """Escapa texto vindo do banco/IA/sites raspados antes de entrar no HTML do e-mail."""
    return html.escape("" if valor is None else str(valor))


def _url_segura(url):
    """Só links http(s); qualquer outra coisa vira '#'."""
    url = str(url or "").strip()
    return html.escape(url, quote=True) if url.lower().startswith(("http://", "https://")) else "#"


def normalizar_texto_report(texto):
    if not texto:
        return ""
    texto = str(texto).strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')


def criar_cliente():
    """Cliente Supabase exclusivo do agendador (a thread não compartilha conexão com o ciclo principal)."""
    return create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


def _proximo_slot(agora):
    return proximo_momento(agora, config.REPORT_DIA_SEMANA, config.REPORT_HORA, config.REPORT_MINUTO)


# ---------------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------------
def _utc_iso(momento):
    """datetime local ingênuo -> ISO em UTC (concluido_em é timestamptz)."""
    return momento.astimezone(timezone.utc).isoformat()


def _paginar(cliente, aplicar):
    """Consulta paginada de editais CONCLUIDOS; `aplicar(query)` acrescenta os filtros do grupo."""
    itens, de = [], 0
    while True:
        consulta = cliente.table("editais").select(COLUNAS_RELATORIO).eq("status_ia", "CONCLUIDO")
        resposta = aplicar(consulta).order("url").range(de, de + TAMANHO_PAGINA - 1).execute()
        lote = resposta.data or []
        itens.extend(lote)
        if len(lote) < TAMANHO_PAGINA:
            return itens
        de += TAMANHO_PAGINA


def _buscar_editais_da_janela(cliente, inicio, fim, tolerancia_dias=0):
    """
    Editais "recentes" da janela [inicio, fim), em UMA rodada para todos os assinantes:
      A) data de início conhecida e dentro da janela (comparada por DATA);
      B) SEM data de início: vale o momento em que ficou CONCLUIDO (entra como se fosse recente);
      C) (opcional) iniciados até `tolerancia_dias` antes da janela e só descobertos dentro dela.
    Os grupos são disjuntos; a união é deduplicada por URL.
    """
    d_ini, d_fim = inicio.date().isoformat(), fim.date().isoformat()
    ts_ini, ts_fim = _utc_iso(inicio), _utc_iso(fim)

    grupos = [
        _paginar(cliente, lambda q: q.gte("inicio_edital", d_ini).lt("inicio_edital", d_fim)),
        _paginar(cliente, lambda q: q.is_("inicio_edital", "null").gte("concluido_em", ts_ini).lt("concluido_em", ts_fim)),
    ]
    if tolerancia_dias > 0:
        d_tol = (inicio.date() - timedelta(days=tolerancia_dias)).isoformat()
        grupos.append(_paginar(
            cliente,
            lambda q: q.gte("inicio_edital", d_tol).lt("inicio_edital", d_ini)
                       .gte("concluido_em", ts_ini).lt("concluido_em", ts_fim),
        ))

    por_url = {}
    for grupo in grupos:
        for edital in grupo:
            por_url.setdefault(edital.get("url"), edital)
    # Início mais recente primeiro; os sem data de início (entraram como "recentes") por último
    return sorted(por_url.values(), key=lambda e: e.get("inicio_edital") or "", reverse=True)


def _filtrar_editais(editais, deve_filtrar, tags_brutas):
    termos = [normalizar_texto_report(t) for t in (tags_brutas or "").split(",") if t.strip()]
    if not (deve_filtrar and termos):
        return list(editais)

    resultado = []
    for edital in editais:
        tags_ia = [normalizar_texto_report(t) for t in (edital.get("tags_ia") or "").split(",") if t.strip()]
        titulo = normalizar_texto_report(edital.get("titulo", ""))
        for termo in termos:
            if termo in titulo or any(termo in tag or tag in termo for tag in tags_ia):
                resultado.append(edital)
                break
    return resultado


# ---------------------------------------------------------------------------
# E-mail
# ---------------------------------------------------------------------------
def _fmt_inicio(item):
    """'2026-10-14' -> '14/10/2026'; sem data -> aviso de que entrou como edital novo na base."""
    bruto = str(item.get("inicio_edital") or "")[:10]
    try:
        return datetime.strptime(bruto, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return "não identificado*"


def _montar_html(editais, inicio, fim, gerado_em):
    corpo = f"""
        <html><head><style>
            body {{ font-family: Arial, sans-serif; margin:0; padding:20px; color:#333; background-color:#f8f9fa; }}
            .container {{ max-width:800px; margin:0 auto; background:#fff; padding:30px; border:1px solid #e2e8f0; }}
            .header {{ border-bottom:3px solid #1f6aa5; padding-bottom:15px; margin-bottom:25px; }}
            .header h2 {{ color:#1f6aa5; margin:0; font-size:22px; }}
            .card {{ border:1px solid #e2e8f0; border-left:5px solid #27ae60; padding:15px; margin-bottom:20px; background:#fafbfc; }}
            .card h3 {{ margin:0 0 10px 0; font-size:16px; color:#2d3748; }}
            .meta {{ font-size:12px; color:#4a5568; margin-bottom:10px; line-height:1.6; }}
            .escopo {{ font-size:13px; color:#4a5568; text-align:justify; line-height:1.5; background:#fff; padding:10px; border:1px solid #edf2f7; }}
            .btn-link {{ display:inline-block; background-color:#1f6aa5; color:#ffffff !important; text-decoration:none; padding:6px 12px; font-size:12px; font-weight:bold; margin-top:10px; }}
            .footer {{ font-size:11px; color:#a0aec0; text-align:center; margin-top:30px; border-top:1px solid #e2e8f0; padding-top:15px; }}
        </style></head><body>
            <div class="container">
                <div class="header">
                    <h2>RELATÓRIO SEMANAL DE NOVOS EDITAIS</h2>
                    <p>Editais iniciados de {inicio.strftime('%d/%m')} a {(fim - timedelta(days=1)).strftime('%d/%m/%Y')} — Gerado em {gerado_em.strftime('%d/%m/%Y às %H:%M')}</p>
                </div>
    """
    for item in editais:
        corpo += f"""
                <div class="card">
                    <h3>{_e(item.get('titulo') or 'Edital sem título')}</h3>
                    <div class="meta">
                        <strong>Portal:</strong> {_e(item.get('portal') or 'N/A')} | <strong>Início:</strong> {_fmt_inicio(item)} | <strong>Prazo:</strong> {_e(item.get('datas') or 'A consultar')}<br>
                        <strong>Vigência:</strong> {_e(item.get('vigencia_projeto') or 'N/A')} | <strong>Verba:</strong> {_e(item.get('subvencao') or 'N/A')}<br>
                        <strong>Tags:</strong> <i>{_e(item.get('tags_ia') or 'Geral')}</i>
                    </div>
                    <div class="escopo"><strong>Resumo:</strong> {_e(item.get('escopo') or 'Sem resumo.')}</div>
                    <a href="{_url_segura(item.get('url'))}" class="btn-link" target="_blank">VISUALIZAR EDITAL FONTE</a>
                </div>
        """
    if any(not item.get("inicio_edital") for item in editais):
        corpo += ('<div class="footer">* Editais sem data de início identificada foram incluídos '
                  'por terem entrado na base nesta semana.</div>')
    corpo += "</div></body></html>"
    return corpo


def _enviar_email(destino, assunto, corpo_html):
    """Envia 1 e-mail (roda dentro de uma thread do pool). Retorna None se OK, ou a mensagem de erro."""
    erro = None
    for tentativa in (1, 2):
        try:
            msg = MIMEMultipart()
            msg['From'] = config.SMTP_REMETENTE
            msg['To'] = destino
            msg['Subject'] = assunto
            msg.attach(MIMEText(corpo_html, 'html', 'utf-8'))
            with smtplib.SMTP(config.SMTP_SERVIDOR, config.SMTP_PORTA, timeout=30) as servidor:
                servidor.sendmail(config.SMTP_REMETENTE, destino, msg.as_string())
            return None
        except Exception as e:
            erro = e
            if tentativa == 1:
                time.sleep(2)
    return str(erro)


# ---------------------------------------------------------------------------
# Rotina principal (idempotente: pode ser chamada a cada poucos segundos)
# ---------------------------------------------------------------------------
def executar_relatorio_semanal(log_func, cliente=None, agora=None, estado=None):
    """
    Envia o relatório do slot vigente a todos os assinantes que ainda não o receberam.
    Silenciosa quando não há nada a fazer. Retorna um resumo (dict).
    """
    estado = estado if estado is not None else _ESTADO
    agora = agora or datetime.now()
    cliente = cliente or criar_cliente()
    resumo = {"enviados": 0, "falhas": 0, "sem_conteudo": 0, "novos": 0}

    slot = momento_agendado_atual(agora, config.REPORT_DIA_SEMANA, config.REPORT_HORA, config.REPORT_MINUTO)
    inicio, fim = janela_do_relatorio(slot)
    slot_data = slot.date().isoformat()

    assinantes = cliente.table("configuracoes_relatorio").select(
        "id,email_destino,filtrar_por_tags,tags_exclusivas,ultima_semana_enviada"
    ).execute().data or []

    novos, pendentes = [], []
    for perfil in assinantes:
        id_reg = perfil.get("id")
        classe = classificar_assinante(perfil.get("ultima_semana_enviada"), slot)

        if classe == "novo":
            novos.append(id_reg)
            continue
        if classe != "pendente" or (id_reg, slot_data) in estado["enviados"]:
            continue
        if not (perfil.get("email_destino") or "").strip():
            continue

        falha = estado["falhas"].get((id_reg, slot_data))
        if falha and (falha["tentativas"] >= config.REPORT_MAX_TENTATIVAS
                      or (agora - falha["ultima"]).total_seconds() < config.REPORT_COOLDOWN_SEGUNDOS):
            continue
        pendentes.append(perfil)

    # Assinante que ainda não estava na agenda: entra agora, sem receber relatório de janela antiga.
    if novos:
        cliente.table("configuracoes_relatorio").update({"ultima_semana_enviada": slot_data}).in_("id", novos).execute()
        resumo["novos"] = len(novos)
        log_func(f"    [📅 RELATÓRIO] {len(novos)} assinante(s) incluído(s) na agenda; recebem a partir do próximo slot.")

    if not pendentes:
        return resumo

    log_func(f"    [📅 RELATÓRIO] Slot {descrever_slot(slot)}: {len(pendentes)} assinante(s) pendente(s). "
             f"Início entre {inicio:%d/%m} e {(fim - timedelta(days=1)):%d/%m}.")

    editais = _buscar_editais_da_janela(cliente, inicio, fim, config.REPORT_TOLERANCIA_DESCOBERTA_DIAS)   # 1 rodada p/ todos
    sem_inicio = sum(1 for e in editais if not e.get("inicio_edital"))
    log_func(f"    [📅 RELATÓRIO] {len(editais)} edital(is) iniciado(s) na janela "
             f"({sem_inicio} sem data de início, incluídos como recentes).")

    jobs, sem_conteudo = [], []
    for perfil in pendentes:
        selecionados = _filtrar_editais(editais, perfil.get("filtrar_por_tags", False), perfil.get("tags_exclusivas"))
        if not selecionados:
            sem_conteudo.append(perfil["id"])
            continue
        jobs.append({
            "id": perfil["id"],
            "email": perfil["email_destino"].strip(),
            "assunto": f"📋 Relatório PCE Semanal - {len(selecionados)} Novos Editais Encontrados",
            "html": _montar_html(selecionados, inicio, fim, agora),
        })

    # --- Envio simultâneo para todos ---
    ok_ids = []
    if jobs:
        log_func(f"    [📧 SMTP] Disparando {len(jobs)} e-mail(s) em paralelo...")
        with ThreadPoolExecutor(max_workers=max(1, min(config.REPORT_MAX_PARALELO, len(jobs)))) as pool:
            futuros = {pool.submit(_enviar_email, j["email"], j["assunto"], j["html"]): j for j in jobs}
            for futuro in as_completed(futuros):
                job = futuros[futuro]
                erro = futuro.result()
                chave = (job["id"], slot_data)
                if erro is None:
                    ok_ids.append(job["id"])
                    estado["enviados"].add(chave)
                    log_func(f"    [✓] Enviado para {job['email']}")
                else:
                    anteriores = estado["falhas"].get(chave, {"tentativas": 0})["tentativas"]
                    estado["falhas"][chave] = {"tentativas": anteriores + 1, "ultima": agora}
                    resumo["falhas"] += 1
                    log_func(f"    [X] Falha SMTP para {job['email']} "
                             f"(tentativa {anteriores + 1}/{config.REPORT_MAX_TENTATIVAS}): {erro}")

    # --- Gravação no banco (thread do agendador, depois que todos os envios terminaram) ---
    try:
        if ok_ids:
            cliente.table("configuracoes_relatorio").update(
                {"ultima_semana_enviada": slot_data, "ultimo_envio": agora.strftime("%Y-%m-%d")}
            ).in_("id", ok_ids).execute()
        if sem_conteudo:
            cliente.table("configuracoes_relatorio").update({"ultima_semana_enviada": slot_data}).in_("id", sem_conteudo).execute()
    except Exception as e:
        log_func(f"    [⚠️] E-mails enviados, mas falhou ao gravar no banco ({e}). "
                 f"Sem reenvio neste processo; confira 'ultima_semana_enviada'.")

    resumo["enviados"], resumo["sem_conteudo"] = len(ok_ids), len(sem_conteudo)
    log_func(f"    [📅 RELATÓRIO] Concluído: {resumo}")
    return resumo


def compilar_e_enviar_relatorio_automatico(log_func):
    """Compatibilidade com o nome antigo (uma passada da rotina)."""
    return executar_relatorio_semanal(log_func)


# ---------------------------------------------------------------------------
# Agendador em thread própria
# ---------------------------------------------------------------------------
def iniciar_agendador_relatorio(log_func, parar=None):
    """
    Inicia a thread do agendador e retorna (thread, evento_parar).
    Independente do ciclo de scraping/IA: confere a agenda a cada REPORT_INTERVALO_CHECAGEM segundos.
    """
    parar = parar or threading.Event()

    def laco():
        log_func(f"[📅 AGENDADOR] Relatório semanal ativo. Próximo slot: {descrever_slot(_proximo_slot(datetime.now()))}.")
        cliente = None
        ultimo_batimento = time.monotonic()

        while not parar.is_set():
            try:
                cliente = cliente or criar_cliente()
                executar_relatorio_semanal(log_func, cliente=cliente)
            except Exception as e:
                log_func(f"[X] Agendador de relatório: {e}")
                traceback.print_exc()
                cliente = None          # força recriar a conexão no próximo ciclo

            if time.monotonic() - ultimo_batimento > 3600:
                log_func(f"[📅 AGENDADOR] Ativo. Próximo slot: {descrever_slot(_proximo_slot(datetime.now()))}.")
                ultimo_batimento = time.monotonic()

            parar.wait(config.REPORT_INTERVALO_CHECAGEM)

    thread = threading.Thread(target=laco, name="agendador-relatorio", daemon=True)
    thread.start()
    return thread, parar