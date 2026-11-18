# Questão Viva — Backend

API FastAPI + scrapers de provas.

## API (MVP)

```powershell
cd questoes-backend
# use o venv da raiz: ..\venv\Scripts\activate
pip install -r requirements.txt
python -m app.seed
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- `GET /health`
- `GET /questoes?page=1&page_size=10&banca=FUVEST&area=Matemática`
- `GET /questoes/{id}`
- `GET /filtros`
- Docs: http://localhost:8000/docs

---

# Pipeline (scrape + parse)

Pacote `pipeline/` que orquestra os scrapers existentes e extrai questões dos PDFs.

Os scripts `scraper_fgv.py`, `scraper_cebraspe.py` e `scraper_pci_vunesp.py` **continuam na raiz** — o pipeline só os chama.

```powershell
cd questoes-backend
..\venv\Scripts\activate
pip install -r requirements.txt

# Só baixar provas (repassa --limit / --dry-run / --skip-upload ao scraper)
python -m pipeline scrape --banca fgv --limit 5 --skip-upload

# Só ler PDFs já baixados → JSON em data/questoes/ + upsert no SQLite
python -m pipeline parse --banca cebraspe --limit 10

# Importar JSON(s) já parseados (formato grupos Cebraspe ou flat) → SQLite
python -m pipeline load-json data/questoes/cebraspe

# Só JSON (sem gravar no banco)
python -m pipeline parse --banca fgv --limit 3 --skip-db

# Scrape + parse
python -m pipeline run --banca vunesp --limit 3 --skip-upload
```

Bancas: `fgv`, `cebraspe`, `vunesp`.

Saída do parse:

| Destino | Conteúdo |
| --- | --- |
| `data/questoes/{banca}/{id}.json` | Questões extraídas (backup local) |
| `data/questoes/{banca}/_index.json` | Índice das provas processadas |
| `questoes.db` | Upsert no modelo `Questao` da API |

Nesta etapa **não** há upload do conteúdo parseado para o B2.

Estrutura:

```
pipeline/
  scrape/     # dispara scraper_*.py
  parse/      # pdf_reader + parsers por banca
  storage/    # JSON local + SQLite
```

---

# Scrapers de provas

Scripts para baixar provas objetivas e gabaritos de três fontes:

| Script | Fonte | Pasta de saída |
| --- | --- | --- |
| `scraper_fgv.py` | [conhecimento.fgv.br](https://conhecimento.fgv.br/concursos) | `provas_fgv/` |
| `scraper_cebraspe.py` | [cebraspe.org.br](https://www.cebraspe.org.br) | `provas_cebraspe/` |
| `scraper_pci_vunesp.py` | [PCI Concursos – VUNESP](https://www.pciconcursos.com.br/provas/vunesp) | `provas_vunesp/` |

Todos geram PDFs nomeados + `provas.json`, `indice.csv` e `indice.json` no mesmo padrão.

---

## Instalação (primeira vez)

### 1. Criar ambiente virtual (recomendado)

```powershell
cd questoes-backend
# venv na raiz do monorepo:
..\venv\Scripts\activate
# ou: python -m venv venv && .\venv\Scripts\activate
pip install -r requirements.txt
```

> Pastas de saída dos scrapers ficam em `questoes-backend/provas_fgv`, `provas_cebraspe`, `provas_vunesp`.

### 2. Instalar dependências (já coberto acima)

```powershell
pip install -r requirements.txt
```

### 3. Instalar navegadores do Playwright (obrigatório para VUNESP/PCI)

O `pip install playwright` instala só o pacote Python. Os navegadores são baixados separadamente:

```powershell
python -m playwright install firefox
```

Ou use o atalho:

```powershell
setup.bat
```

> **Windows:** sempre ative o venv (`.\venv\Scripts\activate`) antes de rodar os scripts.

---

## Scraper FGV — `scraper_fgv.py`

Baixa provas objetivas e gabaritos oficiais da FGV.

### Passo a passo

1. Ative o venv (se estiver usando).
2. Rode o scraper:

```powershell
python scraper_fgv.py
```

3. Aguarde o download. Os PDFs e o JSON aparecem em `provas_fgv/`.

### Comandos úteis

```powershell
# Só um concurso (slug da URL, ex.: /concursos/csjt23)
python scraper_fgv.py --slug csjt23

