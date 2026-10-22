"""
Agenda do relatório semanal (sem banco, sem e-mail: só datas).

Conceitos:
- "slot": o instante agendado do envio (ex.: toda segunda às 07:00).
- O slot vigente é o mais recente que já passou. O que importa para cada assinante é
  se ele já recebeu o relatório *deste* slot (coluna `ultima_semana_enviada`).
  Por isso um atraso (bot desligado, ciclo longo, falha de SMTP) nunca "pula" a semana:
  assim que o bot voltar, o envio é feito, e o próximo slot continua sendo a próxima segunda.
- Janela de editais de cada relatório: [slot - 7 dias, slot). Janelas consecutivas não se
  sobrepõem nem deixam buracos, mesmo que o envio atrase.
"""
from datetime import date, datetime, timedelta

DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def momento_agendado_atual(agora, dia_semana=0, hora=7, minuto=0):
    """Slot mais recente <= agora. dia_semana: 0=segunda ... 6=domingo."""
    dias_atras = (agora.weekday() - dia_semana) % 7
    candidato = (agora - timedelta(days=dias_atras)).replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if candidato > agora:           # hoje é o dia, mas ainda não deu a hora
        candidato -= timedelta(days=7)
    return candidato


def proximo_momento(agora, dia_semana=0, hora=7, minuto=0):
    return momento_agendado_atual(agora, dia_semana, hora, minuto) + timedelta(days=7)


def janela_do_relatorio(slot):
    """(inicio, fim) dos editais cobertos pelo relatório deste slot: [inicio, fim)."""
    return slot - timedelta(days=7), slot


def _como_data(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return datetime.strptime(str(valor).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def classificar_assinante(ultima_semana_enviada, slot):
    """
    'novo'      -> nunca entrou na agenda: é registrado no slot atual SEM enviar
                   (começa a receber no próximo; evita rajada de "recuperação" ao implantar
                   e envio de janela antiga para quem acabou de se cadastrar)
    'pendente'  -> ainda não recebeu o relatório deste slot
    'em_dia'    -> já recebeu
    """
    enviada = _como_data(ultima_semana_enviada)
    if enviada is None:
        return "novo"
    return "pendente" if enviada < slot.date() else "em_dia"


def descrever_slot(slot):
    return f"{DIAS_SEMANA[slot.weekday()]}-feira {slot.strftime('%d/%m/%Y às %H:%M')}" if slot.weekday() < 5 \
        else f"{DIAS_SEMANA[slot.weekday()]} {slot.strftime('%d/%m/%Y às %H:%M')}"