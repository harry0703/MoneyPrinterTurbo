
# Streamlit user authentication

Add real user sign-in with `st.login`, `st.logout`, and `st.user`.

## Don't roll your own password gate

A `st.text_input(type="password")` compared against a hardcoded string (or a
secret) is not authentication. It has no concept of user identity, the
"password" is shared by everyone, and the gate is trivially bypassed. Use
`st.login()` with a real OpenID Connect (OIDC) identity provider instead.

```python
# BAD — a fake gate, not authentication
import streamlit as st

if st.text_input("Password", type="password") != "hunter2":
    st.stop()
st.write("Secret dashboard")
```

```python
# GOOD — real OIDC identity via st.login
import streamlit as st

if not st.user.is_logged_in:
    st.login()
    st.stop()

st.write(f"Hello, {st.user.name}!")
if st.button("Log out"):
    st.logout()
```

**Why st.login:**
- Real per-user identity from a trusted provider (Google, Microsoft, Okta, Auth0, …)
- Signed identity cookie — can't be faked client-side
- Configuring `[auth]` turns on XSRF protection automatically
- `st.user` exposes verified claims (email, name, etc.); no password handling in your code

## Requirements

The auth flow needs the optional `auth` extra, which pulls in Authlib:

```shell
pip install "streamlit[auth]"
```

This is app-level authentication. It is unrelated to `st.text_input(type="password")`,
which is just a masked text field with no identity behind it.

## Configure the provider in secrets.toml

All auth config lives in an `[auth]` section of `.streamlit/secrets.toml`.
`redirect_uri` and `cookie_secret` are shared across every provider, along with
the optional `expose_tokens`. Each provider needs its own `client_id`,
`client_secret`, and `server_metadata_url`.

```toml
# .streamlit/secrets.toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "a-strong-randomly-generated-secret"
client_id = "xxx"
client_secret = "xxx"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

- `redirect_uri` must be your app's absolute URL ending in `/oauth2callback`. For
  local dev on the default port that's `http://localhost:8501/oauth2callback`.
  Update it (in both secrets and your provider) when you deploy.
- `cookie_secret` signs the identity cookie. Use a long, random value.
- `client_id`, `client_secret`, and `server_metadata_url` come from your OIDC
  provider's app registration.

Never commit this file. Add it to `.gitignore`:

```
.streamlit/secrets.toml
```

## Gate the whole app

The canonical pattern: bail out early when the user isn't signed in, then render
protected content.

```python
import streamlit as st

if not st.user.is_logged_in:
    st.title("Please log in")
    if st.button("Log in with Google"):
        st.login()
    st.stop()

# Everything below only runs for authenticated users
st.title("Dashboard")
st.write(f"Signed in as {st.user.name} ({st.user.email})")

with st.sidebar:
    if st.button("Log out"):
        st.logout()
```

`st.user.is_logged_in` is `True` only after a successful `st.login()`.
`st.user.email`, `st.user.name`, and other fields are claims parsed from the
provider's identity token (available claims vary by provider). `st.logout()`
clears the identity cookie and starts a fresh session.

## Multiple named providers

Give users a choice of identity providers by adding `[auth.<provider>]` sections.
Keep `redirect_uri` and `cookie_secret` in the shared `[auth]` section, and put
each provider's credentials in its own section. The name is internal to your app
and is passed to `st.login("<provider>")`.

```toml
# .streamlit/secrets.toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "a-strong-randomly-generated-secret"

[auth.google]
client_id = "xxx"
client_secret = "xxx"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

[auth.microsoft]
client_id = "xxx"
client_secret = "xxx"
server_metadata_url = "https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration"
```

```python
import streamlit as st

if not st.user.is_logged_in:
    st.header("Log in:")
    if st.button("Google"):
        st.login("google")
    if st.button("Microsoft"):
        st.login("microsoft")
    st.stop()

st.write(f"Hello, {st.user.name}!")
if st.button("Log out"):
    st.logout()
```

Provider names can't contain underscores. Only OIDC providers are supported —
generic OAuth 2.0 providers won't work.

## References

- [st.login](https://docs.streamlit.io/develop/api-reference/user/st.login)
- [st.logout](https://docs.streamlit.io/develop/api-reference/user/st.logout)
- [st.user](https://docs.streamlit.io/develop/api-reference/user/st.user)
- [User authentication and information](https://docs.streamlit.io/develop/concepts/connections/authentication)
- [st.secrets](https://docs.streamlit.io/develop/api-reference/connections/st.secrets)
