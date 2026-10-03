# Detailed Design: Trading Simulation Account Management System

## 1. Goals and Scope

Build a simple, secure trading simulation account management system that lets users:

- Create accounts.
- Deposit funds.
- Withdraw funds.
- Buy shares.
- Sell shares.
- View current and historical holdings.
- View current and historical portfolio value.
- View current and historical profit/loss.
- List all transactions over time.
- Prevent invalid financial operations:
  - No withdrawal that would make cash balance negative.
  - No purchase beyond available cash.
  - No sale beyond owned quantity.

The project runs in a single sandbox directory with no package subdirectories.

Available third-party dependency:

- `gradio`

Standard library may be used freely.

The system has access to a share price function:

```python
def get_share_price(symbol: str) -> float
```

A test implementation must return fixed prices for:

- `AAPL`
- `TSLA`
- `GOOGL`

---

## 2. File Structure

All files must live in the same directory.

```text
backend.py
app.py
test_backend.py
threat_model.md
README.md
```

### File Responsibilities

| File | Owner | Purpose |
|---|---:|---|
| `backend.py` | `backend_engineer` | Domain model, validation, account service, in-memory repository, share price function |
| `app.py` | `frontend_engineer` | Gradio 6 UI wired to backend service |
| `test_backend.py` | `test_engineer` | Unit tests for backend behavior |
| `threat_model.md` | `threat_modeller` | DFD description, STRIDE threat table, mitigations |
| `README.md` | shared | How to run app/tests and brief system notes |

---

## 3. System Architecture

```text
User
 |
 | Uses browser
 v
Gradio UI app.py
 |
 | Calls Python functions directly
 v
AccountService backend.py
 |
 | Reads/writes
 v
InMemoryAccountRepository backend.py
 |
 | Stores accounts and transaction ledger in process memory
 v
get_share_price(symbol)
```

This is a local simulation application. There is no external database, no real brokerage integration, no real payment processing, and no authentication system in the first implementation.

---

## 4. Important Product Decisions

### 4.1 Account Identity

Each account receives a generated opaque `account_id`.

The user interacts with the account by entering/selecting the `account_id`.

No passwords are implemented in this version unless explicitly requested later.

Security implication: anyone who knows an `account_id` in the running app can operate on that simulated account. This must be documented in `threat_model.md`.

### 4.2 Money Representation

Use `Decimal` internally for currency and share prices.

Public UI functions may accept strings/floats from Gradio, but backend service must normalize to `Decimal`.

Do not use binary floating point for business rules.

### 4.3 Quantity Representation

Share quantities must be positive whole numbers.

No fractional shares in this version.

### 4.4 Price Source

`get_share_price(symbol)` returns current fixed test prices.

Supported symbols:

```text
AAPL
TSLA
GOOGL
```

Unknown symbols must raise a controlled validation error.

### 4.5 Historical Reports

The backend ledger records all deposits, withdrawals, buys, and sells with timestamps.

For “at any point in time” reporting:

- Holdings are reconstructed by replaying transactions up to the requested timestamp.
- Cash balance is reconstructed by replaying transactions up to the requested timestamp.
- Portfolio market value uses the current `get_share_price(symbol)` price because no historical price oracle exists.
- This limitation must be documented.

### 4.6 Profit/Loss Semantics

The primary P/L calculation should be cashflow-adjusted:

```text
profit_loss = current_total_equity + total_withdrawals - total_deposits
```

Where:

```text
current_total_equity = cash_balance + current_market_value_of_holdings
```

This avoids treating extra user deposits as trading profit.

Also expose an optional convenience metric:

```text
change_from_initial_deposit = current_total_equity - initial_deposit
```

The UI should display the primary cashflow-adjusted P/L and may also display change from initial deposit.

---

## 5. Backend Design: `backend.py`

### 5.1 Domain Exceptions

Define specific exceptions so the frontend and tests can handle errors cleanly.

```python
class TradingSimulationError(Exception):
    """Base class for expected domain errors."""
```

```python
class ValidationError(TradingSimulationError):
    """Raised when user input is invalid."""
```

```python
class AccountNotFoundError(TradingSimulationError):
    """Raised when an account id does not exist."""
```

```python
class InsufficientFundsError(TradingSimulationError):
    """Raised when cash balance is insufficient."""
```

```python
class InsufficientHoldingsError(TradingSimulationError):
    """Raised when share holdings are insufficient."""
```

```python
class UnsupportedSymbolError(TradingSimulationError):
    """Raised when symbol is not supported by price provider."""
```

---

### 5.2 Enums and Constants

```python
class TransactionType(Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"
```

```python
SUPPORTED_SYMBOLS: tuple[str, ...]
```

```python
CURRENCY_QUANTIZATION: Decimal
```

Expected:

