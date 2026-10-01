import os, sys
from supabase import create_client

if getattr(sys, 'frozen', False):
    DIRETORIO_PAI = os.path.dirname(sys.executable)
else:
    DIRETORIO_PAI = os.path.dirname(os.path.abspath(__file__))

DIRETORIO_PDFS = os.path.join(DIRETORIO_PAI, "editais_baixados")
os.makedirs(DIRETORIO_PDFS, exist_ok=True)

# --- CONFIGURAÇÃO OLLAMA (IA LOCAL) ---
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:7b-instruct"

# --- PROMPT IA RESTRITIVO ---
PROMPT_BASE_IA = """
Você é especialista em análise de editais públicos de inovação, tecnologia e pesquisa.
Extraia somente informações explicitamente existentes no texto fornecido. Nunca invente valores ou qualquer outro tipo de informação.
Caso não encontre uma informação de jeito nenhum, retorne o campo correspondente como "Não encontrada".

Responda ESTRITAMENTE com um JSON válido (sem markdown, sem blocos extras).

+ DIRETRIZES DE CRIAÇÃO DAS TAGS:
Identifique de 3 a 10 palavras-chave ou termos técnicos específicos e profundos que definem o CONTEÚDO TÉCNICO E ESCOPO DO PROJETO deste edital (ex: inteligência artificial, biocombustíveis, previdência complementar, smart cities, telecomunicações). 

Proibições Absolutas:
- NUNCA inclua o nome do portal de origem (como Finep, CNPq, Fundep, Governo Federal).
- NUNCA inclua nomes de órgãos públicos, ministérios ou siglas de agências.
- NUNCA inclua termos genéricos de processo burocrático (como edital, chamada, processo seletivo, convênio, termo de referência).

Insira esses termos técnicos no campo "tags_ia" obrigatoriamente separados por vírgula.

+ DIRETRIZES DE STATUS DO PROJETO:
A partir das informações adquiridas, analise e classifique o edital/chamado estritamente em uma das seguintes categorias para o campo "status_projeto":
- "ATIVO": O edital foi lido com sucesso, possui informações relevantes ("datas" e "escopo"/"pesquisa") e as inscrições estão abertas ou programadas para abrir.
- "ENCERRADO": Se houver menção explícita de "Inscrição Encerrada", "Chamada Encerrada", ou se os prazos descritos deixarem claro que o período de submissão já acabou.
- "N/A INFO": Conseguiu ler o texto, mas ele não traz informações sobre o que é o projeto (não encontrou dados reais de "pesquisa", "escopo" ou "subvencao").
- "ATEMPORAL": O edital está aberto/ativo, mas não possui nenhum tipo de data limite ou duração descrita no texto.
- "PAGINA_ERRO": O texto fornecido indica um erro do servidor do portal, como "Erro 404", "Página não encontrada", "Acesso negado", "Bad Gateway" ou falhas de carregamento de sistema.
- "NAO_EDITAL": O texto lido pertence a uma página institucional, manual de uso de sistema, termos de privacidade ou notícias do portal, e NÃO se trata de uma oportunidade/chamada pública de edital.

Siga estritamente esta estrutura para o JSON:
{
  "titulo": "Nome/Título oficial simplificado do edital encontrado",
  "status_projeto": "ATIVO ou ENCERRADO ou N/A INFO ou ATEMPORAL ou PAGINA_ERRO ou NAO_EDITAL",
  "datas": "Texto resumido com o prazo limite de submissão do edital no formato 'DD-MM-YY - DD-MM-YY' ou caso ache só a data de abertura 'Iniciado em DD-MM-YY' ou caso só a data de encerramento 'Até DD-MM-YY'",
  "prazo_iso": "Data limite de submissão formatada em YYYY-MM-DD (se encontrada)",
  "vigencia_projeto": "Texto resumido com o período/vigência do projeto (ex: Data de início, término ou prorrogações encontradas)",
  "fim_projeto_iso": "Data de término ou prorrogação final do projeto formatada em YYYY-MM-DD (se encontrada)",
  "pesquisa": "Descrição sucinta das linhas de pesquisa aceitas",
  "escopo": "Resumo detalhado do objetivo e escopo do edital",
  "subvencao": "Informações sobre recursos financeiros, subvenção econômica ou financiamento",
  "tags_ia": "termo1, termo2, termo3, ..."
}
"""

# --- CONFIGURAÇÕES DE RELAY CORPORATIVO INTERNO - FIEB ---
SMTP_SERVIDOR = "fieb-org-br.mail.protection.outlook.com"
SMTP_PORTA = 25
SMTP_REMETENTE = "joao.freire@fbter.org.br"

# --- CONEXÃO SUPABASE ---
SUPABASE_URL = "https://sjozzxjyqkcofjmyljlv.supabase.co"
SUPABASE_KEY = "sb_publishable_r8890QkbhIEaO1A8gV9p8A_lYzTfuxI"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
