
# Streamlit code organization

For most simple apps, keep everything in one file—it's cleaner and more straightforward. The app file should read like a normal Python script for data processing, with a few Streamlit commands sprinkled in.

Name the main file `streamlit_app.py` (Streamlit's default).

## When to split

**Keep in one file (most apps):**
- Apps under ~1000 lines
- One-off scripts and prototypes
- Apps where logic is straightforward

**Consider splitting when:**
- Data processing is complex (50+ lines of non-UI code)
- Multiple pages share logic
- You want to test business logic separately

If splitting makes sense, here's how to organize it.

## Directory structure

```
my-app/
├── streamlit_app.py      # Main entry point
├── app_pages/            # Page UI modules
│   ├── dashboard.py
│   └── settings.py
└── utils/                # Business logic & helpers
    ├── data.py
    └── api.py
```

## Separating UI from logic

When you do split, keep Streamlit files focused on UI and move complex logic to utility modules:

```python
# streamlit_app.py - UI-focused
import streamlit as st
from utils.data import load_sales_data, compute_metrics

st.title("Sales dashboard")

start = st.date_input("Start")
end = st.date_input("End")

data = load_sales_data(start, end)
metrics = compute_metrics(data)

st.metric("Revenue", f"${metrics['revenue']:,.0f}")
st.dataframe(data, alt="Sales by day")
```

## Omit the `if __name__ == "__main__"` guard

Streamlit executes the app file and each page file with `__name__` set to `"__main__"`, so the guard's body always runs there. Leave it out of those files; it adds nothing and hides the top-level flow.

```python
# Unnecessary in streamlit_app.py or pages
if __name__ == "__main__":
    main()

# Instead, put the code at the top level
import streamlit as st

st.title("My App")
```

## References

- [Multipage apps](https://docs.streamlit.io/develop/concepts/multipage-apps)
- [st.cache_data](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
