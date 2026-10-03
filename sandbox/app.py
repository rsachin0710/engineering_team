import gradio as gr

from backend import (
    AccountService,
    InMemoryAccountRepository,
    TradingSimulationError,
    account_to_summary_rows,
    accounts_to_rows,
    holdings_to_rows,
    snapshot_to_summary_rows,
    transactions_to_rows,
)

repository = InMemoryAccountRepository()
service = AccountService(repository)

PALETTE = {
    "gold": "#ecad0a",
    "blue": "#209dd7",
    "purple": "#753991",
    "bg": "#f6f7fb",
    "bg_dark": "#111827",
    "surface": "#ffffff",
    "surface_dark": "#1f2937",
    "border": "#d1d5db",
    "border_dark": "#374151",
    "text": "#111827",
    "text_dark": "#f9fafb",
    "muted": "#6b7280",
}

CSS = f"""
:root {{
  --gold: {PALETTE['gold']};
  --blue: {PALETTE['blue']};
  --purple: {PALETTE['purple']};
  --bg: {PALETTE['bg']};
  --surface: {PALETTE['surface']};
  --border: {PALETTE['border']};
  --text: {PALETTE['text']};
  --muted: {PALETTE['muted']};
}}
body {{ background: var(--bg); }}
.gradio-container {{ font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
.hero {{
  padding: 1.2rem 1.25rem;
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(32,157,215,0.12), rgba(117,57,145,0.12));
  border: 1px solid rgba(32,157,215,0.20);
}}
.hero h1 {{ margin: 0; color: var(--text); }}
.hero p {{ margin: .35rem 0 0; color: var(--muted); }}
.primary-btn button {{ background: linear-gradient(135deg, var(--blue), var(--purple)) !important; color: white !important; border: none !important; }}
.secondary-btn button {{ background: rgba(236,173,10,0.12) !important; color: var(--text) !important; border: 1px solid rgba(236,173,10,0.35) !important; }}
"""


def _status_ok(message: str) -> str:
    return f"✅ {message}"


def _status_err(message: str) -> str:
    return f"⚠️ {message}"


NO_ACCOUNT = "No active account. Create an account first (or pick one in Active Account)."


def _account_choices():
    return [(f"{a.owner_name} ({a.account_id[:8]})", a.account_id) for a in service.list_accounts()]


def ui_refresh_accounts(selected_account_id=None):
    choices = _account_choices()
    ids = [value for _, value in choices]
    value = selected_account_id if selected_account_id in ids else (ids[-1] if ids else None)
    return accounts_to_rows(service.list_accounts()), gr.update(choices=choices, value=value)


def ui_create_account(owner_name, initial_deposit, selected_account_id):
    try:
        account = service.create_account(owner_name, initial_deposit)
        return (
            _status_ok(f"Created account for {account.owner_name}. It is now the active account."),
            account.account_id,
            accounts_to_rows(service.list_accounts()),
            gr.update(choices=_account_choices(), value=account.account_id),
        )
    except TradingSimulationError as exc:
        return _status_err(str(exc)), "", accounts_to_rows(service.list_accounts()), gr.update(value=selected_account_id)
    except Exception:
        return (
            _status_err("An unexpected error occurred while creating the account."),
            "",
            accounts_to_rows(service.list_accounts()),
            gr.update(value=selected_account_id),
        )


def ui_deposit(account_id, amount):
    if not account_id:
        return (_status_err(NO_ACCOUNT),) + ([],) * 2
    try:
        service.deposit(account_id, amount)
        return (
            _status_ok("Deposit completed."),
            account_to_summary_rows(service.get_account(account_id)),
            transactions_to_rows(service.list_transactions(account_id)),
        )
    except TradingSimulationError as exc:
        return _status_err(str(exc)), [], []
    except Exception:
        return _status_err("An unexpected error occurred while processing the deposit."), [], []


def ui_withdraw(account_id, amount):
    if not account_id:
        return (_status_err(NO_ACCOUNT),) + ([],) * 2
    try:
        service.withdraw(account_id, amount)
        return (
            _status_ok("Withdrawal completed."),
            account_to_summary_rows(service.get_account(account_id)),
            transactions_to_rows(service.list_transactions(account_id)),
        )
    except TradingSimulationError as exc:
        return _status_err(str(exc)), [], []
    except Exception:
        return _status_err("An unexpected error occurred while processing the withdrawal."), [], []