```text
CURRENCY_QUANTIZATION = Decimal("0.01")
```

---

### 5.3 Data Classes

#### `Transaction`

Immutable ledger entry.

```python
@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    account_id: str
    transaction_type: TransactionType
    timestamp: datetime
    amount: Decimal | None
    symbol: str | None
    quantity: int | None
    price: Decimal | None
    cash_delta: Decimal
    notes: str = ""
```

Field rules:

| Field | Description |
|---|---|
| `transaction_id` | UUID string |
| `account_id` | Owning account |
| `transaction_type` | Deposit, withdrawal, buy, sell |
| `timestamp` | Time transaction was recorded, timezone-aware UTC |
| `amount` | Deposit/withdrawal amount, or trade gross value |
| `symbol` | Share symbol for trades |
| `quantity` | Share quantity for trades |
| `price` | Per-share execution price for trades |
| `cash_delta` | Positive for cash increase, negative for cash decrease |
| `notes` | Optional system/user-readable note |

---

#### `Account`

Represents account metadata and current materialized state.

```python
@dataclass
class Account:
    account_id: str
    owner_name: str
    created_at: datetime
    initial_deposit: Decimal
    cash_balance: Decimal
    holdings: dict[str, int]
    transactions: list[Transaction]
```

Notes:

- `holdings` maps symbol to owned quantity.
- Symbols with zero quantity should be removed or omitted from reports.
- `transactions` is append-only from the perspective of service methods.

---

#### `PortfolioSnapshot`

Returned by reports.

```python
@dataclass(frozen=True)
class PortfolioSnapshot:
    account_id: str
    as_of: datetime
    cash_balance: Decimal
    holdings: dict[str, int]
    holdings_market_value: Decimal
    total_equity: Decimal
    total_deposits: Decimal
    total_withdrawals: Decimal
    profit_loss: Decimal
    change_from_initial_deposit: Decimal
```

---

### 5.4 Price Provider

```python
def get_share_price(symbol: str) -> Decimal:
    """Return current fixed share price for supported symbols."""
```

Expected fixed test prices:

```text
AAPL = 150.00
TSLA = 250.00
GOOGL = 2800.00
```

Behavior:

- Normalize symbols to uppercase.
- Reject empty symbols.
- Raise `UnsupportedSymbolError` for unknown symbols.
- Return `Decimal`, not `float`.

---

### 5.5 Validation Helpers

```python
def normalize_symbol(symbol: str) -> str:
    """Trim and uppercase a symbol; reject invalid values."""
```

```python
def parse_money(value: str | int | float | Decimal, field_name: str) -> Decimal:
    """Convert a user-provided money value to Decimal with two decimal places."""
```

```python
def parse_positive_quantity(value: str | int | float, field_name: str = "quantity") -> int:
    """Convert a user-provided quantity to a positive integer."""
```

```python
def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
```

```python
def parse_optional_as_of(value: str | datetime | None) -> datetime | None:
    """Parse optional ISO datetime for historical reports."""
```

Validation rules:

- Money must be finite, positive where required.
- Deposits must be `> 0`.
- Withdrawals must be `> 0`.
- Quantity must be an integer `> 0`.
- Symbol must be non-empty and supported.
- Owner name must be non-empty and length-limited.

Recommended limits:

```text
owner_name <= 100 characters
symbol <= 10 characters
money amount <= 1_000_000_000
quantity <= 1_000_000_000
```

---

### 5.6 Repository Interface

Even though this project uses an in-memory repository, keep a clean boundary for future persistence.

```python
class AccountRepository:
    def create(self, account: Account) -> None:
        ...

    def get(self, account_id: str) -> Account:
        ...

    def list_accounts(self) -> list[Account]:
        ...

    def save(self, account: Account) -> None:
        ...
```

---

### 5.7 In-Memory Repository

```python
class InMemoryAccountRepository(AccountRepository):
    def __init__(self) -> None:
        ...

    def create(self, account: Account) -> None:
        ...

    def get(self, account_id: str) -> Account:
        ...

    def list_accounts(self) -> list[Account]:
        ...

    def save(self, account: Account) -> None:
        ...

    def clear(self) -> None:
        ...
```

Implementation requirements:

- Store accounts in a dictionary keyed by account ID.
- Use `threading.RLock` or equivalent locking around reads/writes because Gradio can process concurrent requests.
- Do not expose internal mutable account state without care.
- Since all service methods run in-process, returning account objects is acceptable for this simple app, but mutations must only happen inside `AccountService`.

---

### 5.8 Account Service

Primary backend API used by frontend and tests.

```python
class AccountService:
    def __init__(self, repository: AccountRepository) -> None:
        ...
```

#### Account Creation

```python
def create_account(self, owner_name: str, initial_deposit: str | int | float | Decimal) -> Account:
    """Create an account with an initial deposit transaction."""
```

