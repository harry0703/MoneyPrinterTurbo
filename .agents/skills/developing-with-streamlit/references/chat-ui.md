
# Streamlit chat interfaces

Build conversational UIs with Streamlit's chat elements.

## Basic chat structure

```python
import streamlit as st

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# Handle new input
if prompt := st.chat_input("Ask a question"):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        response = get_response(prompt)  # Your LLM call
        st.write(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
```

## Streaming responses

Use `st.write_stream` for token-by-token display. Pass any generator that yields strings, including the OpenAI generator directly:

```python
def get_streaming_response(prompt):
    # Replace with your LLM client (OpenAI, Anthropic, Cortex, etc.)
    for chunk in your_llm_client.stream(prompt):
        yield chunk


with st.chat_message("assistant"):
    response = st.write_stream(get_streaming_response(prompt))

st.session_state.messages.append({"role": "assistant", "content": response})
```

With OpenAI, you can pass the stream directly:

```python
from openai import OpenAI

client = OpenAI()
with st.chat_message("assistant"):
    stream = client.chat.completions.create(
        model="gpt-4o",
        messages=st.session_state.messages,
        stream=True,
    )
    response = st.write_stream(stream)
```

## Controlling input while the response runs

Use `submit_mode` to control what happens to the chat input after a user submits a message while the script (e.g. an LLM response) is still running:

```python
# Disable the input until the response finishes (prevents interruptions)
prompt = st.chat_input("Ask a question", submit_mode="disable")

# Turn the submit button into a stop button so users can cancel a long response
prompt = st.chat_input("Ask a question", submit_mode="stop")
```

- `"submit"` (default): the input stays enabled, so users can send new messages while the script runs.
- `"disable"`: the input is disabled after submission and re-enabled when the run completes—useful to avoid interrupting streaming responses.
- `"stop"`: the submit button becomes a stop button during the run; clicking it stops the script, like the app's "Stop" button.

## Thinking and agent steps

Use `type="compact"` or `type="step"` on `st.status` or `st.expander` inside a chat message to disclose reasoning without the default bordered container. Prefer `st.status` for live thinking; `st.expander` is fine for static replay from history.

**Compact thinking expander.** A borderless inline toggle—the ChatGPT/Claude-style "Thought for N seconds" pattern. Use this for a single reasoning block. While work is running, wrap the compact label in `:shimmer[...]` so the text itself is the in-progress cue; update to a static label when complete.

```python
with st.chat_message("assistant"):
    with st.status(":shimmer[Thinking]", type="compact") as status:
        st.write(reasoning)
        status.update(label="Thought for 4 seconds", state="complete")

    response = st.write_stream(get_streaming_response(prompt))
```

**Step timeline.** Consecutive `type="step"` containers share a vertical connector. Use this for tool calls, retrieval, and multi-stage agent work that should stay visible in the message.

```python
with st.chat_message("assistant"):
    with st.status("Searching docs", type="step"):
        sources = search(prompt)
        st.write(sources[0])

    with st.status("Thinking", type="step"):
        st.write(reasoning)

    response = st.write_stream(get_streaming_response(prompt, sources))
```

The connector already stops when the next sibling is not a step, so you do not need an empty terminal step before the streamed answer.

**Combining both.** Nest the step timeline inside a compact status when the details should stay collapsed by default. This is usually the best fit in chat: a "Thought for N seconds" toggle that reveals the chain of thought.

```python
with st.chat_message("assistant"):
    with st.status(":shimmer[Thinking]", type="compact") as status:
        with st.status("Searching docs", type="step"):
            sources = search(prompt)
            st.write(sources[0])

        with st.status("Planning", type="step"):
            st.write(reasoning)

        status.update(label="Thought for 4 seconds", state="complete")

    response = st.write_stream(get_streaming_response(prompt, sources))
```

- Keep `type="step"` containers consecutive. Any other element between them—including an invisible `st.empty()`—starts a new timeline segment.
- A step with no content also ends the timeline, which is useful to split a chain into segments—not as a dummy "done" node before the answer.
- `state` must be `"running"` (default), `"complete"`, or `"error"`—any other value raises an error, including via `status.update(state=...)`.
- Put the status where the work runs so its steps appear as the task runs. Don't gate it behind a button whose only job is to launch the task—running it in response to real input, for example `if prompt := st.chat_input(...)`, is the normal case.

