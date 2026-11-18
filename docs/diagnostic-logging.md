# Diagnostic Logging

In the WebUI, choose the log level under **Settings → Interface Settings → Diagnostic Logging**, optionally enable
**Log API request parameters**, and click **Apply Logging Settings**. The settings apply immediately to the current service,
including later logs of running tasks; all browser sessions of the same service share the setting.
Enabling "Hide logs" only hides logs in the UI and doesn't turn off terminal output.

The API, CLI and WebUI use the same config:

```toml
[diagnostics]
log_level = "INFO"
log_requests = false
```

`log_level` can be TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR or CRITICAL.
When omitted, the original top-level `log_level` is used, defaulting to DEBUG. Manual file edits require a restart;
"Apply" in the WebUI only updates the current process immediately and doesn't remotely change other API or CLI processes.

Request tracing is a separate switch and can be enabled even at the ERROR level. It's off by default and records:

- Request ID, HTTP method, redacted URL, and length-limited request parameters.
- Response status (when available), duration, or the exception type on failure.
- LLM SDK call parameters. These are the SDK's inputs, not the raw JSON the SDK finally sends;
  automatic retries inside the SDK aren't shown individually. The duration of streaming requests only counts until the response or stream object is obtained,
  excluding later download time.

It covers the material, video, voice, publishing and login requests the project makes explicitly with `requests`, as well as
OpenAI-compatible, Azure OpenAI, Qwen, Gemini and LiteLLM script calls.
It doesn't capture the browser's own network traffic, inbound API bodies, CLI subprocesses, Edge TTS WebSocket
or other SDK-internal transport. Normal application logs and third-party SDKs' own log levels are not controlled by the same switch.

Request headers, response bodies and uploaded file contents are never logged. Keys, tokens, cookies, passwords and signature
fields are masked, URL query parameter values are all hidden, and audio/video/base64 content is omitted. Raw
unstructured request bodies aren't logged. **Prompts and other business parameters may appear in the logs**, so turn tracing off
once troubleshooting is done, and still check logs for private content before sharing them. Diagnostics never send logs externally,
and never initiate, retry or replay extra requests.

CLI logs still go to stderr, and stdout stays machine-readable JSON. WebUI task logs keep the existing
thread-attribution filtering and entry limit, and switching levels doesn't remove the log handlers of running tasks.
