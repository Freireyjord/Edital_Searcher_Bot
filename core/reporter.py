import html
import smtplib
import unicodedata
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# Importa o config para ler o cliente Supabase e variáveis globais
import config

def _e(valor):
    """Escapa texto vindo do banco/IA/sites raspados antes de entrar no HTML do e-mail."""
    return html.escape("" if valor is None else str(valor))


def _url_segura(url):
    """Só links http(s); qualquer outra coisa vira '#'."""
    url = str(url or "").strip()
    return html.escape(url, quote=True) if url.lower().startswith(("http://", "https://")) else "#"


# Colunas usadas no e-mail. Nunca select("*"): texto_extracao guarda o texto bruto de editais e PDFs.
COLUNAS_RELATORIO = "titulo,portal,datas,vigencia_projeto,subvencao,tags_ia,escopo,url"


def normalizar_texto_report(texto):
    if not texto: return ""
    texto = str(texto).strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def compilar_e_enviar_relatorio_automatico(log_func):
    """
    Varre todos os assinantes cadastrados na tabela configuracoes_relatorio,
    avalia o intervalo de 7 dias individualmente, filtra as oportunidades
    por tags e dispara os e-mails com os links fontes restaurados.
    """
    log_func("    [📅 RELATÓRIO] Iniciando rotina de monitoramento de e-mails distribuídos...")
    hoje = datetime.now()
    hoje_data_str = hoje.strftime("%Y-%m-%d")
    
    # 1. Puxa todos os assinantes da tabela de configurações
    try:
        resposta_config = config.supabase.table("configuracoes_relatorio").select("*").execute()
        lista_assinantes = resposta_config.data
    except Exception as e:
        log_func(f"    [X] Falha crítica ao ler parâmetros de assinantes no banco: {e}")
        return

    if not lista_assinantes:
        log_func("    [⚠️] Abortado: Nenhuma assinatura configurada na tabela 'configuracoes_relatorio'.")
        return

    # 2. Varre cada perfil cadastrado no banco de dados
    for perfil in lista_assinantes:
        id_registro = perfil.get("id")
        email_destinatario = perfil.get("email_destino", "").strip()
        deve_filtrar_tags = perfil.get("filtrar_por_tags", False)
        tags_brutas_banco = perfil.get("tags_exclusivas", "")
        ultimo_envio_str = perfil.get("ultimo_envio")

        if not email_destinatario:
            log_func(f"    [⚠️ Registro ID {id_registro}] Ignorado: Endereço de e-mail em branco.")
            continue

        # Controle de trava de calendário (Garante intervalo mínimo de 7 dias por usuário)
        if ultimo_envio_str:
            try:
                ultimo_envio = datetime.strptime(ultimo_envio_str, "%Y-%m-%d").date()
                if (hoje.date() - ultimo_envio).days < 7:
                    log_func(f"    [⏳] Cronograma em dia para {email_destinatario}. Último envio há {(hoje.date() - ultimo_envio).days} dias.")
                    continue
            except Exception as e_data:
                log_func(f"    [⚠️] Erro ao processar data de envio do ID {id_registro}: {e_data}. Forçando envio...")

        log_func(f"    [🚀 PROCESSANDO] Compilando editais para: {email_destinatario} | Filtro ativo: {deve_filtrar_tags}")

        # Configura a janela de corte de 7 dias baseado no created_at do banco
        uma_semana_atras = hoje - timedelta(days=7)
        data_corte_iso = uma_semana_atras.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            # Busca editais concluídos gerados nos últimos 7 dias
            resposta_editais = config.supabase.table("editais").select(COLUNAS_RELATORIO).gte("created_at", data_corte_iso).eq("status_ia", "CONCLUIDO").execute()
            editais_capturados = resposta_editais.data
        except Exception as e:
            log_func(f"    [X] Falha ao consultar tabela editais para {email_destinatario}: {e}")
            continue

        if not editais_capturados:
            log_func(f"    [✨] Nenhum edital novo inserido no banco nos últimos 7 dias para {email_destinatario}.")
            # Atualiza a trava para evitar sobrecarga de consultas inúteis no próximo loop
            config.supabase.table("configuracoes_relatorio").update({"ultimo_envio": hoje_data_str}).eq("id", id_registro).execute()
            continue

        # Aplica o filtro de tags do usuário
        termos_usuario = [normalizar_texto_report(t) for t in tags_brutas_banco.split(",") if t.strip()]
        editais_filtrados = []

        for edital in editais_capturados:
            if deve_filtrar_tags and len(termos_usuario) > 0:
                tags_ia = [normalizar_texto_report(t) for t in (edital.get("tags_ia", "") or "").split(",") if t.strip()]
                titulo = normalizar_texto_report(edital.get("titulo", ""))
                
                corresponde = False
                for termo in termos_usuario:
                    if termo in titulo: corresponde = True; break
                    if any(termo in tag or tag in termo for tag in tags_ia): corresponde = True; break
                if not corresponde: continue

            editais_filtrados.append(edital)

        if not editais_filtrados:
            log_func(f"    [✨] Há oportunidades no período, mas nenhuma atende aos filtros de {email_destinatario}.")
            config.supabase.table("configuracoes_relatorio").update({"ultimo_envio": hoje_data_str}).eq("id", id_registro).execute()
            continue

        # Montagem do HTML corporativo com os links funcionando
        log_func(f"    [📧 SMTP] Despachando relatório contendo {len(editais_filtrados)} editais para {email_destinatario}...")
        html_corpo = f"""
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
                    <p>Compilado automatizado de oportunidades — Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')}</p>
                </div>
        """
        for item in editais_filtrados:
            html_corpo += f"""
                <div class="card">
                    <h3>{_e(item.get('titulo') or 'Edital sem título')}</h3>
                    <div class="meta">
                        <strong>Portal:</strong> {_e(item.get('portal') or 'N/A')} | <strong>Prazo:</strong> {_e(item.get('datas') or 'A consultar')}<br>
                        <strong>Vigência:</strong> {_e(item.get('vigencia_projeto') or 'N/A')} | <strong>Verba:</strong> {_e(item.get('subvencao') or 'N/A')}<br>
                        <strong>Tags:</strong> <i>{_e(item.get('tags_ia') or 'Geral')}</i>
                    </div>
                    <div class="escopo"><strong>Resumo:</strong> {_e(item.get('escopo') or 'Sem resumo.')}</div>
                    <a href="{_url_segura(item.get('url'))}" class="btn-link" target="_blank">VISUALIZAR EDITAL FONTE</a>
                </div>
            """
        html_corpo += "</div></body></html>"

        try:
            msg = MIMEMultipart()
            msg['From'] = config.SMTP_REMETENTE
            msg['To'] = email_destinatario
            msg['Subject'] = f"📋 Relatório PCE Semanal - {len(editais_filtrados)} Novos Editais Encontrados"
            msg.attach(MIMEText(html_corpo, 'html', 'utf-8'))
            
            servidor = smtplib.SMTP(config.SMTP_SERVIDOR, config.SMTP_PORTA, timeout=30)
            servidor.sendmail(config.SMTP_REMETENTE, email_destinatario, msg.as_string())
            servidor.quit()

            # Atualiza o carimbo no banco usando o ID real da linha para destravar os próximos 7 dias
            config.supabase.table("configuracoes_relatorio").update({"ultimo_envio": hoje_data_str}).eq("id", id_registro).execute()
            log_func(f"    [✓] Relatório para {email_destinatario} enviado e gravado com sucesso!")
        except Exception as e_smtp:
            log_func(f"    [X] Erro SMTP FIEB ao enviar para {email_destinatario}: {e_smtp}")