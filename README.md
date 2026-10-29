# Robô de Monitoramento e Prospecção de Editais (PCE)

Ecossistema automatizado de nível empresarial para varredura, extração de texto composto (HTML/PDF/OCR), análise estruturada via Inteligência Artificial local e notificação fracionada de editais públicos e chamadas de inovação, tecnologia e pesquisa.

O robô monitora portais como **CNPq, Finep, Fundep, BNDES, FAPESB, Petrobras (Sigitec) e a Plataforma Inovação para a Indústria**, utiliza um LLM local (**Ollama**) para extração de dados determinística em JSON e persiste as informações em um cluster **Supabase**. Um subsistema de agendamento em thread isolada despacha relatórios semanais customizados por e-mail (SMTP corporativo) aos assinantes.

---

## 🗺️ Arquitetura e Fluxo de Dados

O ecossistema é baseado em uma **arquitetura orientada a eventos assíncrona e desacoplada**, utilizando as tabelas do Supabase como fila de mensageria:

```text
[Portais Externos] (Estáticos, SPAs e React)
        │
        ▼ (Scraping Híbrido, Fallback OCR e Deduplicação)
  main_busca.py ──> [ utils/scraper_utils.py ] ──> [ utils/document_utils.py ]
                             │
                             ▼ (Insere registro com status 'PENDENTE')
                     ┌───────────────┐
                     │   SUPABASE    │
                     └───────────────┘
                             │
                             ▼ (Consome fila 'PENDENTE' em lote contínuo)
    main_ia.py  ──> [ core/ai_engine.py ] ──> [ Ollama Local (Temp 0) ]
                             │
                             ├── (Validação Rígida Schema: core/ai_validator.py)
                             ▼ (Atualiza registro para status 'CONCLUIDO')
                [ core/reporter.py (Thread) ] ──> [ Pool SMTP Paralelo ]
```

---

## 📂 Estrutura do Projeto

```text
meu_projeto/
├── config.py              # Orquestrador central: carrega .env, singletons e Prompt Base
├── main.py                # Depreciado: emite erro e instrui a fragmentação de execução
├── main_busca.py          # Worker de busca: varredura perene e ingestão de registros
├── main_ia.py             # Worker de IA: processamento de LLM + agendador de e-mails
├── .env                   # Variáveis de ambiente reais (Ignorado no Git)
├── .env.example           # Template de configuração e infraestrutura local
├── requirements.txt       # Dependências operacionais fixadas
│
├── core/
│   ├── __init__.py
│   ├── agenda_relatorio.py # Regras matemáticas de slots e janelas temporárias
│   ├── ai_engine.py       # Fila de IA, backoff exponencial e esteira de retrabalho
│   ├── ai_validator.py    # Validador de schema, descarte de lixo e limpeza de tags
│   ├── db_cleaner.py      # Expurgo de editais vencidos e otimização de espaço
│   ├── reporter.py        # Geração de HTML e disparo fracionado de e-mails
│   └── workers.py         # Laços de execução contínua de background
│
├── utils/
│   ├── __init__.py
│   ├── document_utils.py  # Download seguro stream-to-memory, pdfminer e OCR fallback
│   ├── http_utils.py      # Sessão compartilhada com retry-adapter e backoff-factor
│   ├── instancia_unica.py # Travas exclusivas no Sistema Operacional (.locks/)
│   ├── pdf_links.py       # Scoring e priorização estatística de PDFs anexos
│   ├── scraper_utils.py   # Validação primária de entrada e montagem de texto composto
│   ├── texto_utils.py     # Algoritmo Water-Filling para divisão de contexto de IA
│   └── url_utils.py       # Sanitização fragmentária de caminhos e abas
│
├── portais/               # Motores de scraping (Descoberta automática)
│   ├── __init__.py
│   ├── bndes.py           # Varredura de blocos colapsáveis (Plone) com suporte a auditoria
│   ├── cnpq.py            # Mineração estática cirúrgica de alta velocidade
│   ├── fapesb.py          # Automação de POST/Filtros e grid dinâmico via Playwright
│   ├── finep.py           # Paginação assistida sob catálogo Liferay
│   ├── fundep.py          # Extração em requisição única capturando JSON interno Next.js
│   ├── petrobras.py       # Interceptador React, manipulação de DOM e reciclagem de sessão
│   └── portal_industria.py # Monitoramento profundo multicategorias com retries
│
└── scripts/
    ├── comparar_modelos.py # CLI para benchmark, TPS, tokens e divergências de LLMs
    └── testar_portal.py   # CLI para dry-run de portais com proxy Supabase de leitura
```

---

## 🛠️ Tecnologias e Motores Principais

*   **Python 3.13** como runtime principal.
*   **Supabase (PostgreSQL)** para persistência e orquestração de fila.
*   **Ollama** para processamento de IA generativa em infraestrutura local (On-Premise).
*   **Playwright (Chromium Headless Shell)** para emulação e interação com SPAs baseadas em Javascript.
*   **pdfminer.six** para extração de strings vetoriais de documentos nativos.
*   **Tesseract OCR + pdf2image (Poppler)** para digitalização e conversão de PDFs escaneados.

