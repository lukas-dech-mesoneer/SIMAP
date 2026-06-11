# SIMAP Agent

Dieses Projekt ruft aktuelle Ausschreibungen aus [SIMAP](https://simap.ch) ab, bewertet sie mit Azure OpenAI fuer mesoneer und postet passende Projekte nach Slack. Interessante Projekte koennen in Slack markiert und anschliessend als detaillierte SCOTSMAN Bid-Qualifizierung analysiert werden.

## Komponenten

- `azure_func_simap_agent`: Timer Function fuer den taeglichen SIMAP-Lauf.
- `slack_interaction`: HTTP Function fuer Slack Button-Klicks.
- `simap_interaction_worker`: Queue Worker fuer Feedback-Thread-Updates.
- `simap_analysis_worker`: Queue Worker fuer die Detailanalyse nach Klick auf `Analyse starten`.
- `simap_agent`: Shared Python Package fuer SIMAP API, OpenAI-Enrichment, Slack-Formatierung, Storage und Reports.

## Installation

```bash
pip install -r requirements.txt
```

## Lokale Nutzung

```bash
python -m simap_agent
```

Der lokale Lauf liest `.env`, ruft SIMAP-Projekte ab, dedupliziert bereits gepostete Projekte, bewertet die Details mit Azure OpenAI und postet passende Ergebnisse an Slack. Laufstatus wird lokal standardmaessig in `posted_projects.json` gespeichert; diese Datei ist bewusst ignoriert.

## Konfiguration

Erforderliche Variablen:

- `SLACK_WEBHOOK_URL`: Slack Incoming Webhook fuer Projektposts.
- `OPENAI_API_KEY`: Azure OpenAI API Key.

Empfohlene Azure Function App Settings:

- `AzureWebJobsStorage`: Storage fuer Timer State, Queues, Feedback, Projektkontexte und Analyseartefakte.
- `SLACK_SIGNING_SECRET`: Slack App Signing Secret fuer Request-Validierung.
- `SLACK_BOT_TOKEN`: Slack Bot Token mit `chat:write` fuer Thread-Antworten und Analyse-Updates.
- `AZURE_OPENAI_ENDPOINT`: Azure OpenAI Endpoint.
- `AZURE_OPENAI_DEPLOYMENT`: Deployment-Name, z.B. `gpt-5`.
- `OPENAI_API_VERSION`: API-Version, Standard `2024-12-01-preview`.
- `CPV_CODES`: Kommagetrennte CPV-Codes, Standard `48000000,72000000`.
- `APPLY_SCORE_THRESHOLD`: Mindestscore fuer Slack-Posts, Standard `6`.
- `POSTED_PROJECTS_RETENTION_DAYS`: Aufbewahrung fuer Deduplikationskeys, Standard `365`.
- `DEDUPLICATION_SCOPE`: `project` oder `publication`, Standard `project`.
- `INTERNAL_REFERENCE_PACK_FILE`: Pfad zum internen Referenz-Pack, Standard `internal_reference_pack.md`.

Nur fuer gezielte Tests oder manuelle Replays:

- `REPOST_ALREADY_POSTED=true`: postet auch bereits bekannte Projekte erneut.
- `POST_BELOW_THRESHOLD=true`: postet auch Projekte unterhalb des Mindestscore.

Diese beiden Test-Modi sollten in Produktion deaktiviert bleiben, weil sie den Timer-Lauf stark verlaengern und Duplikate erzeugen koennen.

## Deduplikation und Storage

Bereits erfolgreich an Slack gesendete SIMAP-Projekte werden in `POSTED_PROJECTS_FILE` gespeichert. Lokal ist der Standard `posted_projects.json`; in Azure Functions wird standardmaessig `$HOME/data/posted_projects.json` verwendet. Standardmaessig wird per `projectId` dedupliziert. Mit `DEDUPLICATION_SCOPE=publication` kann jede neue SIMAP-Publikation eines Projekts separat gepostet werden.

Gepostete Projektkontexte werden in Azure Blob Storage unter `simap-projects/<project_id>.json` abgelegt. Detailanalysen werden im Container `simap-analysis-results` als JSON, HTML und DOCX gespeichert.

## Slack Interactivity

Slack Button-Klicks werden von dieser Azure Function verarbeitet:

```text
https://dataai-func-weu-001.azurewebsites.net/api/slack-interaction
```

`Interessant` und `Nicht interessant` speichern Feedback. `Analyse starten` legt eine Nachricht in die Queue `simap-analysis-requests`; `simap_analysis_worker` erstellt daraus eine SCOTSMAN-Analyse und postet das Ergebnis zurueck in den Slack-Thread.

Lokal kann Feedback statt in Azure Storage in eine Datei geschrieben werden:

```text
SIMAP_FEEDBACK_FILE=feedback.jsonl
```

## Interner Referenz-Pack

Die Detailanalyse nutzt den monatlich gepflegten internen Referenz-Pack `internal_reference_pack.md`, falls vorhanden. Der Prompt fuer Microsoft 365 Copilot zum Erstellen dieses Packs liegt in `docs/copilot_monthly_reference_pack_prompt.md`.

## Deployment

Das Projekt laeuft in der Azure Function App `dataai-func-weu-001`. Der Timer ist in `azure_func_simap_agent/function.json` definiert:

```json
"schedule": "0 0 5 * * *"
```

Die Azure Functions Timer Schedule ist UTC-basiert. Das entspricht 07:00 in der Schweiz waehrend Sommerzeit und 06:00 waehrend Winterzeit.

Deployment mit Azure Functions Core Tools:

```bash
func azure functionapp publish dataai-func-weu-001 --python
```

Publish Profiles, lokale State-Dateien und `.env` duerfen nicht committed werden.

## Tests

```bash
python -m pytest -q
python -m compileall -q simap_agent azure_func_simap_agent simap_analysis_worker simap_interaction_worker slack_interaction
```