# Limitar quantidade de concursos
python scraper_fgv.py --limit 10

# Simular sem baixar PDFs
python scraper_fgv.py --dry-run

# Regenerar provas.json a partir do índice existente
python scraper_fgv.py --rebuild-json

# Outra pasta de destino
python scraper_fgv.py --out ./minha_pasta

# Scraping sem enviar ao Backblaze B2
python scraper_fgv.py --skip-upload
```

Arquivos que já existem na pasta de destino **não são baixados novamente**.

Ao final do scrape (exceto `--dry-run` / `--skip-upload`), os arquivos sobem automaticamente para o bucket B2 no prefixo `fgv/`.

---

## Upload Backblaze B2 — `b2_upload.py`

Configure `questoes-backend/.env` (veja `.env.example`):

```env
B2_KEY_ID=...
B2_APPLICATION_KEY=...
B2_BUCKET_NAME=provas
B2_ENDPOINT=https://s3.us-west-004.backblazeb2.com
```

Os scrapers já chamam o upload no final. Para enviar tudo de uma vez sem scrapar:

```powershell
python b2_upload.py
# ou uma pasta:
python b2_upload.py provas_fgv
```

Mapeamento pasta → prefixo no bucket: `provas_fgv`→`fgv/`, `provas_cebraspe`→`cebraspe/`, `provas_vunesp`→`vunesp/`.

### Saída (`provas_fgv/`)

| Arquivo | Conteúdo |
| --- | --- |
| `*.pdf` | Cadernos (Tipo 1–4) e gabaritos |
| `provas.json` | Metadados agrupados por cargo/ano |
| `indice.csv` | Mesmos dados em planilha |
| `indice.json` | Versão plana do índice |

---

## Scraper Cebraspe — `scraper_cebraspe.py`

Baixa provas objetivas e gabaritos definitivos do Cebraspe.

### Passo a passo

1. Ative o venv (se estiver usando).
2. Rode o scraper:

```powershell
python scraper_cebraspe.py
```

3. Aguarde o download. Os arquivos vão para `provas_cebraspe/`.

### Comandos úteis

```powershell
# Só um concurso (ex.: AEB_24)
python scraper_cebraspe.py --slug AEB_24

# Limitar quantidade
python scraper_cebraspe.py --limit 10

# Simular sem baixar
python scraper_cebraspe.py --dry-run

# Regenerar JSON a partir do índice
python scraper_cebraspe.py --rebuild-json

# Outra pasta de destino
python scraper_cebraspe.py --out ./minha_pasta
```

### Saída (`provas_cebraspe/`)

Mesma estrutura da FGV: PDFs + `provas.json` + `indice.csv` + `indice.json`.

---

## Scraper VUNESP (PCI Concursos) — `scraper_pci_vunesp.py`

Baixa provas e gabaritos VUNESP listados no PCI Concursos.  
O site usa **Cloudflare Turnstile** (captcha), então o fluxo tem uma etapa extra para obter o token.

### Visão geral do fluxo

```
get_pci_token.py  →  turnstile_token.txt  →  scraper_pci_vunesp.py  →  PDFs + provas.json
```

### Passo a passo completo

#### Etapa 1 — Obter o token Turnstile

```powershell
python get_pci_token.py --firefox
```

- Roda em modo **headless** (sem janela) por padrão.
- Salva o token em `provas_vunesp/turnstile_token.txt`.
- Salva cookies em `provas_vunesp/browser_cookies.json`.

Se o captcha não passar em headless, abra o navegador visível:

```powershell
python get_pci_token.py --firefox --visible
```

Resolva o captcha na janela e aguarde a mensagem **"Token salvo"** antes de fechar.

Alternativas para o token:

```powershell
# Google Chrome instalado
python get_pci_token.py --chrome --visible

