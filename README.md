# Robô de Monitoramento e Prospecção de Editais (PCE)

Ecossistema automatizado para varredura, extração, análise e notificação de editais públicos e chamadas de inovação, tecnologia e pesquisa.

O robô coleta editais de **CNPq, Finep, Fundep e Petrobras (Sigitec)**, usa uma **IA local (Ollama)** para resumir e categorizar o escopo técnico e grava tudo no **Supabase**. Também envia relatórios semanais personalizados por e-mail (SMTP corporativo) aos assinantes cadastrados.

---

## Estrutura do projeto

```text
meu_projeto/
├── config.py              # Carrega .env, conecta ao Supabase, prompt da IA
├── main.py                # Orquestrador (loop de background)
├── .env                   # Segredos (NÃO versionar)
├── .env.example           # Modelo de variáveis
├── requirements.txt
│
├── core/
│   ├── __init__.py
│   ├── ai_engine.py       # Fila de IA (Ollama) e retrabalho
│   ├── ai_validator.py    # Validação/normalização da resposta do LLM
│   ├── db_cleaner.py      # Marca editais vencidos como expirados
│   └── reporter.py        # Relatórios semanais por e-mail
│
├── utils/
│   ├── __init__.py
│   ├── scraper_utils.py   # Coleta página + PDFs anexos e registra no banco
│   ├── document_utils.py  # Download seguro de PDF, pdfminer e OCR (fallback)
│   ├── pdf_links.py       # Descobre e prioriza PDFs anexos em uma página
│   ├── texto_utils.py     # Fontes do texto e orçamento de caracteres para a IA
│   └── http_utils.py      # Sessão HTTP com retry/backoff
│
└── portais/               # Um módulo por portal
    ├── __init__.py
    ├── cnpq.py
    ├── fundep.py
    ├── finep.py
    └── petrobras.py
```

Cada módulo de portal deve expor:
- `NOME_PORTAL`: nome gravado na coluna `portal`;
- `varrer(log, atualizar_tabela_func)`: coleta e registra os editais;
- `recuperar(page, url)` *(opcional)*: re-extração de texto no retrabalho. Se não existir, usa-se o extrator genérico.

---

## Tecnologias

- **Python 3.13**
- **Supabase** (PostgreSQL) para persistência
- **Ollama** (`qwen2.5:14b-instruct` por padrão) para extração estruturada em JSON
- **Playwright** + **BeautifulSoup4** para raspagem (SPAs e HTML estático)
- **pdfminer.six** para PDFs com texto; **pytesseract + pdf2image** (OCR) como fallback para PDFs escaneados

---

## Instalação

```bash
git clone <URL-DO-REPOSITORIO>
cd <pasta-do-projeto>

python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/Mac: source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
```

### Ollama