Rules:

- Owner name required.
- Initial deposit must be positive.
- Create account with cash balance equal to initial deposit.
- Add an initial `DEPOSIT` transaction.
- Return created account.

---

#### Deposits

```python
def deposit(self, account_id: str, amount: str | int | float | Decimal) -> Transaction:
    """Deposit funds into an account."""
```

Rules:

- Account must exist.
- Amount must be positive.
- Increase cash balance.
- Append `DEPOSIT` transaction.

---

#### Withdrawals

```python
def withdraw(self, account_id: str, amount: str | int | float | Decimal) -> Transaction:
    """Withdraw funds from an account if cash balance remains non-negative."""
```

Rules:

- Account must exist.
- Amount must be positive.
- Reject if `amount > cash_balance`.
- Decrease cash balance.
- Append `WITHDRAWAL` transaction.

---

#### Buy Shares

```python
def buy_shares(self, account_id: str, symbol: str, quantity: str | int | float) -> Transaction:
    """Buy shares if account has sufficient cash."""
```

Rules:

- Account must exist.
- Symbol must be supported.
- Quantity must be a positive integer.
- Price comes from `get_share_price(symbol)`.
- Trade cost is `price * quantity`.
- Reject if `trade_cost > cash_balance`.
- Decrease cash balance by trade cost.
- Increase holdings.
- Append `BUY` transaction.

---

#### Sell Shares

```python
def sell_shares(self, account_id: str, symbol: str, quantity: str | int | float) -> Transaction:
    """Sell shares if account has sufficient holdings."""
```

Rules:

- Account must exist.
- Symbol must be supported.
- Quantity must be positive integer.
- Reject if owned quantity is less than sell quantity.
- Price comes from `get_share_price(symbol)`.
- Trade proceeds are `price * quantity`.
- Increase cash balance by proceeds.
- Decrease holdings.
- Remove symbol from holdings if resulting quantity is zero.
- Append `SELL` transaction.

---

#### Current Account State

```python
def get_account(self, account_id: str) -> Account:
    """Return account by id."""
```

```python
def list_accounts(self) -> list[Account]:
    """Return all accounts."""
```

---

#### Transaction Listing

```python
def list_transactions(
    self,
    account_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[Transaction]:
    """Return transactions for an account, optionally filtered by inclusive time range."""
```

Rules:

- Transactions sorted ascending by timestamp.
- If `start` provided, include transactions where `timestamp >= start`.
- If `end` provided, include transactions where `timestamp <= end`.

---

#### Historical Reconstruction

```python
def get_holdings_at(self, account_id: str, as_of: datetime | None = None) -> dict[str, int]:
    """Reconstruct holdings as of timestamp using ledger replay."""
```

```python
def get_cash_balance_at(self, account_id: str, as_of: datetime | None = None) -> Decimal:
    """Reconstruct cash balance as of timestamp using ledger replay."""
```

```python
def get_portfolio_snapshot(
    self,
    account_id: str,
    as_of: datetime | None = None,
) -> PortfolioSnapshot:
    """Return cash, holdings, value, and P/L as of timestamp."""
```

Rules:

- If `as_of` is `None`, use current latest state.
- If `as_of` provided, only replay transactions with `timestamp <= as_of`.
- Market value uses current prices.
- Cashflow-adjusted P/L:
  - `total_equity + total_withdrawals - total_deposits`
- Change from initial deposit:
  - `total_equity - initial_deposit`

---

#### Formatting Helpers for UI

These helpers are optional but recommended to keep `app.py` simple.

```python
def account_to_summary_rows(account: Account) -> list[list[str]]:
    """Convert account summary into rows suitable for gr.Dataframe."""
```

```python
def holdings_to_rows(snapshot: PortfolioSnapshot) -> list[list[str]]:
    """Convert holdings snapshot into rows suitable for gr.Dataframe."""
```

```python
def transactions_to_rows(transactions: list[Transaction]) -> list[list[str]]:
    """Convert transactions into rows suitable for gr.Dataframe."""
```

```python
def snapshot_to_summary_rows(snapshot: PortfolioSnapshot) -> list[list[str]]:
    """Convert portfolio snapshot into summary rows suitable for gr.Dataframe."""
```

---

## 6. Frontend Design: `app.py`

Owner: `frontend_engineer`

Build a Gradio 6 app that lets users exercise all backend functionality.

### 6.1 Gradio 6 API Guidance

Use the current Gradio 6 style:

```python
import gradio as gr

with gr.Blocks() as demo:
    ...
    button.click(fn=handler, inputs=[...], outputs=[...])

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=4).launch()
```

Important Gradio 6 notes:

1. Use `gr.Blocks()` as the main layout container.
2. Use event listeners like:
   ```python
   button.click(fn=some_function, inputs=[input1, input2], outputs=[output1, output2])
   ```