def ui_buy(account_id, symbol, quantity):
    if not account_id:
        return (_status_err(NO_ACCOUNT),) + ([],) * 3
    try:
        service.buy_shares(account_id, symbol, quantity)
        snapshot = service.get_portfolio_snapshot(account_id)
        return (
            _status_ok("Purchase completed."),
            snapshot_to_summary_rows(snapshot),
            holdings_to_rows(snapshot),
            transactions_to_rows(service.list_transactions(account_id)),
        )
    except TradingSimulationError as exc:
        return _status_err(str(exc)), [], [], []
    except Exception:
        return _status_err("An unexpected error occurred while processing the purchase."), [], [], []


def ui_sell(account_id, symbol, quantity):
    if not account_id:
        return (_status_err(NO_ACCOUNT),) + ([],) * 3
    try:
        service.sell_shares(account_id, symbol, quantity)
        snapshot = service.get_portfolio_snapshot(account_id)
        return (
            _status_ok("Sale completed."),
            snapshot_to_summary_rows(snapshot),
            holdings_to_rows(snapshot),
            transactions_to_rows(service.list_transactions(account_id)),
        )
    except TradingSimulationError as exc:
        return _status_err(str(exc)), [], [], []
    except Exception:
        return _status_err("An unexpected error occurred while processing the sale."), [], [], []


def ui_get_snapshot(account_id, as_of_iso):
    if not account_id:
        return (_status_err(NO_ACCOUNT),) + ([],) * 2
    try:
        snapshot = service.get_portfolio_snapshot(account_id, as_of_iso)
        return _status_ok("Snapshot loaded."), snapshot_to_summary_rows(snapshot), holdings_to_rows(snapshot)
    except TradingSimulationError as exc:
        return _status_err(str(exc)), [], []
    except Exception:
        return _status_err("An unexpected error occurred while loading the snapshot."), [], []


def ui_list_transactions(account_id, start_iso, end_iso):
    if not account_id:
        return (_status_err(NO_ACCOUNT),) + ([],) * 1
    try:
        txns = service.list_transactions(account_id, start_iso, end_iso)
        return _status_ok(f"Loaded {len(txns)} transaction(s)."), transactions_to_rows(txns)
    except TradingSimulationError as exc:
        return _status_err(str(exc)), []
    except Exception:
        return _status_err("An unexpected error occurred while loading transactions."), []