---

## 🚀 Instalação e Configuração

### 1. Clonar e Inicializar o Ambiente
```bash
git clone <URL-DO-REPOSITORIO>
cd <pasta-do-projeto>

python -m venv .venv
# Ativação no Windows: .venv\Scripts\activate | Linux/Mac: source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Configuração do Ambiente Local (OCR)
*   **Tesseract:** Certifique-se de que o binário possui o pacote de idioma `por` instalado. Adicione o caminho de execução na variável `TESSERACT_CMD` se ele não estiver no PATH global do sistema.
*   **Poppler:** Essencial para o funcionamento do modulo `pdf2image`. No ecossistema Windows, aponte a pasta `bin` na variável `POPPLER_PATH`.

### 3. Configuração de Variáveis de Ambiente
Copie o arquivo de exemplo para inicializar o seu arquivo real:
```bash
cp .env.example .env
```
Abra o `.env` e preencha com os dados de infraestrutura:
*   `SUPABASE_SERVICE_KEY`: Use estritamente a chave `service_role` (segurança de backend). Nunca exponha essa credencial no front-end.
*   `OLLAMA_MODEL`: Escolha do modelo (Padrão recomendado: `qwen3.5:9b`).
*   `OLLAMA_THINK`: Controle de raciocínio (`off` | `auto` | `on`). Modelos estilo DeepSeek-R1 ou Qwen3.5 com raciocínio ligado geram milhares de tokens ocultos, reduzindo a performance. O padrão recomendado para extração rápida é `off`.

---

## 🔄 Funcionamento dos Processos Operacionais

O ecossistema é mantido vivo através de **dois processos paralelos** que não compartilham memória, conversando estritamente através de transações de estado no Supabase.

Para rodar em ambiente de produção, abra dois terminais (ou configure duas tarefas simultâneas no Agendador do Windows):

```bash
# Terminal 1: Monitoramento contínuo de portais. Roda a cada 2 horas por padrão.
python main_busca.py

# Terminal 2: Esteira de processamento Ollama + Disparador de Relatório Semanal
python main_ia.py
```

### 🔒 Mecanismos de Proteção e Resiliência Integrados
1.  **Trava de Instância Única (msvcrt / fcntl):** O robô cria travas diretamente no kernel do Sistema Operacional ao iniciar cada trabalhador. Se você tentar rodar um segundo `main_ia.py` por engano, ele será abortado imediatamente, impedindo análises de GPU duplicadas ou disparo em massa de e-mails repetidos.
2.  **Algoritmo Water-Filling (`texto_utils.py`):** Antes de enviar o edital para o Ollama, o robô divide dinamicamente o orçamento máximo de contexto de texto (`MAX_CHARS_TEXTO_IA`). Páginas ou anexos pequenos são lidos por inteiro, enquanto documentos massivos sofrem truncamento bidirecional equilibrado (mantendo início e fim), garantindo que um anexo gigante nunca engula o contexto das outras fontes.
3.  **Controle Inteligente de Concorrência de Falhas (Timeouts Seguidos):** Se o modelo sofrer timeouts repetidos por lentidão de hardware ou travamento (`IA_MAX_TIMEOUTS_SEGUIDOS`), o processo de IA suspende temporariamente a fila e entra em backoff exponencial de segurança **sem queimar ou gastar as tentativas** dos editais sob análise.
4.  **Esteira Automática de Retrabalho:** Editais capturados com páginas corrompidas, limitação de rede ou falha de renderização inicial são jogados para o status `erro_sem_texto`. O sistema re-executa a raspagem de forma isolada utilizando instâncias reais e emuladas do Playwright.
5.  **Fatiamento Crítico de E-mails (Segmentation):** Para evitar que os relatórios semanais excedam as limitações físicas de tamanho de e-mail estipuladas por firewalls corporativos e relays SMTP, se um assinante possuir um volume superior a 20 editais novos em sua semana, o relatório é fatiado de forma automatizada em mensagens numeradas ("Parte 1/X").

---

## 📊 Ciclo de Vida do Registro (`status_ia`)

*   `PENDENTE`: Ingestão concluída com sucesso pelo Worker de Busca; aguardando processamento da IA.
*   `erro_sem_texto`: Página capturada sem conteúdo legível. Encaminhada para a esteira de re-scraping via Playwright.
*   `erro_ia`: Falha temporária no processamento da IA (JSON malformado ou indisponibilidade). Re-tentada a cada 30 minutos até o limite definido (`MAX_TENTATIVAS`).
*   `CONCLUIDO`: Processamento finalizado. Dados normalizados salvos e prontos para o painel visual e relatórios.
*   `descartado_invalido`: Registro limpo e retirado da fila por não conter um título de edital válido (Páginas de erro 404 capturadas, cabeçalhos genéricos).
*   `descartado_encerrado`: Identificado pela IA como cancelado ou já finalizado antes do processamento.
*   `descartado_vencido`: Prazo de submissão do edital expirado antes do processamento de IA.
*   `falha_definitiva`: Registro estourou o teto de re-tentativas. Removido automaticamente da fila de concorrência para auditoria manual.