## Chat message avatars

Streamlit provides default avatars for "user" and "assistant" roles—only customize if you have a specific need. You can use icons or images:

```python
# With icons
with st.chat_message("assistant", avatar=":material/robot:"):
    st.write(assistant_message)

# With images
with st.chat_message("user", avatar="https://example.com/avatar.png"):
    st.write(user_message)
```

## Suggestion chips

Offer clickable suggestions before the first message. A selected suggestion becomes the first prompt, and the pills disappear once the conversation starts:

```python
SUGGESTIONS = {
    ":blue[:material/help:] What is Streamlit?": "Explain what Streamlit is",
    ":green[:material/code:] Show me an example": "Show a simple Streamlit example",
}

# Replaces the basic example's `if prompt := st.chat_input(...)`
prompt = st.chat_input("Ask a question")

if not st.session_state.messages:
    suggestions = st.empty()
    selected = suggestions.pills(
        "Try asking:", list(SUGGESTIONS.keys()), label_visibility="collapsed"
    )
    if selected:
        prompt = SUGGESTIONS[selected]
    if prompt:
        suggestions.empty()  # Hide the pills before the first reply renders

if prompt:
    ...  # Same handling as typed input: append, display, and generate the reply
```

Show suggestions only while `st.session_state.messages` is empty, and route the selected suggestion through the same `if prompt:` handler as typed input. Appending the suggestion and calling `st.rerun()` skips the reply, because on that rerun `st.chat_input` returns `None`. Render the pills in an `st.empty()` placeholder and clear it once there is a prompt; otherwise they stay on screen above the first reply until the next rerun.

## File uploads

Enable file attachments with `accept_file`. When enabled, `st.chat_input` returns a dict-like object with `text` and `files` attributes:

```python
prompt = st.chat_input(
    "Ask about an image",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)

if prompt:
    with st.chat_message("user"):
        if prompt.text:
            st.write(prompt.text)
        if prompt.files:
            st.image(prompt.files[0])

    # Send to vision model; a message can be text-only, so files may be empty
    with st.chat_message("assistant"):
        image = prompt.files[0] if prompt.files else None
        response = analyze_image(image, prompt.text)
        st.write(response)
```

Use `accept_file="multiple"` to allow multiple files.

For typed helpers, import `ChatInputValue` and `UploadedFile` from the public `streamlit.typing` namespace instead of Streamlit's internal modules:

```python
from streamlit.typing import ChatInputValue, UploadedFile


def first_file(submission: ChatInputValue) -> UploadedFile | None:
    return submission.files[0] if "files" in submission and submission.files else None
```

## Audio input

Enable voice recording with `accept_audio`. The recorded audio is available as a WAV file:

```python
prompt = st.chat_input("Say something", accept_audio=True)

if prompt:
    if prompt.audio:
        st.audio(prompt.audio)
    if prompt.text:
        st.write(prompt.text)
```

### Dictation with speech-to-text

Convert audio to text and inject it back into the chat input:

```python
prompt = st.chat_input("Say something", accept_audio=True, key="chat")

if prompt and prompt.audio:
    # Transcribe with Whisper or another STT model
    transcript = openai.audio.transcriptions.create(
        model="whisper-1",
        file=prompt.audio,
    )
    # Set the transcribed text as the next input
    st.session_state.chat = transcript.text
    st.rerun()
```

## References

- `snowflake-connection.md` — Database queries and Cortex chat example
- `performance.md` — Caching strategies for LLM calls
- [st.chat_message](https://docs.streamlit.io/develop/api-reference/chat/st.chat_message)
- [st.chat_input](https://docs.streamlit.io/develop/api-reference/chat/st.chat_input)
- [st.write_stream](https://docs.streamlit.io/develop/api-reference/write-magic/st.write_stream)
- [st.status](https://docs.streamlit.io/develop/api-reference/status/st.status)
- [st.expander](https://docs.streamlit.io/develop/api-reference/layout/st.expander)
