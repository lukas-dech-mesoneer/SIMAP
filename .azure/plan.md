# Azure Plan: Slack Interactivity HTTP Trigger

Status: Code Validated; Deployment Blocked by Missing Azure CLI/Az PowerShell Login

## Goal
Add a new HTTP-triggered Azure Function endpoint for Slack Block Kit button interactions in the existing Python Azure Functions app and deploy it to the existing Function App `dataai-func-weu-001`.

## Mode
MODIFY existing Azure Functions project.

## Architecture
- Existing timer function remains unchanged: `azure_func_simap_agent`.
- New HTTP function folder: `slack_interaction`.
- Route: `/api/slack-interaction`.
- Auth level: `anonymous`, because Slack cannot send Azure function keys reliably in the configured Interactivity Request URL.
- Security: verify `X-Slack-Request-Timestamp` and `X-Slack-Signature` with `SLACK_SIGNING_SECRET`.
- Processing: parse Slack form field `payload`, read `actions[0].action_id` and button `value`, return fast `200 OK`.

## Validation
- Unit tests for signature validation and payload parsing.
- Run `python -m pytest`.
- Completed: `python -m pytest` -> 15 passed.

## Deployment
- Use Azure Functions Core Tools if available: `func azure functionapp publish dataai-func-weu-001 --python`.
- If not available, report the exact command and required local tool.
- Attempted: installed Azure Functions Core Tools and ran `func.cmd azure functionapp publish dataai-func-weu-001 --python`.
- Result: blocked because this shell is not authenticated with Azure CLI or Az PowerShell.

## Slack UI Configuration
- Slack App -> Interactivity & Shortcuts -> Interactivity On.
- Request URL: `https://dataai-func-weu-001.azurewebsites.net/api/slack-interaction`.
- Basic Information -> Signing Secret must be set in Azure Function App setting `SLACK_SIGNING_SECRET`.
