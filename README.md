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
│   ├── scraper_utils.py   # Requisições, limpeza de HTML, registro no banco
│   └── document_utils.py  # Leitura de PDF (pdfminer / OCR)
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
- **pdfminer.six / pypdf / pytesseract** para PDFs

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

E o conteúdo de `sql/002_tentativas_e_fim_projeto.sql` (colunas `tentativas`, `erro_detalhe`, `fim_projeto` e padronização de `prazo_iso` para NULL).

---

## Execução

```bash
python main.py
```

A cada 2 horas (`INTERVALO_SEGUNDOS` em `main.py`) o robô executa o ciclo abaixo.

## Fluxo interno

1. **Limpeza** (`db_cleaner`): editais com prazo anterior a hoje recebem status `expirado`.
2. **Raspagem** (`portais/`): cada portal localiza URLs novas; o texto bruto vai para `texto_extracao` e o registro nasce com status `PENDENTE`.
3. **Esteira de IA** (`ai_engine`): o Ollama lê `texto_extracao` (limitado a `MAX_CHARS_TEXTO_IA` caracteres, mantendo início e fim) e devolve JSON. A resposta passa por `ai_validator` (tipos, datas, tags) antes de ir ao banco, e o status vira `CONCLUIDO`. O texto bruto é mantido para reprocessamento.
4. **Retrabalho**: editais com `erro_sem_texto` são raspados de novo pelo `recuperar` do respectivo portal.
5. **Tentativas**: cada falha de scraping ou de IA incrementa `tentativas`. Ao atingir `MAX_TENTATIVAS` (padrão 3) o status vira `falha_definitiva` e o edital sai da fila; o motivo fica em `erro_detalhe`. Se o Ollama estiver fora do ar, a fila é interrompida sem gastar tentativas.
6. **Prazo**: apenas o prazo de *submissão* (`prazo_iso`) define se o edital venceu. Prazo desconhecido fica `NULL`; o fim do projeto fica em `fim_projeto`.

### Status de `editais.status_ia`

`PENDENTE` · `erro_sem_texto` · `erro_ia` · `CONCLUIDO` · `descartado_vencido` · `falha_definitiva` · `expirado`
7. **Relatórios** (`reporter`): para cada assinante em `configuracoes_relatorio` com 7+ dias desde o último envio, os editais novos são filtrados por tags e enviados em HTML.

## Segurança

- O `.env` está no `.gitignore`. Nunca faça commit de chaves.
- Se alguma chave já foi publicada em repositório, **revogue/rotacione** no painel do Supabase.
- O robô usa `service_role`; o front-end (UI) deve usar apenas a chave publishable com RLS permitindo somente `SELECT`.