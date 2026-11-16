# Displaying text

Use the specific text command for the job — explicit elements give you the right semantics, anchors, and spacing. Reach for `st.write`/magic only for quick debugging; prefer the named command in real apps.

For inline Markdown formatting (bold, colored text, links, inline badges, LaTeX), see [markdown.md](markdown.md). This reference covers the text *elements* themselves.

## Headings and titles

| Command | Use for |
|---------|---------|
| `st.title` | The one page title (largest) |
| `st.header` | Top-level section heading |
| `st.subheader` | Sub-section heading |

```python
st.title("Sales dashboard")
st.header("This quarter")
st.subheader("By region")
```

All three accept `anchor=`, `help=`, `icon=` (e.g. `icon=":material/dashboard:"`), and `text_alignment=`; `st.header` and `st.subheader` also accept `divider=`. Use sentence case (see [design.md](design.md)). Don't fake a heading with bold Markdown (`st.write("**Title**")`) — use the real element so it gets a proper anchor and consistent spacing.

## Body text, captions, code

- `st.markdown(...)` — formatted prose, the main workhorse (see [markdown.md](markdown.md)).
- `st.text(...)` — unformatted text: no Markdown or HTML parsing. It is *not* monospace; for monospace or preformatted output use `st.code(...)`.
- `st.caption(...)` — small, muted text for footnotes, timestamps, and help lines.
- `st.code(body, language=...)` — a syntax-highlighted code block with a copy button. Don't hand-build a fenced block inside `st.markdown` when you want a real code box.

```python
st.markdown("Formatted **prose** with a [link](https://example.com).")
st.caption("Last updated 5 minutes ago")
st.code("SELECT * FROM sales", language="sql")
st.text("Plain text, no Markdown parsing")
```

## Badges

`st.badge` renders a standalone status pill; for badges inline within text, use the Markdown directive (see [markdown.md](markdown.md)).

```python
st.badge("Active", icon=":material/check:", color="green")
```

## Streaming text: st.write_stream

`st.write_stream` writes string chunks from a generator / iterable / stream with a typewriter effect (non-string chunks go through the matching element). When the streamed output is only text, it returns that string; otherwise it returns a list of the streamed objects, so you can store or replay it. It accepts OpenAI and LangChain streams directly.

```python
def token_stream():
    for word in "Streaming one word at a time".split():
        yield word + " "


full_text = st.write_stream(token_stream)
```

For streaming an assistant reply inside a chat turn, see [chat-ui.md](chat-ui.md).

## st.write and magic (quick output only)

`st.write(...)` dispatches on argument type, and "magic" auto-renders a bare value sitting on its own line. Both are handy for quick, notebook-style output and debugging — but in real apps prefer the explicit element above: you get layout and configuration control, and the intent is clear. (Note: `st.write` of a dict/list renders interactive JSON, not a table; magic only applies in the main script and can be disabled via `runner.magicEnabled`.)

## References

- [st.title](https://docs.streamlit.io/develop/api-reference/text/st.title)
- [st.header](https://docs.streamlit.io/develop/api-reference/text/st.header)
- [st.subheader](https://docs.streamlit.io/develop/api-reference/text/st.subheader)
- [st.markdown](https://docs.streamlit.io/develop/api-reference/text/st.markdown)
- [st.caption](https://docs.streamlit.io/develop/api-reference/text/st.caption)
- [st.text](https://docs.streamlit.io/develop/api-reference/text/st.text)
- [st.code](https://docs.streamlit.io/develop/api-reference/text/st.code)
- [st.badge](https://docs.streamlit.io/develop/api-reference/text/st.badge)
- [st.write_stream](https://docs.streamlit.io/develop/api-reference/write-magic/st.write_stream)