3. `gr.Dataframe` Gradio 6 sizing changed:
   - Use `row_count` for initial row count.
   - Use `row_limits` for min/max row constraints.
   - Use `column_count` for initial column count.
   - Use `column_limits` for min/max column constraints.
   - Do not use old tuple forms like `row_count=(5, "fixed")`.
4. Example fixed dataframe columns:
   ```python
   gr.Dataframe(
       headers=["Field", "Value"],
       datatype=["str", "str"],
       row_count=1,
       row_limits=None,
       column_count=2,
       column_limits=(2, 2),
       interactive=False,
       label="Summary",
   )
   ```
5. For component property updates, use:
   ```python
   gr.update(...)
   ```
   or return a new component instance if needed.
6. Use `gr.Markdown`, `gr.Textbox`, `gr.Number`, `gr.Dropdown`, `gr.Button`, `gr.Dataframe`.
7. `demo.queue(default_concurrency_limit=4).launch()` is acceptable for this app.
8. Avoid custom JavaScript.
9. Avoid accepting raw HTML from users. Use plain text outputs.

---

### 6.2 Shared Backend Instance

At module level in `app.py`:

```python
repository: InMemoryAccountRepository
service: AccountService
```

The app uses this single in-memory service.

---

### 6.3 UI Layout

Recommended tabs:

```text
Trading Simulation Account Manager
|
|-- Create Account
|-- Funds
|-- Trade
|-- Reports
|-- Transactions
```

---

### 6.4 Components

#### Global Components

A reusable account ID textbox should be available in each tab or a single account selector can be used.

Because accounts are created dynamically, a simple textbox is less error-prone than dynamic dropdown updates.

```python
account_id_input: gr.Textbox
status_output: gr.Textbox
```

Optional account list dataframe:

```python
accounts_table: gr.Dataframe
```

---

### 6.5 Frontend Handler Signatures

Handlers should catch `TradingSimulationError` and generic `Exception`.

Expected return style:

- First output: status message.
- Additional outputs: refreshed tables.

#### Create Account

```python
def ui_create_account(owner_name: str, initial_deposit: float | str) -> tuple[str, str, list[list[str]]]:
    """Create account and return status, account_id, accounts table."""
```

Outputs:

1. Status text.
2. Created account ID textbox value.
3. Accounts dataframe rows.

---

#### Refresh Accounts

```python
def ui_refresh_accounts() -> list[list[str]]:
    """Return all accounts as table rows."""
```

---

#### Deposit

```python
def ui_deposit(account_id: str, amount: float | str) -> tuple[str, list[list[str]], list[list[str]]]:
    """Deposit funds and return status, portfolio summary, transactions."""
```

Outputs:

1. Status.
2. Portfolio summary rows.
3. Transaction rows.

---

#### Withdraw

```python
def ui_withdraw(account_id: str, amount: float | str) -> tuple[str, list[list[str]], list[list[str]]]:
    """Withdraw funds and return status, portfolio summary, transactions."""
```

---

#### Buy

```python
def ui_buy(account_id: str, symbol: str, quantity: float | str) -> tuple[str, list[list[str]], list[list[str]], list[list[str]]]:
    """Buy shares and return status, summary, holdings, transactions."""
```

Outputs:

1. Status.
2. Portfolio summary.
3. Holdings table.
4. Transactions table.

---

#### Sell

```python
def ui_sell(account_id: str, symbol: str, quantity: float | str) -> tuple[str, list[list[str]], list[list[str]], list[list[str]]]:
    """Sell shares and return status, summary, holdings, transactions."""
```

---

#### Report Snapshot

```python
def ui_get_snapshot(account_id: str, as_of_iso: str | None) -> tuple[str, list[list[str]], list[list[str]]]:
    """Return portfolio summary and holdings as of optional timestamp."""
```

---

#### List Transactions

```python
def ui_list_transactions(
    account_id: str,
    start_iso: str | None,
    end_iso: str | None,
) -> tuple[str, list[list[str]]]:
    """Return transaction list filtered by optional timestamps."""
```

---

### 6.6 Dataframe Schemas

#### Accounts Table

Headers:

```text
Account ID
Owner
Created At
Cash Balance
Initial Deposit
```

```python
accounts_table = gr.Dataframe(
    headers=["Account ID", "Owner", "Created At", "Cash Balance", "Initial Deposit"],
    datatype=["str", "str", "str", "str", "str"],
    row_count=1,
    row_limits=None,
    column_count=5,
    column_limits=(5, 5),
    interactive=False,
    label="Accounts",
)
```

---

#### Portfolio Summary Table

Headers:

```text
Metric
Value
```

Rows:

```text
As Of
Cash Balance
Holdings Market Value
Total Equity
Total Deposits
Total Withdrawals
Profit/Loss
Change From Initial Deposit
```

