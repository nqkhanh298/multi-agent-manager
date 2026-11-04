# Codex models by role

The platform has eight available Codex specialist roles: Coordinator, Researcher, Architect, Designer, Developer, QA, Writer, and Release. Coordinator chooses a suitable subset for each prompt. Each selected role has its own skill instructions and Codex thread. All roles use the same connected ChatGPT account, while their model choices can differ.

Connect ChatGPT in the dashboard, open **Model Codex theo vai trò**, select models, and save. **Mặc định tài khoản** leaves model selection to Codex. A new run snapshots these assignments; changing settings later does not change an existing run. Coordinator uses its configured model to choose the output and agent team. The dashboard fetches available model IDs through Codex app-server `model/list` and sends each chosen model to `thread/start`.

Each workflow block shows its model prominently. Before a role starts, the block shows the configured model or says that the default model is still being resolved. When Codex opens the role's thread, the platform records the actual model returned by `thread/start` and replaces the block's planned label with that model. Older runs that did not record the actual default are marked as unrecorded rather than assigned a guessed model.

For an explicitly configured model, the app-server adapter compares the model requested in `thread/start` with the model returned in the thread. If they differ or the response omits the model, the role stops and the run reports the mismatch instead of claiming to use the configured model.

The local platform token authenticates dashboard requests. Codex sign-in is scoped to the local platform user. No external provider API keys are needed or accepted. Previously saved non-Codex role assignments reset to the Codex default when settings are read. Existing Codex model choices are retained.

This remains a local prototype. The preview supports generated browser apps, Python terminal programs, and Markdown research reports. Native desktop apps, arbitrary stacks, and live remote deployment are outside the current scope.

Reference: [Codex app-server protocol](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server).