with gr.Blocks(title="Trading Simulation Account Manager") as demo:
    gr.Markdown(
        """
        <div class="hero">
          <h1>Trading Simulation Account Manager</h1>
          <p>Create accounts, manage cash, trade supported symbols, and review historical reports in one clean workspace.</p>
        </div>
        """
    )

    with gr.Row():
        status = gr.Textbox(label="Status", value="Ready.", interactive=False)
        account_id_input = gr.Dropdown(
            label="Active Account",
            choices=[],
            value=None,
            interactive=True,
            info="Create an account first; it is selected here automatically.",
        )

    with gr.Tab("Create Account"):
        with gr.Row():
            owner_name = gr.Textbox(label="Owner Name", placeholder="e.g. Alex Morgan")
            initial_deposit = gr.Textbox(label="Initial Deposit", placeholder="e.g. 1000")
        create_btn = gr.Button("Create Account", variant="primary", elem_classes=["primary-btn"])
        created_account_id = gr.Textbox(label="Created Account ID", interactive=False)
        accounts_table = gr.Dataframe(
            headers=["Account ID", "Owner", "Created At", "Cash Balance", "Initial Deposit"],
            datatype=["str", "str", "str", "str", "str"],
            row_count=1,
            row_limits=None,
            column_count=5,
            interactive=False,
            label="Accounts",
        )
        refresh_accounts_btn = gr.Button("Refresh Accounts", elem_classes=["secondary-btn"])

    with gr.Tab("Funds"):
        with gr.Row():
            deposit_amount = gr.Textbox(label="Deposit Amount", placeholder="e.g. 250")
            withdraw_amount = gr.Textbox(label="Withdraw Amount", placeholder="e.g. 125")
        with gr.Row():
            deposit_btn = gr.Button("Deposit", variant="primary", elem_classes=["primary-btn"])
            withdraw_btn = gr.Button("Withdraw", elem_classes=["secondary-btn"])
        funds_summary = gr.Dataframe(headers=["Field", "Value"], datatype=["str", "str"], row_count=1, row_limits=None, column_count=2, interactive=False, label="Account Summary")
        funds_transactions = gr.Dataframe(headers=["Timestamp", "Transaction ID", "Type", "Symbol", "Quantity", "Price", "Amount", "Cash Delta", "Notes"], datatype=["str"] * 9, row_count=1, row_limits=None, column_count=9, interactive=False, label="Transactions")

    with gr.Tab("Trade"):
        with gr.Row():
            trade_symbol = gr.Dropdown(choices=["AAPL", "TSLA", "GOOGL"], value="AAPL", label="Symbol")
            trade_quantity = gr.Textbox(label="Quantity", placeholder="e.g. 2")
        with gr.Row():
            buy_btn = gr.Button("Buy", variant="primary", elem_classes=["primary-btn"])
            sell_btn = gr.Button("Sell", elem_classes=["secondary-btn"])
        trade_summary = gr.Dataframe(headers=["Metric", "Value"], datatype=["str", "str"], row_count=1, row_limits=None, column_count=2, interactive=False, label="Portfolio Summary")
        trade_holdings = gr.Dataframe(headers=["Symbol", "Quantity", "Current Price", "Market Value"], datatype=["str", "str", "str", "str"], row_count=1, row_limits=None, column_count=4, interactive=False, label="Holdings")
        trade_transactions = gr.Dataframe(headers=["Timestamp", "Transaction ID", "Type", "Symbol", "Quantity", "Price", "Amount", "Cash Delta", "Notes"], datatype=["str"] * 9, row_count=1, row_limits=None, column_count=9, interactive=False, label="Transactions")

    with gr.Tab("Reports"):
        with gr.Row():
            as_of_iso = gr.Textbox(label="As Of (ISO datetime)", placeholder="e.g. 2026-01-31T12:00:00Z")
            report_btn = gr.Button("Load Snapshot", variant="primary", elem_classes=["primary-btn"])
        report_summary = gr.Dataframe(headers=["Metric", "Value"], datatype=["str", "str"], row_count=1, row_limits=None, column_count=2, interactive=False, label="Portfolio Snapshot")
        report_holdings = gr.Dataframe(headers=["Symbol", "Quantity", "Current Price", "Market Value"], datatype=["str", "str", "str", "str"], row_count=1, row_limits=None, column_count=4, interactive=False, label="Holdings as of Timestamp")

    with gr.Tab("Transactions"):
        with gr.Row():
            start_iso = gr.Textbox(label="Start (ISO datetime)", placeholder="optional")
            end_iso = gr.Textbox(label="End (ISO datetime)", placeholder="optional")
        tx_btn = gr.Button("List Transactions", variant="primary", elem_classes=["primary-btn"])
        tx_table = gr.Dataframe(headers=["Timestamp", "Transaction ID", "Type", "Symbol", "Quantity", "Price", "Amount", "Cash Delta", "Notes"], datatype=["str"] * 9, row_count=1, row_limits=None, column_count=9, interactive=False, label="Filtered Transactions")

    create_btn.click(
        ui_create_account,
        inputs=[owner_name, initial_deposit, account_id_input],
        outputs=[status, created_account_id, accounts_table, account_id_input],
    )
    refresh_accounts_btn.click(ui_refresh_accounts, inputs=[account_id_input], outputs=[accounts_table, account_id_input])
    deposit_btn.click(ui_deposit, inputs=[account_id_input, deposit_amount], outputs=[status, funds_summary, funds_transactions])
    withdraw_btn.click(ui_withdraw, inputs=[account_id_input, withdraw_amount], outputs=[status, funds_summary, funds_transactions])
    buy_btn.click(ui_buy, inputs=[account_id_input, trade_symbol, trade_quantity], outputs=[status, trade_summary, trade_holdings, trade_transactions])
    sell_btn.click(ui_sell, inputs=[account_id_input, trade_symbol, trade_quantity], outputs=[status, trade_summary, trade_holdings, trade_transactions])
    report_btn.click(ui_get_snapshot, inputs=[account_id_input, as_of_iso], outputs=[status, report_summary, report_holdings])
    tx_btn.click(ui_list_transactions, inputs=[account_id_input, start_iso, end_iso], outputs=[status, tx_table])

    demo.load(ui_refresh_accounts, inputs=[account_id_input], outputs=[accounts_table, account_id_input])

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=4).launch()