---

#### Holdings Table

Headers:

```text
Symbol
Quantity
Current Price
Market Value
```

---

#### Transactions Table

Headers:

```text
Timestamp
Transaction ID
Type
Symbol
Quantity
Price
Amount
Cash Delta
Notes
```

---

### 6.7 Frontend Security Requirements

- Never call `eval`, `exec`, or shell commands.
- Display user-provided values as text only.
- Validate in backend, not only frontend.
- Do not trust Gradio numeric fields because users can call endpoints directly.
- Catch expected backend exceptions and show safe user-facing messages.
- Do not expose Python tracebacks in UI status messages.
- Limit free-text input length before passing to backend where practical.
- Avoid `gr.HTML` for user-controlled data.

---

## 7. Unit Test Design: `test_backend.py`

Owner: `test_engineer`

Use Python standard library `unittest`.

No `pytest` dependency.

### 7.1 Test Setup

Each test should create a fresh repository and service.

```python
class AccountServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        ...
```

Recommended helper:

```python
def make_service() -> AccountService:
    """Return AccountService with fresh InMemoryAccountRepository."""
```

---

### 7.2 Required Test Cases

#### Account Creation

```python
def test_create_account_with_initial_deposit(self) -> None:
    ...
```

Verify:

- Account is created.
- Cash balance equals initial deposit.
- Initial deposit transaction exists.
- Initial deposit stored.

```python
def test_create_account_rejects_empty_owner(self) -> None:
    ...
```

```python
def test_create_account_rejects_non_positive_initial_deposit(self) -> None:
    ...
```

---

#### Deposits

```python
def test_deposit_increases_cash_balance(self) -> None:
    ...
```

```python
def test_deposit_rejects_negative_amount(self) -> None:
    ...
```

---

#### Withdrawals

```python
def test_withdraw_decreases_cash_balance(self) -> None:
    ...
```

```python
def test_withdraw_rejects_overdraft(self) -> None:
    ...
```

```python
def test_withdraw_rejects_negative_amount(self) -> None:
    ...
```

---

#### Buying

```python
def test_buy_shares_decreases_cash_and_increases_holdings(self) -> None:
    ...
```

Example:

- Create account with `1000`.
- Buy `2` AAPL at `150`.
- Cash becomes `700`.
- AAPL holdings become `2`.

```python
def test_buy_rejects_insufficient_funds(self) -> None:
    ...
```

```python
def test_buy_rejects_unknown_symbol(self) -> None:
    ...
```

```python
def test_buy_rejects_non_positive_quantity(self) -> None:
    ...
```

```python
def test_buy_rejects_fractional_quantity(self) -> None:
    ...
```

---

#### Selling

```python
def test_sell_shares_increases_cash_and_decreases_holdings(self) -> None:
    ...
```

```python
def test_sell_rejects_insufficient_holdings(self) -> None:
    ...
```

```python
def test_sell_removes_zero_holding(self) -> None:
    ...
```

```python
def test_sell_rejects_unknown_symbol(self) -> None:
    ...
```

---

#### Portfolio Snapshot

```python
def test_portfolio_snapshot_calculates_total_equity(self) -> None:
    ...
```

```python
def test_portfolio_snapshot_calculates_profit_loss_cashflow_adjusted(self) -> None:
    ...
```

Example:

- Deposit `1000`.
- Buy `2` AAPL for `300`.
- Current equity remains `1000` if AAPL price unchanged.
- Cashflow-adjusted P/L is `0`.

```python
def test_portfolio_snapshot_after_withdrawal_cashflow_adjusted(self) -> None:
    ...
```

---

#### Historical Reporting

```python
def test_get_holdings_at_reconstructs_past_holdings(self) -> None:
    ...
```

```python
def test_get_cash_balance_at_reconstructs_past_balance(self) -> None:
    ...
```

```python
def test_list_transactions_filters_by_time_range(self) -> None:
    ...
```

Testing timestamps:

- Because timestamps are generated internally, capture transaction timestamps returned by service methods.
- Use those timestamps as boundaries.

---

#### Account Lookup

```python
def test_get_unknown_account_raises_account_not_found(self) -> None:
    ...
```

---

### 7.3 Test Execution

`README.md` should instruct:

```bash
uv run python -m unittest test_backend.py
```

---

## 8. Threat Model Design: `threat_model.md`

Owner: `threat_modeller`

The threat modeller should create:

1. Data Flow Diagram description.
2. STRIDE threat table.
3. Security assumptions.
4. Trust boundaries.
5. Mitigation mapping.

---

## 9. DFD Details for Threat Modeller

### 9.1 External Entities

