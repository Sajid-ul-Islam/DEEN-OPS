# Data Pilot AI Skills

This document tracks the core autonomous workflow skills available to the Data Pilot AI Agent.

## 1. DuckDB SQL Analytics

The Data Pilot has direct access to run high-performance SQL analytics on offline `.parquet` snapshots using an in-memory DuckDB connection.

**How it works:**
- The LLM is instructed via system prompt to output the `[SQL_QUERY: <query>]` tag when it needs to perform complex aggregations.
- The Streamlit chat loop intercepts this tag, strips it from the user-facing markdown, and executes the SQL against the `sales_data` view.
- The resulting DataFrame is rendered as a clean, interactive UI table for the user using `st.dataframe()`.
- The result (up to 50 rows) is converted to CSV string format and injected back into the LLM's context window as a `system` role message, allowing the AI to summarize or refer to the specific data points in subsequent interactions.

**Best Practices for the LLM:**
- Always target the `sales_data` table.
- Use double quotes around columns with spaces (e.g., `SUM("Total Amount")`).
- Keep aggregations concise and use `LIMIT` if selecting raw rows.

## 2. Dynamic Plotly Chart Generation

The Data Pilot can generate and display live `plotly.express` charts directly in the chat interface.

**How it works:**
- The LLM is instructed to output Python code wrapped in the `[PLOTLY_CODE: <code>]` tag.
- The chat execution loop intercepts this tag and safely executes it via `exec()`.
- A local scope is provided to the script mapping `df` to the primary sales dataframe and `px` to the `plotly.express` library.
- The resulting `fig` variable is parsed and rendered to the user via `st.plotly_chart(fig)`.

**Chaining with SQL (Advanced):**
- The LLM can output a `[SQL_QUERY: ...]` and a `[PLOTLY_CODE: ...]` in the *same* response.
- The execution loop runs the SQL query first.
- The resulting DataFrame from the SQL query is injected into the Plotly execution scope as `sql_df`.
- The LLM is instructed to use `sql_df` instead of `df` to plot highly aggregated or complex metrics without writing complex pandas aggregation code.

## 3. In-Memory Data Transformation

The Pilot can execute Pandas data cleaning operations directly on the live session data.

**How it works:**
- The LLM outputs Python code wrapped in the `[DATA_TRANSFORM: <code>]` tag.
- The code is executed in a restricted local scope where `df` is mapped to `st.session_state.wc_curr_df`.
- The transformed dataframe is saved back to `st.session_state`, immediately cleaning the data for the active user session without permanently corrupting the offline snapshot or backend files.

## 4. Data Export & Download

The Pilot can dynamically generate a download button in the chat UI, allowing users to export the active in-memory dataset to their local machine as a CSV.

**How it works:**
- The LLM is instructed to output the `[DOWNLOAD_DATA]` tag when a user asks to download or export the dataset.
- The chat execution loop intercepts this tag and removes it from the markdown.
- It then retrieves the active dataframe (`st.session_state.wc_curr_df`), converts it to a CSV payload, and renders a Streamlit `st.download_button()`.
- This is extremely powerful when chained after a `[DATA_TRANSFORM: ...]` operation, allowing users to safely clean and then export data without touching the backend files.