import os, sys
from dotenv import load_dotenv
from supabase import create_client

if getattr(sys, 'frozen', False):
    DIRETORIO_PAI = os.path.dirname(sys.executable)
else:
    DIRETORIO_PAI = os.path.dirname(os.path.abspath(__file__))

# Carrega o .env que fica ao lado do config.py (ou do executável)
load_dotenv(os.path.join(DIRETORIO_PAI, ".env"))


def _obrigatoria(nome):
    valor = os.getenv(nome)
    if not valor:
        raise RuntimeError(
            f"Variável de ambiente '{nome}' não definida. "
            f"Copie .env.example para .env e preencha."
        )
    return valor


DIRETORIO_PDFS = os.path.join(DIRETORIO_PAI, "editais_baixados")
os.makedirs(DIRETORIO_PDFS, exist_ok=True)

# --- CONFIGURAÇÃO OLLAMA (IA LOCAL) ---
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))
# Raciocínio ("thinking") de modelos como Qwen3.5 / DeepSeek-R1:
#   "auto" = não envia o parâmetro (usa o padrão do modelo; em modelos de raciocínio é LIGADO e lento)
#   "off"  = desliga o raciocínio   |   "on" = liga
# Modelos instruct comuns (qwen2.5) não têm raciocínio: deixe "auto". Teste com scripts/comparar_modelos.py.
# Benchmark (scripts/comparar_modelos.py, 5 editais): qwen3.5:9b com "off" = 15 s/edital e 5/5 JSON válidos;
# com "auto" gasta ~3.000-4.800 tokens pensando (100-180 s) e 2 de 5 respostas vieram inválidas.
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "off")

# Limite de caracteres do edital enviados à IA. ~3,5 caracteres/token em português:
# 40.000 chars ≈ 11-12k tokens, deixando folga no num_ctx para prompt + resposta.
MAX_CHARS_TEXTO_IA = int(os.getenv("MAX_CHARS_TEXTO_IA", "40000"))

# --- PDFs anexos ---
MAX_PDFS_POR_EDITAL = int(os.getenv("MAX_PDFS_POR_EDITAL", "3"))   # anexos lidos por edital
MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", "30"))                    # ignora PDFs maiores que isso
OCR_MAX_PAGINAS = int(os.getenv("OCR_MAX_PAGINAS", "10"))          # páginas por PDF escaneado
MAX_CHARS_TEXTO_BRUTO = int(os.getenv("MAX_CHARS_TEXTO_BRUTO", "400000"))  # teto gravado em texto_extracao

# --- RELATÓRIO SEMANAL (agendador próprio, independente do ciclo de scraping/IA) ---
REPORT_DIA_SEMANA = int(os.getenv("REPORT_DIA_SEMANA", "0"))        # 0=segunda ... 6=domingo
REPORT_HORA = int(os.getenv("REPORT_HORA", "7"))
REPORT_MINUTO = int(os.getenv("REPORT_MINUTO", "0"))
REPORT_MAX_PARALELO = int(os.getenv("REPORT_MAX_PARALELO", "20"))   # e-mails enviados ao mesmo tempo
REPORT_INTERVALO_CHECAGEM = int(os.getenv("REPORT_INTERVALO_CHECAGEM", "30"))   # segundos entre conferências da agenda
REPORT_MAX_TENTATIVAS = int(os.getenv("REPORT_MAX_TENTATIVAS", "3"))            # por assinante e por semana
REPORT_COOLDOWN_SEGUNDOS = int(os.getenv("REPORT_COOLDOWN_SEGUNDOS", "600"))    # espera entre tentativas após falha
# 0 = só editais INICIADOS na semana. N>0 = também os iniciados nos N dias anteriores que o robô
# só descobriu nesta semana (rede de segurança contra edital achado depois do relatório da semana dele).
REPORT_TOLERANCIA_DESCOBERTA_DIAS = int(os.getenv("REPORT_TOLERANCIA_DESCOBERTA_DIAS", "0"))

# Após N falhas (scraping ou IA) o edital vira 'falha_definitiva' e sai da fila
MAX_TENTATIVAS = int(os.getenv("MAX_TENTATIVAS", "3"))

# --- WORKERS (dois processos: main_busca.py e main_ia.py) ---
INTERVALO_BUSCA_SEGUNDOS = int(os.getenv("INTERVALO_BUSCA_SEGUNDOS", "7200"))      # entre varreduras dos portais
IA_POLL_SEGUNDOS = int(os.getenv("IA_POLL_SEGUNDOS", "60"))                        # IA confere a fila a cada N s quando ociosa
IA_TAMANHO_LOTE = int(os.getenv("IA_TAMANHO_LOTE", "20"))                          # editais carregados por vez
IA_INTERVALO_RETRY_SEGUNDOS = int(os.getenv("IA_INTERVALO_RETRY_SEGUNDOS", "1800"))  # retentativas e retrabalho
IA_BACKOFF_OLLAMA_SEGUNDOS = int(os.getenv("IA_BACKOFF_OLLAMA_SEGUNDOS", "300"))   # espera se o Ollama estiver fora
IA_MAX_TIMEOUTS_SEGUIDOS = int(os.getenv("IA_MAX_TIMEOUTS_SEGUIDOS", "3"))         # N timeouts seguidos = problema do modelo, pausa sem gastar tentativa