| Entity | Description |
|---|---|
| User | Person using browser to operate simulated account |
| Browser | User’s web client running Gradio frontend |
| Price Provider Function | Local `get_share_price(symbol)` function returning fixed prices |

---

### 9.2 Processes

| Process | Description |
|---|---|
| P1: Gradio UI | Receives user input, displays account data, calls backend service |
| P2: Account Service | Validates business commands and enforces trading rules |
| P3: Reporting Engine | Reconstructs holdings, cash, P/L from transaction ledger |
| P4: Price Lookup | Returns current share price for supported symbols |

The reporting engine may be implemented as methods in `AccountService`, but model it separately in the DFD for clarity.

---

### 9.3 Data Stores

| Data Store | Description |
|---|---|
| D1: In-Memory Account Store | Dictionary of account IDs to account objects |
| D2: Transaction Ledger | Append-only transaction list per account, stored inside each account object |

In implementation, D1 and D2 are both contained in `InMemoryAccountRepository`.

---

### 9.4 Data Flows

| Flow ID | Source | Destination | Data |
|---|---|---|---|
| F1 | User | Browser/Gradio UI | Owner name, account ID, deposit amount, withdrawal amount, symbol, quantity, report dates |
| F2 | Gradio UI | User | Status messages, account summary, holdings, transactions, P/L |
| F3 | Gradio UI | Account Service | Account commands |
| F4 | Account Service | In-Memory Account Store | Create/read/update account data |
| F5 | Account Service | Transaction Ledger | Append transaction entries |
| F6 | Account Service | Price Lookup | Symbol |
| F7 | Price Lookup | Account Service | Current price |
| F8 | Reporting Engine | Transaction Ledger | Read transaction history |
| F9 | Reporting Engine | Price Lookup | Symbol for market valuation |
| F10 | Reporting Engine | Gradio UI | Snapshot, holdings, P/L, transactions |

---

### 9.5 Trust Boundaries

| Boundary | Description |
|---|---|
| TB1: Browser to Gradio Server | User input crosses from untrusted client into server process |
| TB2: Gradio UI to Backend Service | UI calls backend methods; backend must still validate all input |
| TB3: Backend to Price Provider | Price lookup dependency must be handled safely |
| TB4: Process Memory | In-memory data is trusted only within current Python process |

---

### 9.6 Assets

| Asset | Security Goal |
|---|---|
| Account balances | Integrity |
| Holdings | Integrity |
| Transaction ledger | Integrity, non-repudiation within simulation constraints |
| Account IDs | Confidentiality-ish bearer identifiers |
| Profit/loss calculations | Integrity |
| Application availability | Availability |

---

### 9.7 Security Assumptions

- This is a local simulation, not a real brokerage.
- No real money is moved.
- No personally sensitive information should be collected beyond display owner name.
- Account IDs are bearer references, not strong authentication.
- In-memory data is lost when the process restarts.
- Gradio endpoints may be callable directly; therefore all validation must be in backend.
- Price source is local deterministic test code.
- The app is not intended to be exposed publicly without adding authentication, TLS, rate limiting, and persistent storage protections.

---

## 10. STRIDE Threat Table

The threat modeller should include at least the following.

| STRIDE | Threat | Area | Impact | Mitigation |
|---|---|---|---|---|
| Spoofing | User guesses another account ID and operates that account | Account access | Unauthorized simulated trades | Document limitation; generate high-entropy UUIDs; future auth required |
| Tampering | User submits negative deposit or malformed quantity | Backend commands | Incorrect balances | Backend validation for all values |
| Tampering | Direct Gradio API call bypasses UI controls | UI/backend boundary | Invalid state | Do not rely on frontend validation |
| Tampering | Concurrent buy/withdraw requests overspend cash | Backend/repository | Negative balance | Repository/service locking around mutations |
| Repudiation | User denies making transaction | Ledger | Dispute in simulation | Append transaction records with timestamps and IDs |
| Information Disclosure | Account list exposes all account IDs | UI | Other users can see account IDs | Acceptable for local demo; hide account list or add auth for public use |
| Information Disclosure | Tracebacks reveal internals | UI | Leaks implementation details | Catch expected errors and return safe messages |
| Denial of Service | Huge input values or long strings | Backend | Memory/CPU issues | Length and max value validation |
| Denial of Service | Excessive Gradio requests | Server | Slow or unavailable app | Use Gradio queue concurrency limit; future rate limiting |
| Elevation of Privilege | User modifies account by using another account ID | Account operations | Unauthorized control | Future authentication/authorization; current UUID hard-to-guess mitigation |
| Integrity | Unsupported symbol causes crash | Price lookup | Availability issue | Controlled `UnsupportedSymbolError` |
| Integrity | Floating point rounding errors | Money calculations | Incorrect balances | Use `Decimal` internally |

---

## 11. Backend Security Requirements

The backend engineer must implement:

