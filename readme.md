# NEBIX - Personal AI Intelligence

**NEBIX**  
**BY NABEENEYYY**

Creator and CEO: **Nabeen Joshi**  
Creation date: **September 16, 2026**  
Development: approximately **three and a half months**

The creation date above is static NEBIX identity information, not today's date.
NEBIX obtains the current date and time dynamically at runtime and uses the
`Asia/Kathmandu` timezone (Nepal Time, UTC+05:45) for date/time answers and
user-facing clock/status timestamps.

NEBIX is a Windows-focused personal AI assistant with a real-time Gemini Live voice experience, text Chat, local memory, computer actions, system monitoring, and a remote-control dashboard. Its settings keep Global, Voice, Chat, and Settings appearance choices independent.

## Capabilities

| Area | Current functionality |
| --- | --- |
| Live Voice | Gemini Live audio input/output, six built-in voices, wake-word support, transcription, and session resumption |
| AI Providers | Gemini, OpenAI, Anthropic, Groq, and OpenRouter for Chat |
| Chat | Text conversations and supported image/text attachments on the selected provider |
| Voice | Gemini Live speech generation with six selectable Gemini voices |
| Appearance | One Settings > Appearance hub for Global/App, Voice Interface, Chat, and Settings themes |
| Chat Themes | Fourteen built-in themes, custom themes, wallpapers, editor preview, favorites, filters, and persistence |
| Voice Interfaces | Four layouts: Arc Reactor, Red Cyberpunk HUD, Holographic Projector, and Cyan/Gold Radial |
| Memory | Local long-term memory, session summaries, topic monitoring, and memory search/edit controls |
| Actions | Discovered tools for files, apps, browser, desktop, system settings, weather, web search, flights, games, code, messages, and media; shared active-context UI automation |
| Engineering tasks | Shared voice/Chat task engine for bounded project inventory, Python/JSON static diagnostics, task state, and opening already-installed VS Code or Android Studio |
| Remote Control | Paired browser dashboard for commands, status, and file sharing |
| Windows Integration | Desktop/Start shortcuts, optional startup launch, audio-device selection, and PyInstaller deployment artifacts |

Alternate AI adapters currently provide **Chat only**. They do not replace Gemini Live audio, realtime voice, NEBIX tool/function calling, or streaming. Gemini remains the provider for NEBIX Live and its existing realtime voice features.

## Appearance

Open **Settings > Appearance** to manage all visual themes:

- **Global / App:** NEBIX Default, Midnight, Cyber Cyan, Crimson, Aurora, or Light.
- **Voice Interface:** the existing four presentation layouts and their current customization controls.
- **Chat:** the existing gallery and custom theme editor, including wallpaper and bubble controls.
- **Settings:** Light, Midnight, Cyber Cyan, Crimson, or Aurora Glass.

These preferences are independent. The legacy dark/light preference is migrated into the Global theme when necessary; existing Voice and Chat selections are retained. UI settings are validated and persisted by the shared Settings Manager in `data/ui_settings.json`; provider credentials and provider/model selection remain in `config/api_keys.json`.

Manual Settings controls and voice/chat setting commands use the same Settings Manager and registry. Supported settings are validated before persistence, and local setting and identity questions are answered from the registry and the provider-independent `config/nebix_identity.json` source.

## AI And Voice Providers

Gemini is selected by default. The AI provider settings support Google Gemini, OpenAI, Anthropic, Groq, and OpenRouter. Connecting validates the credential with the provider's real models endpoint and retrieves that account's model IDs; models are not hardcoded or manually entered. Selecting a non-Gemini provider routes Chat text and supported attachments through that provider. Voice commands and realtime speech remain on Gemini Live.

Provider keys and selected-provider/model state are stored in the existing `api_keys.json` configuration using NEBIX's secure API-key storage. On Windows, API-key values are protected with DPAPI. The UI shows only masked connection status and does not prefill saved secrets. Keep local configuration private and never commit real credentials.

NEBIX uses Gemini Live for voice input, transcription, response generation, and speech output. The selectable Gemini voices are **Zephyr, Puck, Charon, Kore, Fenrir, and Aoede**.

## Architecture

