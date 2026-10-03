#!/usr/bin/env python
import os
import sys
import threading
import time
import warnings
from datetime import datetime

import gradio as gr

import engineering_team.patch  # noqa: F401 — applies CrewAI MCP monkey-patch on import
from engineering_team.crew import EngineeringTeam
from engineering_team.guardrails import PII_MESSAGE, contains_pii
from .tools.sandbox_tools import SANDBOX_DIR, reset_sandbox

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Task output_file paths (e.g. sandbox/design.md) are relative to the working
# directory, so the crew must always run from the project root.
PROJECT_ROOT = SANDBOX_DIR.parent

DEFAULT_REQUIREMENTS = """
A simple account management system for a trading simulation platform.
The system should allow users to create an account, deposit funds, and withdraw funds.
The system should allow users to record that they have bought or sold shares, providing a quantity.
The system should calculate the total value of the user's portfolio, and the profit or loss from the initial deposit.
The system should be able to report the holdings of the user at any point in time.
The system should be able to report the profit or loss of the user at any point in time.
The system should be able to list the transactions that the user has made over time.
The system should prevent the user from withdrawing funds that would leave them with a negative balance, or from buying more shares than they can afford, or selling shares that they don't have.
The system has access to a function get_share_price(symbol) which returns the current price of a share, and includes a test implementation that returns fixed prices for AAPL, TSLA, GOOGL.
The system should be secure.
""".strip()

# Generated artifacts shown in the UI, keyed by tab label.
ARTIFACTS = {
    "Design": "design.md",
    "Threat Model": "threat_model.md",
    "Test Summary": "test_summary.md",
}


def run_crew(requirements: str):
    """Reset the sandbox and run the full engineering crew on the given requirements."""
    os.chdir(PROJECT_ROOT)
    reset_sandbox()
    return EngineeringTeam().crew().kickoff(inputs={"requirements": requirements})


def run():
    """
    Run the crew from the command line with the default requirements.
    """
    try:
        run_crew(DEFAULT_REQUIREMENTS)
    except Exception as e:
        raise Exception(f"An error occurred while running the crew: {e}")


def _read_sandbox(filename: str) -> str:
    path = SANDBOX_DIR / filename
    return path.read_text() if path.is_file() else ""


def _generated_files() -> list[str]:
    """Paths of the generated source/docs in the sandbox (excludes uv/venv plumbing)."""
    if not SANDBOX_DIR.exists():
        return []
    return sorted(
        str(p) for p in SANDBOX_DIR.iterdir()
        if p.is_file() and p.suffix in {".py", ".md"}
    )


def _snapshot(status: str):
    files = _generated_files()
    listing = "\n".join(f"- `{os.path.basename(f)}`" for f in files) or "_No files yet._"
    return (
        f"{status}\n\n**Sandbox files:**\n{listing}",
        *(_read_sandbox(name) or "_Not generated yet._" for name in ARTIFACTS.values()),
        _read_sandbox("app.py"),
        files or None,
    )


def build_from_requirements(requirements: str):
    """Gradio handler: run the crew in a background thread and stream progress."""
    requirements = (requirements or "").strip()
    if not requirements:
        raise gr.Error("Please enter the requirements for the system to build.")
    if contains_pii(requirements):
        raise gr.Error(PII_MESSAGE)

    outcome: dict = {}

    def worker():
        try:
            run_crew(requirements)
        except Exception as e:  # surfaced in the UI below
            outcome["error"] = e

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    started = time.monotonic()
    while thread.is_alive():
        elapsed = int(time.monotonic() - started)
        yield _snapshot(f"⏳ **Crew is working…** ({elapsed // 60}m {elapsed % 60:02d}s elapsed)")
        thread.join(timeout=3)

    if "error" in outcome:
        yield _snapshot(f"❌ **The crew failed:** {outcome['error']}")
    else:
        yield _snapshot(
            f"✅ **Done.** Run the generated app with:\n\n"
            f"```\ncd {SANDBOX_DIR} && uv run app.py\n```"
        )


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Engineering Team") as demo:
        gr.Markdown(
            "# Engineering Team\n"
            "Describe the system you want. The crew will design it, produce a threat model, "
            "write the backend, build a Gradio `app.py` and unit-test it."
        )
        with gr.Row():
            with gr.Column(scale=1):
                requirements = gr.Textbox(
                    label="Requirements",
                    value=DEFAULT_REQUIREMENTS,
                    lines=16,
                    max_lines=40,
                )
                build_btn = gr.Button("Build app", variant="primary")
                status = gr.Markdown()
                files = gr.File(label="Generated files", file_count="multiple", interactive=False)
            with gr.Column(scale=2):
                with gr.Tabs():
                    artifact_views = []
                    for label in ARTIFACTS:
                        with gr.Tab(label):
                            artifact_views.append(gr.Markdown())
                    with gr.Tab("app.py"):
                        app_code = gr.Code(language="python", interactive=False)

        build_btn.click(
            build_from_requirements,
            inputs=requirements,
            outputs=[status, *artifact_views, app_code, files],
            concurrency_limit=1,  # the crew shares a single sandbox directory
        )
    return demo


def ui():
    """
    Launch the Gradio UI for entering requirements and running the crew.
    """
    build_ui().launch()


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "topic": "AI LLMs",
        'current_year': str(datetime.now().year)
    }
    try:
        EngineeringTeam().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        EngineeringTeam().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "topic": "AI LLMs",
        "current_year": str(datetime.now().year)
    }

    try:
        EngineeringTeam().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "topic": "",
        "current_year": ""
    }

    try:
        result = EngineeringTeam().crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