1. Centralized validation in `backend.py`.
2. `Decimal` for all monetary calculations.
3. Positive-only deposit/withdrawal amounts.
4. Positive integer-only share quantities.
5. Controlled errors for invalid inputs.
6. Atomic service methods protected by repository or service lock.
7. Append-only transaction creation through service methods only.
8. UUID-based account IDs and transaction IDs.
9. Timezone-aware UTC timestamps.
10. No dynamic code execution.
11. No file writes required for account data.
12. Safe symbol normalization.

---

## 12. Frontend Security Requirements

The frontend engineer must implement:

1. Catch `TradingSimulationError`.
2. Do not show raw stack traces to users.
3. Do not trust Gradio `Number` component values.
4. Avoid user-controlled HTML rendering.
5. Use text/dataframe outputs.
6. Keep launch simple:
   ```python
   demo.queue(default_concurrency_limit=4).launch()
   ```
7. Do not enable public sharing by default.
8. Do not persist user data to files.

---

## 13. Backend Engineer Assignment

Owner: `backend_engineer`

Create `backend.py`.

### Required Deliverables

Implement the following public API.

#### Exceptions

```python
class TradingSimulationError(Exception): ...
class ValidationError(TradingSimulationError): ...
class AccountNotFoundError(TradingSimulationError): ...
class InsufficientFundsError(TradingSimulationError): ...
class InsufficientHoldingsError(TradingSimulationError): ...
class UnsupportedSymbolError(TradingSimulationError): ...
```

#### Enums/Data Classes

```python
class TransactionType(Enum): ...
```

```python
@dataclass(frozen=True)
class Transaction: ...
```

```python
@dataclass
class Account: ...
```

```python
@dataclass(frozen=True)
class PortfolioSnapshot: ...
```

#### Price Provider

```python
def get_share_price(symbol: str) -> Decimal: ...
```

#### Validation

```python
def normalize_symbol(symbol: str) -> str: ...
def parse_money(value: str | int | float | Decimal, field_name: str) -> Decimal: ...
def parse_positive_quantity(value: str | int | float, field_name: str = "quantity") -> int: ...
def utc_now() -> datetime: ...
def parse_optional_as_of(value: str | datetime | None) -> datetime | None: ...
```

#### Repository

```python
class AccountRepository:
    def create(self, account: Account) -> None: ...
    def get(self, account_id: str) -> Account: ...
    def list_accounts(self) -> list[Account]: ...
    def save(self, account: Account) -> None: ...
```

```python
class InMemoryAccountRepository(AccountRepository):
    def __init__(self) -> None: ...
    def create(self, account: Account) -> None: ...
    def get(self, account_id: str) -> Account: ...
    def list_accounts(self) -> list[Account]: ...
    def save(self, account: Account) -> None: ...
    def clear(self) -> None: ...
```

#### Service

```python
class AccountService:
    def __init__(self, repository: AccountRepository) -> None: ...

    def create_account(self, owner_name: str, initial_deposit: str | int | float | Decimal) -> Account: ...

    def deposit(self, account_id: str, amount: str | int | float | Decimal) -> Transaction: ...

    def withdraw(self, account_id: str, amount: str | int | float | Decimal) -> Transaction: ...

    def buy_shares(self, account_id: str, symbol: str, quantity: str | int | float) -> Transaction: ...

    def sell_shares(self, account_id: str, symbol: str, quantity: str | int | float) -> Transaction: ...

    def get_account(self, account_id: str) -> Account: ...

    def list_accounts(self) -> list[Account]: ...

    def list_transactions(
        self,
        account_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Transaction]: ...

    def get_holdings_at(self, account_id: str, as_of: datetime | None = None) -> dict[str, int]: ...

    def get_cash_balance_at(self, account_id: str, as_of: datetime | None = None) -> Decimal: ...

    def get_portfolio_snapshot(
        self,
        account_id: str,
        as_of: datetime | None = None,
    ) -> PortfolioSnapshot: ...
```

#### Formatting Helpers

```python
def account_to_summary_rows(account: Account) -> list[list[str]]: ...
def accounts_to_rows(accounts: list[Account]) -> list[list[str]]: ...
def holdings_to_rows(snapshot: PortfolioSnapshot) -> list[list[str]]: ...
def transactions_to_rows(transactions: list[Transaction]) -> list[list[str]]: ...
def snapshot_to_summary_rows(snapshot: PortfolioSnapshot) -> list[list[str]]: ...
```

---

## 14. Frontend Engineer Assignment

Owner: `frontend_engineer`

Create `app.py`.

### Required Deliverables

1. Gradio 6 app with tabs:
   - Create Account
   - Funds
   - Trade
   - Reports
   - Transactions