```text
main.py                    Gemini Live session, audio, actions, and runtime orchestration
web_ui.py                  pywebview bridge, settings, providers, and local UI lifecycle
interface/index.html       Main Voice/Chat UI and Settings markup
                           Includes the interface styling and JavaScript bridge logic
core/ai_providers.py       Text adapters for compatible AI providers
core/settings_manager.py  Validated settings registry, persistence, and UI synchronization
core/identity_manager.py  Provider-independent NEBIX identity source
core/action_loader.py      Discovery of built-in actions
core/plugin_loader.py      Discovery of plugins
core/engineering_agent.py  Shared session task state, project inventory, and static diagnostics
core/permissions.py        Risk tiers and confirmation decisions for registered actions
actions/engineering_task.py Voice tool entry into the shared engineering task engine
actions/                   Built-in assistant actions and tools
dashboard/                 Remote-control server and browser UI
memory/                    Configuration helpers and local memory management
config/api_keys.json       Local API keys and provider/model settings
config/nebix_identity.json Permanent NEBIX identity facts
data/ui_settings.json     Persistent manual and voice/chat UI settings
```

Gemini Live remains the realtime session used by the Voice experience. Alternate-provider Chat uses a separate asynchronous text path and session-only message history. Recognized engineering requests are routed locally through the shared Engineering Task Core before a provider response; this does not make arbitrary Chat messages desktop-tool calls.

## Engineering Task Core

Voice command/transcript text, Live voice tool calls, and Chat project-task requests share `core/engineering_agent.py`. It retains the last explicitly selected project path for the current session, exposes task state through the existing pywebview bridge, emits activity from real scan/launch events, and permits cancellation during inventory. If no project path is known, it asks for one rather than choosing an unrelated folder.

Project inventory recognizes common Python, Node, Android/Gradle, Java, Rust, Go, .NET, and C/C++ markers; collects manifests, entry points, test candidates, available tool paths, and project-declared VS Code extension recommendations; and performs bounded Python AST and JSON syntax checks. It excludes common generated/vendor folders, skips symlinks, limits traversal, and does not execute project code or change project files. A requested diagnosis reports these static findings, but does not claim that they explain an unobserved runtime failure.

Opening a project launches an already-installed IDE with the selected folder and reports process-launch evidence. It does not download/install IDEs or extensions, verify indexing/Gradle sync, or claim that the project finished loading. Requests to fix code are scanned first but end in `BLOCKED` before edits: a reviewed patch-preview/approval/apply/rollback transaction is not implemented yet. Tests and build commands are not run by a scan.

`core/permissions.py` is applied at the existing registered-action dispatch boundary. Medium-risk edits, project execution, computer/browser interaction, file operations, and plugins use the existing `confirmSensitive` preference; destructive operations and external message sending always require the on-screen confirmation, even if that preference is off. The request is not run until the user accepts the HUD confirmation. Some tools retain their own confirmation checks.

The Engineering Task Core is an initial, intentionally bounded capability—not yet a complete autonomous coding/provisioning agent. It does not apply source patches, run arbitrary project-defined tests/builds, install software/extensions/dependencies, observe installer dialogs, or provide semantic UI Automation for every application. These limitations are reported rather than simulated.

## WhatsApp Saved-Contact Verification

The WhatsApp send guard uses only visible UI Automation evidence. It does not open or close Contact info or move focus to the message composer. Sending is blocked unless the requested recipient is uniquely identified in the conversation header, Contact info already exposes an explicit saved-contact signal (`Edit contact` or `Delete contact`), the same header and saved-contact signal remain visible on revalidation, and the identified composer is already focused. If the current WhatsApp Desktop build does not expose those elements, verification fails closed; it does not use OCR, coordinates, or private application data.

## User-Controlled Long-Term Memory

Current conversation context and user-approved long-term memory are separate. Normal statements, tasks, preferences mentioned without a save request, proactive prompts, and session summaries do not create retrievable long-term facts. The model-facing save and forget operations are checked against the current completed user message; supported explicit intent includes English, Nepali, Romanized Nepali, and mixed phrasing. Only the extracted requested fact is stored, tagged `source: user_explicit`, and confirmed after disk readback succeeds. Passwords, API keys, tokens, and other detected credentials are rejected.

Saved facts are not injected as a database dump into session prompts. Gemini retrieves a specific approved fact through `recall_memory`; alternate-provider Chat handles explicit memory save/forget and relevant recall locally, without sending stored facts to that provider. A direct request to review memories returns only a bounded list of approved entries. The existing `sessions` summary list remains separate from fact retrieval, and approved facts persist in the existing `memory/long_term.json` across new chats, reconnects, and restarts.

Older memory entries without provenance are preserved in storage but are not treated as user-approved and are hidden from AI retrieval. They remain available in the existing Memory Center for the user to review and explicitly save again. Editing/saving an entry there records the approval source. This avoids silently granting approval to legacy facts whose origin cannot be verified.

## Development Setup