# Chrome já aberto com depuração remota
# 1) Feche o Chrome e abra:
#    "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
# 2) Depois:
python get_pci_token.py --connect-cdp http://127.0.0.1:9222
```

#### Etapa 2 — Baixar todas as provas

```powershell
python scraper_pci_vunesp.py --turnstile-token-file provas_vunesp/turnstile_token.txt
```

O scraper:
1. Carrega a listagem de `provas_vunesp/provas_list.json` (~4940 provas).
2. Abre Firefox headless com o token e a sessão salvos.
3. Baixa prova + gabarito de cada URL.
4. Gera `provas.json`, `indice.csv` e `indice.json`.

#### Etapa 3 — Verificar a saída

Confira a pasta `provas_vunesp/`:

```powershell
dir provas_vunesp\*.pdf
type provas_vunesp\provas.json
```

### Comandos úteis do scraper PCI

```powershell
# Só gerar/atualizar a listagem de URLs (sem baixar PDFs)
python scraper_pci_vunesp.py --list-only

# Rebuscar listagem do site
python scraper_pci_vunesp.py --list-only --refresh-list

# Processar só N provas (teste)
python scraper_pci_vunesp.py --turnstile-token-file provas_vunesp/turnstile_token.txt --limit 5

# Uma prova específica
python scraper_pci_vunesp.py --url "https://www.pciconcursos.com.br/provas/download/2-tenente-dentista-policia-militar-sp-vunesp-2009" --turnstile-token-file provas_vunesp/turnstile_token.txt

# Simular sem baixar PDFs
python scraper_pci_vunesp.py --dry-run --limit 10

# Navegador visível (se headless falhar)
python scraper_pci_vunesp.py --turnstile-token-file provas_vunesp/turnstile_token.txt --browser-visible

# Outra pasta de destino
python scraper_pci_vunesp.py --out ./minha_pasta --turnstile-token-file provas_vunesp/turnstile_token.txt
```

### Saída (`provas_vunesp/`)

| Arquivo | Conteúdo |
| --- | --- |
| `*.pdf` | Provas e gabaritos nomeados por órgão/ano/cargo |
| `provas.json` | Metadados agrupados |
| `indice.csv` / `indice.json` | Índice plano |
| `provas_list.json` | Cache da listagem de URLs |
| `links_cache.json` | Cache de links PDF já resolvidos |
| `turnstile_token.txt` | Token do captcha (gerado por `get_pci_token.py`) |
| `browser_cookies.json` | Cookies da sessão do navegador |
| `firefox_profile/` | Perfil persistente do Firefox |

---

## Script auxiliar — `get_pci_token.py`

Abre uma página de prova no PCI, aguarda o Turnstile e salva o token para uso no scraper.

| Flag | Descrição |
| --- | --- |
| `--firefox` | Usa Firefox (recomendado) |
| `--chrome` | Usa Google Chrome instalado |
| `--visible` | Abre janela do navegador (para resolver captcha manualmente) |
| `--connect-cdp URL` | Conecta a um Chrome já aberto |
| `--url URL` | Página de prova usada para obter o token |
| `--timeout N` | Tempo máximo de espera em segundos (padrão: 300) |

---

## Script auxiliar — `setup.bat`

Instala dependências e o Firefox do Playwright de uma vez:

```powershell
setup.bat
```

Equivalente a:

```powershell
pip install -r requirements.txt
python -m playwright install firefox
```

---

## Problemas comuns

### `Executable doesn't exist at ... firefox.exe`

O navegador do Playwright não foi instalado. Rode:

```powershell
python -m playwright install firefox
```

### Token obtido, mas PDFs não baixam

O token precisa da sessão do navegador. Use sempre:

```powershell
python scraper_pci_vunesp.py --turnstile-token-file provas_vunesp/turnstile_token.txt
```

Se falhar, regenere o token com `--visible`:

```powershell
python get_pci_token.py --firefox --visible
```

### Captcha detecta automação

- Prefira `--firefox --visible` ou `--connect-cdp` com Chrome real.
- Evite headless na **primeira** obtenção do token.
- O perfil persistente em `provas_vunesp/firefox_profile/` ajuda nas execuções seguintes.

---

## Formato do JSON

Cada item de `provas.json` segue o padrão:

- `id`: `ORGAO-ANO-Cargo`
- `variacao_prova`: lista com PDF da prova e gabarito aninhado
- `banca`, `orgao_abreviado`, `link_acesso`, `ano`, `cargo`, etc.

Sentença e discursiva não entram nos scrapers FGV e Cebraspe.