2. Use one shared `AccountService`.
3. All backend calls go through frontend handler functions.
4. Handlers catch backend exceptions and return friendly error messages.
5. Dataframes use Gradio 6 `row_count`, `row_limits`, `column_count`, `column_limits`.

### Required Handler Signatures

```python
def ui_create_account(owner_name: str, initial_deposit: float | str) -> tuple[str, str, list[list[str]]]: ...
```

```python
def ui_refresh_accounts() -> list[list[str]]: ...
```

```python
def ui_deposit(account_id: str, amount: float | str) -> tuple[str, list[list[str]], list[list[str]]]: ...
```

```python
def ui_withdraw(account_id: str, amount: float | str) -> tuple[str, list[list[str]], list[list[str]]]: ...
```

```python
def ui_buy(account_id: str, symbol: str, quantity: float | str) -> tuple[str, list[list[str]], list[list[str]], list[list[str]]]: ...
```

```python
def ui_sell(account_id: str, symbol: str, quantity: float | str) -> tuple[str, list[list[str]], list[list[str]], list[list[str]]]: ...
```

```python
def ui_get_snapshot(account_id: str, as_of_iso: str | None) -> tuple[str, list[list[str]], list[list[str]]]: ...
```

```python
def ui_list_transactions(
    account_id: str,
    start_iso: str | None,
    end_iso: str | None,
) -> tuple[str, list[list[str]]]: ...
```

### Gradio Launch

Use:

```python
if __name__ == "__main__":
    demo.queue(default_concurrency_limit=4).launch()
```

Do not use:

```python
launch(share=True)
```

unless explicitly requested.

---

## 15. Test Engineer Assignment

Owner: `test_engineer`

Create `test_backend.py`.

### Required Deliverables

Use standard library `unittest`.

Cover:

- Account creation.
- Deposits.
- Withdrawals.
- Buy validation.
- Sell validation.
- Portfolio valuation.
- Profit/loss calculation.
- Historical holdings.
- Historical cash balance.
- Transaction listing.
- Unknown accounts.
- Unknown symbols.
- Fractional quantity rejection.
- Negative/zero input rejection.

### Required Test Command

Document and verify:

```bash
uv run python -m unittest test_backend.py
```

---

## 16. Threat Modeller Assignment

Owner: `threat_modeller`

Create `threat_model.md`.

### Required Deliverables

1. DFD using the entities, processes, data stores, flows, and trust boundaries in this design.
2. STRIDE table using the provided baseline threats.
3. Additional risks discovered during modelling.
4. Mitigation status:
   - Implemented now.
   - Accepted for local simulation.
   - Future hardening.
5. Explicit statement that this is not production brokerage software.
6. Explicit statement that account IDs are bearer references in this version.

### Questions Answered for Threat Modeller

#### Is there authentication?

No. This version has no authentication. Account IDs act as bearer references.

#### Is data persisted?

No. Data is stored in memory and lost on process restart.

#### Is real money involved?

No. This is a trading simulation only.

#### Is there external network access to price data?

No. `get_share_price(symbol)` is a local fixed-price test function.

#### Are users trusted?

No. All user input must be treated as untrusted.

#### Can Gradio endpoints be called directly?

Yes. Backend validation must not rely on UI constraints.

#### What are the most important assets?

- Account cash balances.
- Holdings.
- Transaction ledger.
- Profit/loss calculations.
- Account IDs.

#### What are the biggest known limitations?

- No authentication.
- No persistent audit log.
- No historical share prices.
- No production-grade authorization.
- No rate limiting beyond basic Gradio queue concurrency.

---

## 17. README Requirements

Create `README.md` with:

### App Run Command

```bash
uv run python app.py
```

### Test Command

```bash
uv run python -m unittest test_backend.py
```

### Supported Symbols

```text
AAPL = 150.00
TSLA = 250.00
GOOGL = 2800.00
```

### Notes

- This is a simulation.
- Data is in memory.
- No real trades occur.
- No real money is moved.
- Do not expose publicly without authentication and other hardening.

---

## 18. Acceptance Criteria

The system is complete when:

1. User can create account with initial deposit.
2. User can deposit funds.
3. User can withdraw funds if sufficient cash exists.
4. User cannot overdraft cash.
5. User can buy supported shares if sufficient cash exists.
6. User cannot buy unsupported symbols.
7. User cannot buy more than cash permits.
8. User can sell shares if sufficient holdings exist.
9. User cannot sell shares they do not own.
10. User can view holdings.
11. User can view total portfolio value.
12. User can view profit/loss.
13. User can view holdings as of a past timestamp.
14. User can view profit/loss as of a past timestamp.
15. User can list transactions over time.
16. Backend unit tests pass.
17. Gradio app launches successfully with `uv run python app.py`.
18. Threat model document exists with DFD and STRIDE table.
19. No third-party packages are used other than Gradio.
20. All files are in the same directory.