#!/usr/bin/env python
import atexit
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
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

# How long to wait for the generated app to print its URL after launching it.
APP_START_TIMEOUT = 120
URL_PATTERN = re.compile(r"https?://[^\s]+")

# The generated app currently running from the sandbox, if any.
_app_process: subprocess.Popen | None = None


def _stop_app() -> None:
    """Stop the previously launched generated app so the sandbox can be rebuilt."""
    global _app_process
    if _app_process and _app_process.poll() is None:
        _app_process.terminate()
        try:
            _app_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _app_process.kill()
    _app_process = None


atexit.register(_stop_app)


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


def _launch_app() -> str:
    """Start sandbox/app.py in the background and return the URL it serves on."""
    global _app_process
    if not (SANDBOX_DIR / "app.py").is_file():
        raise RuntimeError("The crew did not produce app.py.")

    _app_process = subprocess.Popen(
        ["uv", "run", "app.py"],
        cwd=SANDBOX_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1", "GRADIO_SERVER_NAME": "127.0.0.1"},
    )

    lines: queue.Queue[str] = queue.Queue()

    def pump(stream):
        # Keep draining output for the app's lifetime so its pipe never fills up;
        # forward it to this console for debugging.
        for line in stream:
            print(f"[app.py] {line}", end="")
            lines.put(line)

    threading.Thread(target=pump, args=(_app_process.stdout,), daemon=True).start()

    deadline = time.monotonic() + APP_START_TIMEOUT
    while time.monotonic() < deadline:
        if _app_process.poll() is not None and lines.empty():
            raise RuntimeError("app.py exited before it started serving.")
        try:
            line = lines.get(timeout=1)
        except queue.Empty:
            continue
        match = URL_PATTERN.search(line)
        if match:
            return match.group(0).rstrip("/")
    _stop_app()
    raise RuntimeError("app.py did not report a URL in time.")


def build_from_requirements(requirements: str):
    """Gradio handler: run the crew, launch the generated app and show its URL."""
    requirements = (requirements or "").strip()
    if not requirements:
        raise gr.Error("Please enter the requirements for the system to build.")
    if contains_pii(requirements):
        raise gr.Error(PII_MESSAGE)

    _stop_app()
    outcome: dict = {}

    def worker():
        try:
            run_crew(requirements)
        except Exception as e:
            outcome["error"] = e

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    started = time.monotonic()
    while thread.is_alive():
        elapsed = int(time.monotonic() - started)
        yield f"⏳ **Building your app…** ({elapsed // 60}m {elapsed % 60:02d}s elapsed)"
        thread.join(timeout=3)

    if "error" in outcome:
        traceback.print_exception(outcome["error"])
        yield "❌ **The build failed.** Check the terminal running `uv run ui` for details."
        return

    yield "🚀 **Starting your app…**"
    try:
        url = _launch_app()
    except Exception:
        traceback.print_exc()
        yield "❌ **The app was built but could not be started.** Check the terminal for details."
        return

    yield f"✅ **Your app is running:** [{url}]({url})"


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Engineering Team") as demo:
        gr.Markdown(
            "# Engineering Team\n"
            "Describe the system you want, then click **Build app**. "
            "When it's ready, a link to the running app appears below."
        )
        requirements = gr.Textbox(
            label="Requirements",
            value=DEFAULT_REQUIREMENTS,
            lines=16,
            max_lines=40,
        )
        build_btn = gr.Button("Build app", variant="primary")
        status = gr.Markdown()

        build_btn.click(
            build_from_requirements,
            inputs=requirements,
            outputs=status,
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