Instale o [Ollama](https://ollama.com) e baixe o modelo:

```bash
ollama pull qwen2.5:14b-instruct
```

### OCR (opcional)

Só é necessário para PDFs escaneados. Sem ele, esses PDFs são ignorados (com aviso no log).
- **Tesseract** com o idioma `por`. Defina `TESSERACT_CMD` se não estiver no PATH.
- **Poppler** (usado pelo `pdf2image`). No Windows, defina `POPPLER_PATH` com a pasta `bin`.

### Variáveis de ambiente

```bash
cp .env.example .env     # Windows: copy .env.example .env
```

Preencha o `.env`:

| Variável | Descrição |
|---|---|
| `SUPABASE_URL` | URL do projeto Supabase |
| `SUPABASE_SERVICE_KEY` | Chave `service_role` (somente backend; nunca no front-end) |
| `OLLAMA_URL` / `OLLAMA_MODEL` | Endpoint e modelo do Ollama |
| `SMTP_SERVIDOR` / `SMTP_PORTA` / `SMTP_REMETENTE` | Relay de e-mail |

### Banco de dados

Execute no SQL Editor do Supabase, nesta ordem:

```sql
-- Passo 2
ALTER TABLE editais ADD COLUMN IF NOT EXISTS texto_extracao text;
```

E o conteúdo de `sql/004_relatorio_semanal.sql` (colunas `concluido_em` e `ultima_semana_enviada`; **rode antes de subir o novo `ai_engine.py`**) e de `sql/002_tentativas_e_fim_projeto.sql` (colunas `tentativas`, `erro_detalhe`, `fim_projeto` e padronização de `prazo_iso` para NULL).

---

## Execução

```bash
python main.py
```

A cada 2 horas (`INTERVALO_SEGUNDOS` em `main.py`) o robô executa o ciclo abaixo.

## Fluxo interno

1. **Limpeza** (`db_cleaner`): editais com prazo anterior a hoje recebem status `expirado`.
2. **Raspagem** (`portais/`): cada portal localiza URLs novas. Para cada edital, o texto da página e o dos PDFs anexos mais relevantes (até `MAX_PDFS_POR_EDITAL`; resultados, atas e cartilhas são ignorados) são gravados em `texto_extracao`, separados por linhas `=== FONTE: ... ===`. O registro nasce `PENDENTE`.
3. **Esteira de IA** (`ai_engine`): o Ollama lê `texto_extracao` (limitado a `MAX_CHARS_TEXTO_IA` caracteres; o orçamento é dividido entre página e PDFs, mantendo início e fim de cada fonte) e devolve JSON. A resposta passa por `ai_validator` (tipos, datas, tags) antes de ir ao banco, e o status vira `CONCLUIDO`. O texto bruto é mantido para reprocessamento.
4. **Retrabalho**: editais com `erro_sem_texto` são raspados de novo pelo `recuperar` do respectivo portal.
5. **Tentativas**: cada falha de scraping ou de IA incrementa `tentativas`. Ao atingir `MAX_TENTATIVAS` (padrão 3) o status vira `falha_definitiva` e o edital sai da fila; o motivo fica em `erro_detalhe`. Se o Ollama estiver fora do ar, a fila é interrompida sem gastar tentativas.
6. **Prazo**: apenas o prazo de *submissão* (`prazo_iso`) define se o edital venceu. Prazo desconhecido fica `NULL`; o fim do projeto fica em `fim_projeto`.

### Status de `editais.status_ia`

`PENDENTE` · `erro_sem_texto` · `erro_ia` · `CONCLUIDO` · `descartado_vencido` · `falha_definitiva` · `expirado`
7. **Relatório semanal** (`reporter` + `agenda_relatorio`): **toda segunda às 07:00** (horário da máquina; ajustável por `REPORT_DIA_SEMANA/HORA/MINUTO`). Roda numa **thread própria**, que confere a agenda a cada 30 s, independente do ciclo de scraping/IA de 2 em 2 horas, então um ciclo longo nunca atrasa nem pula o envio. Todos os assinantes pendentes recebem **ao mesmo tempo** (até `REPORT_MAX_PARALELO` envios simultâneos; cada um com seu filtro de tags). Cada relatório cobre os editais concluídos em `[segunda anterior 07:00, segunda 07:00)` (coluna `concluido_em`), sem buracos nem repetição. Se o robô estiver desligado na segunda, o envio acontece assim que ele voltar, com a mesma janela. `ultima_semana_enviada` controla a agenda; o envio manual da UI não a altera. Assinante novo entra na agenda e recebe a partir da segunda seguinte. Falhas de SMTP: até 3 tentativas por semana, com 10 min de intervalo.

## Segurança

- O `.env` está no `.gitignore`. Nunca faça commit de chaves.
- Se alguma chave já foi publicada em repositório, **revogue/rotacione** no painel do Supabase.
- O robô usa `service_role`; o front-end (UI) deve usar apenas a chave publishable com RLS permitindo somente `SELECT`.