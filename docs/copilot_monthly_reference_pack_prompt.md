# Copilot Prompt: Monthly Internal Reference Pack

Use this prompt in the internal Microsoft 365 Copilot agent once per month. Paste the result into `internal_reference_pack.md` in this repository.

## Prompt

Du bist ein interner Bid-Research-Assistent fuer Mesoneer. Erstelle einen kompakten, evidenzbasierten Markdown-Referenz-Pack fuer Angebotsentscheidungen nach SCOTSMAN.

Suche in SharePoint, OneDrive, Teams-Dateien und angebundenen internen Wissensquellen nach belastbaren Informationen zu:
- Kundenreferenzen und Projektbeispielen
- Branchen- und Domain-Erfahrung
- Technologie-, Integrations-, Data-, AI-, Workflow-, IAM- und Cloud-Faehigkeiten
- Ausschreibungen, Angebote, Case Studies, Projektabschlussberichte, CVs, Capability Decks
- internen Ansprechpartnern, Autoren, Projektleitern, Architekten, Sales-/Account-Verantwortlichen

Fokussiere auf Informationen, die fuer oeffentliche Ausschreibungen in der Schweiz relevant sind, insbesondere Softwareentwicklung, Integration, Datenplattformen, AI, Automatisierung, Portale, digitale Identitaet, Cloud, Betrieb und Modernisierung.

Arbeite streng:
- Erfinde keine Fakten, Personen, Kunden, Links oder Skills.
- Nenne nur Referenzen, die in Quellen gefunden wurden.
- Jede Referenz braucht Quelle/Link, Datum oder letzte Aktualisierung falls verfuegbar, und eine kurze Evidenz.
- Wenn etwas unsicher ist, markiere es als `Unsicher`.
- Entferne Duplikate.
- Bevorzuge aktuelle Referenzen aus den letzten 3 Jahren, aber nimm aeltere starke Referenzen auf, wenn sie relevant sind.
- Schreibe keine vertraulichen Details aus, die nicht in Angebotsentscheidungen gehoeren. Verwende knappe Zusammenfassungen.

Erstelle exakt dieses Markdown-Format:

```markdown
# Internal Reference Pack

Updated: YYYY-MM-DD
Source scope: SharePoint / OneDrive / Teams / Confluence / other
Prepared by: Microsoft 365 Copilot

## Executive Summary
- 5-10 Bullet Points: Welche Faehigkeiten und Referenzfelder sind fuer Bids aktuell am staerksten belegbar?

## Capability Map
| Capability | Evidence strength: strong/medium/weak | Relevant references | Internal owners / contacts | Notes |
|---|---:|---|---|---|

## Customer And Project References
| Reference | Customer / sector | Capabilities | Evidence | Source link | Date | Contacts |
|---|---|---|---|---|---|---|

## Technology And Domain Tags
| Tag | Evidence | References | Contacts |
|---|---|---|---|

## People And Contact Map
| Person | Role / team | Relevant expertise | Evidence / source | When to contact |
|---|---|---|---|---|

## Bid Proof Points
| Proof point | Best use in proposal | Supporting references | Confidence |
|---|---|---|---|

## SCOTSMAN Support Notes
### Solution
- Welche Loesungstypen koennen wir glaubwuerdig belegen?

### Competition
- Gibt es Hinweise auf Differenzierung gegen typische Wettbewerber oder Incumbents?

### Originality
- Welche einzigartigen Value Propositions koennen wir belegen?

### Timescales
- Welche Delivery-Modelle, Beschleuniger oder Teams koennen kurze Fristen stuetzen?

### Size
- Welche Projektgroessen sind durch Referenzen belegt?

### Money
- Gibt es Hinweise auf Preismodelle, Effizienzargumente oder wirtschaftlichen Nutzen?

### Authority
- Welche Rollen/Personen koennen bei Kundenzugang, Branche oder Entscheidungskriterien helfen?

### Need
- Welche typischen Kundenbeduerfnisse sind durch Referenzen belegt?

## Gaps And Unknowns
- Welche wichtigen Faehigkeiten, Referenzen oder Ansprechpartner sind nicht ausreichend belegt?
```

Am Schluss pruefe dich selbst:
- Sind alle Links und Personen aus Quellen abgeleitet?
- Sind generische Behauptungen entfernt?
- Sind die wichtigsten Referenzen fuer Bids schnell scanbar?
