# SIMAP Agent

Dieses Projekt automatisiert das Abrufen und Aufbereiten von Ausschreibungen aus [SIMAP](https://simap.ch). Die Daten werden mit Hilfe von Azure OpenAI angereichert und anschliessend als formatierte Nachrichten an Slack gesendet.

## Installation
```bash
pip install -r requirements.txt
```

## Konfiguration
`.env`-Datei beinhaltet folgende Variablen :

- `SLACK_WEBHOOK_URL` – Slack Incoming Webhook
- `OPENAI_API_KEY` – Azure OpenAI API key
- Optional: `AZURE_OPENAI_ENDPOINT`, `OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`, `SIMAP_BASE_URL`, `SIMAP_SEARCH_ENDPOINT`, `SIMAP_DETAIL_ENDPOINT_TEMPLATE`, `COMPANY_PROFILE_FILE`, `CPV_CODES`, `APPLY_SCORE_THRESHOLD`, `POSTED_PROJECTS_FILE`, `DEDUPLICATION_SCOPE`, `POSTED_PROJECTS_RETENTION_DAYS`

Bereits erfolgreich an Slack gesendete SIMAP-Projekte werden in `POSTED_PROJECTS_FILE` gespeichert, damit der taegliche Lauf keine Duplikate postet. Lokal ist der Standard `posted_projects.json`; in Azure Functions wird standardmaessig `$HOME/data/posted_projects.json` verwendet. Standardmaessig wird per `projectId` dedupliziert. Mit `DEDUPLICATION_SCOPE=publication` kann stattdessen jede neue SIMAP-Publikation eines Projekts separat gepostet werden. Alte Eintraege werden nach `POSTED_PROJECTS_RETENTION_DAYS` Tagen entfernt; Standard ist `365`.

`APPLY_SCORE_THRESHOLD` steuert, ab welchem Score ein Projekt an Slack gesendet wird. Standard ist `6`; Projekte darunter werden als wahrscheinlich nicht relevant verworfen.

Standardwerte für `AZURE_OPENAI_ENDPOINT` und `OPENAI_API_VERSION` sind bereits hinterlegt.


## Nutzung
```bash
python -m simap_agent
```
Das Skript ruft aktuelle Projekte ab, nutzt Azure OpenAI zur Anreicherung und postet die Ergebnisse in Slack. Die angereicherten Daten werden ebenfalls in `enriched_projects.json` geschrieben.

## Deployment
Das Projekt läuft in einer Azure Function, die nach einem täglich um 7:00 nach einen festen Zeitplan ausgeführt wird:

```
<AZURE_FUNCTION_APP_NAME_PLACEHOLDER>
```

Die Umgebungsvariablen sind ebenfalls in Azure Function konfiguriert.

### Slack Button Interactivity

Slack Button-Klicks werden von dieser Azure Function verarbeitet:

```text
https://dataai-func-weu-001.azurewebsites.net/api/slack-interaction
```

Erforderliche App Settings:

- `SLACK_SIGNING_SECRET` - Slack App Signing Secret zur Request-Validierung
- `AzureWebJobsStorage` - wird fuer `simap-feedback/feedback.jsonl` verwendet

Optional fuer Thread-Antworten und den Button `Analyse starten`:

- `SLACK_BOT_TOKEN` - Slack Bot Token mit Scope `chat:write`

`Analyse starten` legt einen Job in die Storage Queue `simap-analysis-requests`.
Die Queue Function `simap_analysis_worker` erstellt daraus eine Detailanalyse und postet das Ergebnis zurueck in den Slack-Thread.
Gepostete Projektkontexte werden in `simap-projects/<project_id>.json` gespeichert.
Die Detailanalyse nutzt zusaetzlich den monatlich gepflegten internen Referenz-Pack `internal_reference_pack.md`, falls vorhanden.
Der Prompt fuer Microsoft 365 Copilot zum Erstellen dieses Packs liegt in `docs/copilot_monthly_reference_pack_prompt.md`.
Alternativ kann der Pfad ueber `INTERNAL_REFERENCE_PACK_FILE` gesetzt werden.

Lokal kann Feedback statt in Azure Storage in eine Datei geschrieben werden:

```text
SIMAP_FEEDBACK_FILE=feedback.jsonl
```
