# Robô de Monitoramento e Prospecção de Editais (PCE)

Este é um ecossistema automatizado de inteligência focado na varredura, extração, análise e notificação de novos editais públicos e chamadas de inovação, tecnologia e pesquisa. 

O sistema realiza buscas periódicas em portais como **CNPq, Finep, Fundep e Petrobras (Sigitec)**, utiliza inteligência artificial (**Google Gemini**) para resumir e categorizar o escopo técnico das oportunidades e gerencia as preferências de notificações enviando relatórios semanais customizados por e-mail (via SMTP corporativo) para múltiplos usuários cadastrados.

---

## 📂 Estrutura do Projeto

O projeto adota uma arquitetura modular baseada em responsabilidades isoladas para garantir facilidade de manutenção e escalabilidade:

```text
meu_projeto/
│
├── config.py              # Credenciais, conexão com o Supabase e prompt base da IA
├── main.py                # Serviço de background principal (Orquestrador do loop)
├── README.md              # Documentação técnica do repositório
│
├── core/                  # Core business e processamento de regras de negócio
│   ├── __init__.py
│   ├── ai_engine.py       # Extração com Gemini (Prompts, rotação de chaves e IA)
│   ├── db_cleaner.py      # Rotina de expurgo de editais vencidos na base
│   └── reporter.py        # Processador e distribuidor multi-usuário de relatórios SMTP
│
├── utils/                 # Ferramentas utilitárias e extratores de texto
│   ├── __init__.py
│   ├── scraper_utils.py   # Manipulação de requisições, BeautifulSoup e limpeza de HTML
│   └── document_utils.py  # Leitores profundos de PDF, TextMiner e OCR Tesseract
│
└── portais/               # Motores dedicados de raspagem (Scrapers)
    ├── __init__.py
    ├── cnpq.py            # Motor focado nas Chamadas Abertas do CNPq
    ├── fundep.py          # Motor focado nos Projetos da Fundep
    ├── finep.py           # Motor focado nas Oportunidades da Finep (Liferay)
    └── petrobras.py       # Motor focado no SPA React do Sigitec Petrobras
```

---

## 🛠️ Tecnologias e Dependências

O robô foi desenvolvido em **Python 3.13** utilizando as seguintes tecnologias centrais:
* **Banco de Dados:** Supabase (PostgreSQL em Nuvem) para persistência de dados e controle de usuários.
* **Inteligência Artificial:** SDK `google-genai` integrado ao modelo `gemini-2.5-flash` para estruturação de dados em formato JSON.
* **Automação de Navegação:** `playwright` para renderização de aplicações de página única (SPAs) e `BeautifulSoup4` para mineração clássica de HTML.
* **Processamento de Documentos:** `pypdf`, `pdfminer.six`, `pdf2image` e `pytesseract` (Tesseract OCR) para leitura de editais em PDFs textuais ou escaneados.

---

## 🚀 Instalação e Configuração

### 1. Clonar o Repositório
```bash
git clone https://github.com
cd seu-repositorio
```

### 2. Instalar os Pacotes Python
Instale todas as distribuições requeridas através do gerenciador de pacotes `pip`:
```bash
pip install requests beautifulsoup4 pypdf pdf2image google-genai playwright supabase pytesseract pdfminer.six
```

### 3. Instalar o Navegador do Playwright
O Playwright necessita baixar o binário isolado do Chromium para renderizar as páginas dinâmicas:
```bash
python -m playwright install chromium
```

### 4. Configurar as Variáveis de Ambiente e Bancos
Certifique-se de validar as chaves e URLs de comunicação dentro do arquivo `config.py`:
* **Supabase:** URL e a chave pública de acesso (`SUPABASE_URL` e `SUPABASE_KEY`).
* **SMTP:** Servidor de relay corporativo configurado para envio de mensagens internas.

---

## 💻 Como Executar

O robô roda como um serviço de segundo plano persistente. A cada **2 horas** (intervalo padrão configurável), ele limpa a base de registros antigos, executa a raspagem nos portais e dispara os e-mails pendentes.

Para iniciar o serviço, execute:
```bash
python main.py
```

---

## 📊 Fluxo de Funcionamento Interno

1. **Faxina Base (`core/db_cleaner.py`):** O robô inicia o ciclo buscando registros cuja data limite de submissão seja anterior ao dia de hoje, alterando seu status para `expirado` para manter a integridade operacional do painel.
2. **Raspagem dos Portais (`portais/`):** Cada script de portal busca novas URLs de editais de forma cirúrgica. Links novos são pré-extraídos e registrados no Supabase com status `PENDENTE`.
3. **Esteira de IA (`core/ai_engine.py`):** A fila pendente é consumida. O robô faz a rotação de chaves da API do Gemini caso encontre limites de cota (`429`) e injeta os dados estruturados (prazos, verbas, escopo e palavras-chave técnicas) de volta ao banco.
4. **Distribuição de Relatórios (`core/reporter.py`):** O sistema varre a tabela `configuracoes_relatorio`. Para cada assinante que completou a janela de 7 dias desde o último envio, as oportunidades criadas no período são filtradas de acordo com as preferências de tags do usuário e disparadas formatadas em HTML contendo os botões com os links fontes originais.
