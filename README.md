# Engineering Team Crew

A [CrewAI](https://crewai.com) crew that turns plain-English requirements into a working Python app.
You describe the system in a Gradio web page; a team of AI agents then designs it, threat-models it,
writes the backend, builds a Gradio front end (`app.py`) and unit-tests it.

| Step | Agent | Output (in `sandbox/`) |
|------|-------|------------------------|
| 1. Design | Engineering Lead | `design.md` |
| 2. Threat model (DFD + STRIDE) | Security Architect | `threat_model.md` |
| 3. Backend | Backend Engineer | backend `.py` module(s) |
| 4. Front end | Frontend Engineer | `app.py`, `_validate.py` |
| 5. Unit tests | Test Engineer | `test_*.py`, `test_summary.md` |

The steps run one after another; each agent sees the output of the earlier steps it depends on.

## Prerequisites

- Python 3.10–3.13
- [uv](https://docs.astral.sh/uv/): `pip install uv`
- [Docker](https://www.docker.com/), running — the agents execute generated code inside a container
- API keys in a `.env` file in this folder:

  ```
  OPENAI_API_KEY=sk-...
  ANTHROPIC_API_KEY=sk-ant-...
  ```

Install the dependencies once from this folder:

```bash
uv sync
```

## Part 1 — Generate an app from your requirements

1. Start the requirements page:

   ```bash
   uv run ui
   ```

2. Open http://127.0.0.1:7860 in your browser.

3. Type your requirements in the **Requirements** box (it is pre-filled with an example trading-account
   system you can run as-is or replace).

4. Click **Build app**.
   - The requirements are first checked for personal information (see [PII guardrail](#pii-guardrail)).
     If any is found you'll see *"Your requirements appear to contain personal information (PII). Please
     remove any PII and try again."* — edit the text and click **Build app** again.
   - Otherwise the crew starts. The left panel shows elapsed time and the files written so far.
     A full run usually takes several minutes.

5. When the status shows **✅ Done**, review the results in the tabs on the right:
   **Design**, **Threat Model**, **Test Summary** and **app.py**. All generated files can also be
   downloaded from **Generated files**.

Only one build runs at a time. **Every build wipes the `sandbox/` folder first**, so copy anything
you want to keep before starting another build.

To run a build from the command line with the built-in example requirements instead, use
`uv run run_crew` (or `crewai run`).

## Part 2 — Run the generated app

The generated app lives in `sandbox/`, which is its own uv project with Gradio installed.

1. Open a new terminal (you can leave the requirements page running) and go to the sandbox:

   ```bash
   cd sandbox
   ```

2. Start the app:

   ```bash
   uv run app.py
   ```

3. Open the URL printed in the terminal. It is normally http://127.0.0.1:7860; if the requirements page is
   still running on that port, Gradio picks the next free one (e.g. http://127.0.0.1:7861).

4. Stop the app with `Ctrl+C`.

Optional checks, also from inside `sandbox/`:

```bash
uv run _validate.py            # confirms the Gradio UI builds without errors
uv run python -m unittest      # runs the generated unit tests
```

## PII guardrail

Before anything is sent to an LLM, the requirements are scanned locally by
[`guardrails.py`](src/engineering_team/guardrails.py). It looks for email addresses, phone numbers,
payment card numbers, US SSNs, Indian Aadhaar and PAN numbers, IBANs, dates of birth and public IP
addresses. Detection is pattern-based, so it won't catch everything (for example, names or postal
addresses) — still avoid pasting real personal data.

## Debugging

Tracing is enabled on the crew, so each run prints a trace link showing every agent step, tool call and
LLM call. Anyone with the link can read the trace, so don't share it if the run contained anything
sensitive.

## Customizing

- `src/engineering_team/config/agents.yaml` — agents and the LLM each one uses
- `src/engineering_team/config/tasks.yaml` — what each step does and where it writes its output
- `src/engineering_team/crew.py` — agent tools and crew settings
- `src/engineering_team/main.py` — the Gradio requirements page and CLI entry points
