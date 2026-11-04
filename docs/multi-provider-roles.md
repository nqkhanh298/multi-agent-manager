# AI providers by role

The dashboard section **AI cho từng vai trò** configures Coordinator, Researcher, Architect, Designer, Developer, QA, Writer, and Release independently. Each role keeps its repository skill and receives prior role handoffs. New runs snapshot the eight provider/model assignments at creation; editing settings later does not change a running project. The target selector uses Coordinator's provider and model.

- **Codex** uses the connected ChatGPT account through Codex app-server. The model field can be left blank to use that account's default, or set to a model ID from `model/list`.
- **Claude** uses a Claude API key and the Messages API. The role's skill is sent as system instructions; the selected model ID is sent in `model`.
- **Gemini** uses a Gemini API key and `models.generateContent`. The role's skill is sent as system instructions; the selected model ID is used in the URL.

Provider requests follow the [Codex app-server model selection](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server), [Claude Messages API](https://platform.claude.com/docs/en/api/messages/create), and [Gemini generateContent API](https://ai.google.dev/api/generate-content) documentation.

Claude and Gemini keys are entered in the dashboard, stored under ignored `.local/platform/ai-accounts/<user-id>/` with owner-only file permissions, and never included in the role settings response, events, generated source, or ZIP. The API returns only whether a key is present. Removing a key prevents its assigned roles from starting in new runs. A run already queued still needs that key when its role executes.

The model fields accept IDs from the providers' model catalogs, which the dashboard can fetch after connection. A listed model is not a guarantee that the account can use it; a provider request verifies access. The task graph and inspector show the provider and configured model. For Codex with no explicit model, the graph says `mặc định` rather than claiming a specific model.

Provider keys can incur provider charges. This local implementation limits each generated response to 4,096 tokens for briefs or 16,000 tokens for structured developer/selector output, and a network request to 120 seconds. It does not yet calculate provider-specific USD spend or enforce a USD ceiling on external API calls. Set account-side usage limits with each provider before assigning paid models.

## Verification

Unit tests cover exact role configuration, protected key files, API payload construction for Claude and Gemini, Codex model selection, mixed-provider role dispatch, and runs with no Codex role. Browser tests cover choosing and saving a model. The current local suite passed 63 Python tests, 3 frontend unit tests, 11 fixture browser tests, and a production frontend build. Live Claude and Gemini inference requires the user's keys and has not been run in this repository.