Developing from source requires Windows 11, Python, a microphone and speakers for Voice, and a Gemini API key from a Google project with Gemini Live access and any required billing enabled. The current development target is Python **3.14.7**, pywebview **6.2.1**, and PyInstaller **6.22.3**. Other platforms may support portions of the code, but platform-specific actions and packaging can differ.

From PowerShell in the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

`setup.py` provides the project setup flow and can install platform-specific requirements. On first launch, configure the Gemini API key in Settings. Additional text-provider keys and local endpoints are configured in their respective provider sections.

## Windows Application Packaging

Build the portable onedir application from the project root:

```powershell
.\build_nebix.bat
```

The release is `dist/NEBIX-Portable`. Keep the whole folder together when copying it to another PC; launch `NEBIX.exe` directly. The PyInstaller onedir package includes Python and application dependencies, and does not require a separately installed Python or VS Code. Windows WebView2 Runtime is an operating-system prerequisite for pywebview and may need to be installed from Microsoft's WebView2 page on older or minimal Windows installations.

To produce the normal Windows installer, install Inno Setup 6 and run the same build command. The installer definition is `installer/NEBIX.iss`; when ISCC is found in its standard Program Files location, the build creates `dist/installer/NEBIX-Setup.exe`. It installs per-user under `%LOCALAPPDATA%\Programs\NEBIX`, creates a Start Menu entry and an optional Desktop shortcut, preserves an existing startup-shortcut preference, and registers a normal Windows uninstall entry. Uninstall removes installed application files and shortcuts; NEBIX user data is preserved. Inno Setup 6.7.3 identifies its compiler as non-commercial-use-only; obtain the appropriate license or use a suitably licensed installer tool for commercial distribution.

The executable embeds `config/nebix.ico` and NEBIX version metadata. The packaging spec includes the interface, prompts, shortcut identity script, dynamic action/plugin modules, and runtime dependencies. Credentials and mutable settings/memory are not bundled; packaged builds keep them in `%LOCALAPPDATA%\NEBIX`, with API keys protected by Windows DPAPI. The current `.exe` and installer are not Authenticode-signed; production distribution should sign them with the publisher's code-signing certificate.

After building, refresh the current user's Desktop and Start Menu links to target the compiled executable directly. Existing startup status is preserved:

```powershell
.\.venv\Scripts\python.exe -c "from config.windows_shortcut import install_nebix_shortcuts; print(install_nebix_shortcuts(autostart=None))"
```

The shortcut helper refuses to create links until `dist/NEBIX-Portable/NEBIX.exe` exists; it never creates a shortcut targeting Python or a `.py` file. Startup shortcuts also launch the packaged executable.

## Security And Data

- In development, configuration is stored under the project `config` directory. Packaged builds store configuration at `%LOCALAPPDATA%\NEBIX\config\api_keys.json`; API keys are protected with Windows DPAPI.
- Provider connection tests are explicit user actions and use bounded request timeouts.
- Provider errors are sanitized to avoid returning saved API keys.
- Remote-control sessions use paired access tokens and encrypted command payloads where supported by the dashboard client.
- Long-term memory is stored in the project `memory` directory during development and `%LOCALAPPDATA%\NEBIX\memory\long_term.json` in packaged builds.
- Chat theme wallpapers are scaled/compressed before being saved in appearance settings.

## Development Status

The existing Gemini Live path, four Voice layouts, six built-in voices, Chat theme gallery/editor, Appearance settings, provider configuration, and core action/plugin architecture are implemented. Alternate AI adapters are currently text-only, and real third-party API availability depends on the user's credentials, network, endpoint, and model access. Live service calls are not run automatically at startup.

## Chat response latency diagnostics

Chat reuses the active Gemini Live session. Real output-transcription chunks are rendered as they arrive; the UI does not simulate streaming. Deterministic greetings, date/time, and polled system-metric/status queries use local replies. Stop/cancel uses the direct interrupt bridge to discard the active response and cancel queued Chat requests; the active Gemini generation may continue until the Live service completes it.

For development measurements, set `NEBIX_LATENCY_TRACE=1` before launching NEBIX. The setting enables request-stage timing in the WebView developer console and the local `startup.log` (in a frozen build, `%LOCALAPPDATA%\NEBIX\startup.log`). Timings include JavaScript submit-to-bridge, Python bridge dispatch, attachment preparation, Gemini Live send/first transcript/completion, Python-to-WebView dispatch, and total submit-to-render. Disable the environment variable for normal use.

Future work may add provider-specific streaming/tool support where the APIs and NEBIX architecture can support it safely, expand automated integration coverage, and refine cross-platform packaging.

## License

See [LICENSE](LICENSE) for the project's license terms.
