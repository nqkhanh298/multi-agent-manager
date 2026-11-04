# Codex models by role

The platform uses Codex for all eight specialist roles: Coordinator, Researcher, Architect, Designer, Developer, QA, Writer, and Release. Each role has its own skill instructions and Codex thread. All roles use the same connected ChatGPT account, while their model choices can differ.

Connect ChatGPT in the dashboard, open **Model Codex theo vai trò**, select models, and save. **Mặc định tài khoản** leaves model selection to Codex. A new run snapshots these assignments; changing settings later does not change an existing run. The automatic target selector uses Coordinator's model. The dashboard fetches available model IDs through Codex app-server `model/list` and sends each chosen model to `thread/start`.

The local platform token authenticates dashboard requests. Codex sign-in is scoped to the local platform user. No external provider API keys are needed or accepted. Previously saved non-Codex role assignments reset to the Codex default when settings are read. Existing Codex model choices are retained.

This remains a local prototype. The preview currently supports generated browser apps and Python terminal programs. Native desktop apps, arbitrary stacks, and live remote deployment are outside the current scope.

Reference: [Codex app-server protocol](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server).