# --- PROMPT IA RESTRITIVO ---
PROMPT_BASE_IA = """
Você é especialista em análise de editais públicos de inovação, tecnologia e pesquisa.
Extraia somente informações explicitamente existentes no texto fornecido. Nunca invente valores.
Caso não encontre uma informação de jeito nenhum, retorne o campo correspondente como "Não encontrada".

Responda ESTRITAMENTE com um JSON válido (sem markdown, sem blocos extras).

DIRETRIZES DE CRIAÇÃO DAS TAGS:
Identifique de 3 a 10 palavras-chave ou termos técnicos específicos e profundos que definem o CONTEÚDO TÉCNICO E ESCOPO DO PROJETO deste edital (ex: inteligência artificial, biocombustíveis, previdência complementar, smart cities, telecomunicações). 

Proibições Absolutas:
- NUNCA inclua o nome do portal de origem (como Finep, CNPq, Fundep, Governo Federal).
- NUNCA inclua nomes de órgãos públicos, ministérios ou siglas de agências.
- NUNCA inclua termos genéricos de processo burocrático (como edital, chamada, processo seletivo, convênio, termo de referência).

Insira esses termos técnicos no campo "tags_ia" obrigatoriamente separados por vírgula.

DATA DE INÍCIO DO EDITAL ("inicio_iso"):
- É a data de ABERTURA do período de submissão (início das inscrições / envio de propostas).
- Se o texto trouxer apenas a data de publicação ou lançamento do edital, use essa data.
- NÃO use a data limite de submissão nem datas de início/vigência do projeto.
- Se nenhuma dessas datas estiver no texto, retorne "Não encontrada". Nunca invente.

PRAZO DE SUBMISSÃO ("prazo_iso"):
- É SOMENTE a data limite para enviar propostas/inscrições.
- Data de publicação, de abertura ou de resultado NÃO é prazo. Se não houver data limite, retorne "Não encontrada".
- Se o texto indicar que a inscrição está "Encerrada", escreva "Encerrada" em "datas" e retorne "Não encontrada" em "prazo_iso".

FORMATO DAS DATAS:
- Algumas páginas usam MM/DD/AA (ex.: "03/23/02" = 23 de março de 2002). Converta SEMPRE para YYYY-MM-DD; se um dos números for maior que 12, ele é o dia.

TÍTULO ("titulo"):
- Use o título ESPECÍFICO da oportunidade/desafio/chamada descrita no texto.
- NUNCA use o nome do portal, do programa ou um cabeçalho genérico (ex.: "Oportunidades de Inovação", "Sigitec").
- Se o texto for só uma mensagem de erro (ex.: "Oportunidade não encontrada") ou não trouxer o conteúdo de um edital, retorne "Não encontrada" em todos os campos.

SITUAÇÃO ("datas"):
- Se o edital estiver encerrado, cancelado ou aguardando resultado, escreva exatamente essa situação em "datas" (ex.: "Cancelada", "Aguardando resultado do certame").

Siga estritamente esta estrutura para o JSON:
{
  "titulo": "Nome/Título oficial simplificado do edital encontrado",
  "inicio_iso": "Data de abertura/início do edital formatada em YYYY-MM-DD (se encontrada ou data de publicação)",
  "prazo_iso": "Data limite de submissão/inscrição formatada em YYYY-MM-DD",
  "vigencia_projeto": "Texto resumido com o período/vigência do projeto (ex: Data de início, término ou prorrogações encontradas)",
  "fim_projeto_iso": "Data de término ou prorrogação final do projeto formatada em YYYY-MM-DD (se encontrada)",
  "pesquisa": "Descrição sucinta das linhas de pesquisa aceitas",
  "escopo": "Resumo detalhado do objetivo e escopo do edital",
  "subvencao": "Informações sobre recursos financeiros, subvenção econômica ou financiamento",
  "tags_ia": "termo1, termo2, termo3, ..."
}
"""

# --- CONFIGURAÇÕES DE RELAY CORPORATIVO INTERNO ---
SMTP_SERVIDOR = _obrigatoria("SMTP_SERVIDOR")
SMTP_PORTA = int(os.getenv("SMTP_PORTA", "25"))
SMTP_REMETENTE = _obrigatoria("SMTP_REMETENTE")

# --- CONEXÃO SUPABASE (service_role: uso exclusivo do robô) ---
SUPABASE_URL = _obrigatoria("SUPABASE_URL")
SUPABASE_KEY = _obrigatoria("SUPABASE_SERVICE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)