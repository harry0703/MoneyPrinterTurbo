
# Streamlit Snowflake connection

Connect your Streamlit app to Snowflake the right way.

## Use st.connection

Always use `st.connection("snowflake")` instead of raw connectors.

```python
import streamlit as st

conn = st.connection("snowflake")

# Query data
df = conn.query("SELECT * FROM my_table LIMIT 100")
st.dataframe(df)
```

**Why st.connection:**
- Created once and reused across reruns (cached with `st.cache_resource`)
- Built-in query caching (without `ttl`, results are cached indefinitely; see [Cached queries](#cached-queries))
- Handles reconnection
- Works with st.secrets

## Caller's rights connection (Streamlit in Snowflake only)

> **Prerequisite:** This feature requires running your app inside Snowflake (Streamlit in Snowflake). It is not available for OSS Streamlit deployments.

For apps running in Snowflake, use caller's rights to run queries with the viewer's permissions instead of the app owner's:

```python
conn = st.connection("snowflake", type="snowflake-callers-rights")
```

This is useful when:
- Different users should see different data based on their Snowflake roles
- You want row-level security to apply based on the viewer
- You don't want the app to have elevated permissions

## Cached queries

`conn.query` caches results. Without `ttl` they are cached indefinitely, so set `ttl` for data that changes:

```python
from datetime import timedelta

conn = st.connection("snowflake")

# Cache for 10 minutes
df = conn.query("SELECT * FROM metrics", ttl=timedelta(minutes=10))

# Cache for 1 hour
df = conn.query("SELECT * FROM reference_data", ttl=3600)
```

## Configure with st.secrets

Store credentials in `.streamlit/secrets.toml` (never commit this file).

If `snow connection list` shows a connection with `is_default` set to `True`, skip `[connections.snowflake]`: `st.connection("snowflake")` uses that default. To use a different connection from that list, see [Named connections](#named-connections-from-a-snowflake-config-file). Otherwise, or when the app runs on a host that doesn't have that default, copy `account` and `host` exactly from the user's connection details, because a wrong `account` redirects to the wrong login page.

```toml
# .streamlit/secrets.toml
[connections.snowflake]
account = "ORGNAME-ACCTNAME"            # from `snow connection list`
host = "myaccount.snowflakecomputing.com"  # from `snow connection list` (include if present)
user = "your_user"
authenticator = "externalbrowser"
warehouse = "your_warehouse"
database = "your_database"
schema = "your_schema"
```

Add to `.gitignore`:
```
.streamlit/secrets.toml
```

## Parameterized queries

Use parameters to prevent SQL injection:

```python
conn = st.connection("snowflake")

# Safe: parameterized (Streamlit uses qmark binding: `?` placeholders, list params)
df = conn.query("SELECT * FROM users WHERE region = ?", params=[selected_region])

# UNSAFE: string formatting - don't do this
# df = conn.query(f"SELECT * FROM users WHERE region = '{selected_region}'")
```

## Write data

Use the session for write operations:

```python
conn = st.connection("snowflake")
session = conn.session()

# Write a dataframe
session.write_pandas(df, "MY_TABLE", auto_create_table=True)

# Execute statements
session.sql("INSERT INTO logs VALUES (?, ?)", params=[ts, msg]).collect()
```

## Multiple connections

Define multiple connections in secrets:

```toml
# .streamlit/secrets.toml
[connections.snowflake]
account = "prod_account"
# ... prod credentials

[connections.snowflake_staging]
account = "staging_account"
# ... staging credentials
```

```python
prod_conn = st.connection("snowflake")
staging_conn = st.connection("snowflake_staging")
```

## Named connections from a Snowflake config file

If you already manage connections in a Snowflake `connections.toml` file (the same
file the Snowflake CLI and Python connector use), you can select one by name without
duplicating the credentials in `secrets.toml`. When you call `st.connection` with a
name other than `"snowflake"` and provide no `[connections.<name>]` secrets and no
connection keyword arguments, Streamlit uses that name as the Snowflake connection
name.

```toml
# ~/.snowflake/connections.toml
[my_connection]
account = "ORGNAME-ACCTNAME"
user = "your_user"
authenticator = "externalbrowser"
warehouse = "your_warehouse"
database = "your_database"
schema = "your_schema"
```

```python
# Uses the [my_connection] entry from connections.toml
conn = st.connection("my_connection", type="snowflake")
df = conn.query("SELECT * FROM my_table")
```

The `type="snowflake"` argument is required here because the connection name is not the
built-in `"snowflake"` shorthand. Streamlit secrets still take precedence: if a
`[connections.my_connection]` section exists in `secrets.toml`, those values are used
instead of the `connections.toml` entry. Likewise, passing connection keyword arguments
(e.g. `st.connection("my_connection", type="snowflake", warehouse="wh")`) bypasses the
named entry entirely—those kwargs are forwarded to the connector as-is, so the
`connections.toml` entry is not used in that case.

## Chat with Cortex (Snowflake Cortex required)

> **Prerequisite:** This feature requires the `snowflake.cortex` package and a Snowflake account with Cortex access. It is primarily used in Streamlit in Snowflake deployments.

Build a chat interface using Snowflake Cortex LLMs:

```python
import streamlit as st
from snowflake.cortex import complete

st.set_page_config(page_title="AI Assistant", page_icon=":sparkles:")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

if prompt := st.chat_input("Ask anything"):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        response = st.write_stream(
            complete(
                "claude-3-5-sonnet",
                prompt,
                session=st.connection("snowflake").session(),
                stream=True,
            )
        )

    st.session_state.messages.append({"role": "assistant", "content": response})
```

See `chat-ui.md` for more chat patterns (avatars, suggestions, history management).

## References

- [st.connection](https://docs.streamlit.io/develop/api-reference/connections/st.connection)
- [SnowflakeConnection](https://docs.streamlit.io/develop/api-reference/connections/st.connections.snowflakeconnection)
- [st.secrets](https://docs.streamlit.io/develop/api-reference/connections/st.secrets)
