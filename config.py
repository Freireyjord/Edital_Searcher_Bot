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
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b-instruct")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))

# Limite de caracteres do edital enviados à IA. ~3,5 caracteres/token em português:
# 40.000 chars ≈ 11-12k tokens, deixando folga no num_ctx para prompt + resposta.
MAX_CHARS_TEXTO_IA = int(os.getenv("MAX_CHARS_TEXTO_IA", "40000"))

# --- PDFs anexos ---
MAX_PDFS_POR_EDITAL = int(os.getenv("MAX_PDFS_POR_EDITAL", "3"))   # anexos lidos por edital
MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", "30"))                    # ignora PDFs maiores que isso
OCR_MAX_PAGINAS = int(os.getenv("OCR_MAX_PAGINAS", "10"))          # páginas por PDF escaneado
MAX_CHARS_TEXTO_BRUTO = int(os.getenv("MAX_CHARS_TEXTO_BRUTO", "400000"))  # teto gravado em texto_extracao

# Após N falhas (scraping ou IA) o edital vira 'falha_definitiva' e sai da fila
MAX_TENTATIVAS = int(os.getenv("MAX_TENTATIVAS", "3"))

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

Siga estritamente esta estrutura para o JSON:
{
  "titulo": "Nome/Título oficial simplificado do edital encontrado",
  "datas": "Texto resumido com o prazo limite de submissão do edital no formato 'DD-MM-YY - DD-MM-YY' ou caso ache so a data de abertura 'Iniciado em DD-MM-YY' ou caso so a data de encerramento 'Até DD-MM-YY'",
  "prazo_iso": "Data limite de submissão formatada em YYYY-MM-DD (se encontrada)",
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