"""Backend for the trading simulation account management system.

This module contains the domain model, centralized input validation, an
in-memory repository, the account service (business rules + reporting), the
fixed-price share price provider, and formatting helpers for the UI.

Security notes (see threat_model.md):
* All input is treated as untrusted and validated here (T-03, T-04, T-05).
* Money is handled with ``Decimal`` only (T-23).
* Every state change happens under one lock, so the check and the update
  happen together (T-06).
* Transactions are immutable and only appended to the ledger (T-07, T-08).
* Each account's timestamps are UTC and strictly increasing, so replay order is
  always the same (T-28).
* The repository stores and returns defensive copies (T-13, T-20).
* Text length, number size, account count and ledger size are capped (T-14,
  T-15, T-29).
* Symbols are checked against an allowlist (T-17, T-22).
* Account and transaction IDs are random UUID4 values (T-01).
* Error messages never repeat back long or raw user input (T-11).
* No dynamic code execution, no file I/O, no logging of account IDs (T-30).
"""

from __future__ import annotations

import copy
import math
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import Enum

__all__ = [
    "TradingSimulationError",
    "ValidationError",
    "AccountNotFoundError",
    "InsufficientFundsError",
    "InsufficientHoldingsError",
    "UnsupportedSymbolError",
    "TransactionType",
    "SUPPORTED_SYMBOLS",
    "CURRENCY_QUANTIZATION",
    "Transaction",
    "Account",
    "PortfolioSnapshot",
    "get_share_price",
    "normalize_symbol",
    "parse_money",
    "parse_positive_quantity",
    "utc_now",
    "parse_optional_as_of",
    "AccountRepository",
    "InMemoryAccountRepository",
    "AccountService",
    "account_to_summary_rows",
    "accounts_to_rows",
    "holdings_to_rows",
    "transactions_to_rows",
    "snapshot_to_summary_rows",
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TradingSimulationError(Exception):
    """Base class for expected domain errors."""


class ValidationError(TradingSimulationError):
    """Raised when user input is invalid."""


class AccountNotFoundError(TradingSimulationError):
    """Raised when an account id does not exist."""


class InsufficientFundsError(TradingSimulationError):
    """Raised when cash balance is insufficient."""


class InsufficientHoldingsError(TradingSimulationError):
    """Raised when share holdings are insufficient."""


class UnsupportedSymbolError(ValidationError):
    """Raised when symbol is not supported by price provider.

    It subclasses ValidationError (which subclasses TradingSimulationError),
    so callers can catch it either way.
    """


# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------


class TransactionType(Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"


CURRENCY_QUANTIZATION: Decimal = Decimal("0.01")

_SHARE_PRICES: dict[str, Decimal] = {
    "AAPL": Decimal("150.00"),
    "TSLA": Decimal("250.00"),
    "GOOGL": Decimal("2800.00"),
}
SUPPORTED_SYMBOLS: tuple[str, ...] = tuple(_SHARE_PRICES.keys())

MAX_OWNER_NAME_LENGTH = 100
MAX_SYMBOL_LENGTH = 10
MAX_MONEY_AMOUNT = Decimal("1000000000")
MAX_QUANTITY = 1_000_000_000
MAX_CASH_BALANCE = Decimal("1000000000000000")  # 1e15 cap on stored cash
MAX_ACCOUNT_ID_LENGTH = 64
MAX_NUMERIC_INPUT_LENGTH = 40
MAX_TIMESTAMP_INPUT_LENGTH = 64
MAX_ACCOUNTS = 10_000
MAX_TRANSACTIONS_PER_ACCOUNT = 100_000

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


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


@dataclass
class Account:
    account_id: str
    owner_name: str
    created_at: datetime
    initial_deposit: Decimal
    cash_balance: Decimal
    holdings: dict[str, int] = field(default_factory=dict)
    transactions: list[Transaction] = field(default_factory=list)


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


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(CURRENCY_QUANTIZATION, rounding=ROUND_HALF_UP)


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def normalize_symbol(symbol: str) -> str:
    """Trim and uppercase a symbol; reject invalid or unsupported values."""
    if not isinstance(symbol, str):
        raise ValidationError("Symbol must be text.")
    cleaned = symbol.strip().upper()
    if not cleaned:
        raise ValidationError("Symbol is required.")
    if len(cleaned) > MAX_SYMBOL_LENGTH or not _SYMBOL_RE.match(cleaned):
        raise UnsupportedSymbolError(
            f"Unsupported symbol. Supported symbols: {', '.join(SUPPORTED_SYMBOLS)}."
        )
    if cleaned not in _SHARE_PRICES:
        raise UnsupportedSymbolError(
            f"Unsupported symbol '{cleaned}'. Supported symbols: {', '.join(SUPPORTED_SYMBOLS)}."
        )
    return cleaned


def get_share_price(symbol: str) -> Decimal:
    """Return current fixed share price for supported symbols."""
    normalized = normalize_symbol(symbol)
    return _SHARE_PRICES[normalized]


def _to_decimal(value: object, field_name: str) -> Decimal:
    """Convert untrusted input to a finite Decimal or raise ValidationError."""
    if isinstance(value, bool) or value is None:
        raise ValidationError(f"{field_name} must be a number.")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError(f"{field_name} must be a finite number.")
        result = Decimal(repr(value))  # shortest repr avoids binary artefacts
    elif isinstance(value, str):
        text = value.strip().replace(",", "").replace("_", "")
        if text.startswith("$"):
            text = text[1:].strip()
        if not text:
            raise ValidationError(f"{field_name} is required.")
        if len(text) > MAX_NUMERIC_INPUT_LENGTH:
            raise ValidationError(f"{field_name} is too long.")
        try:
            result = Decimal(text)
        except (InvalidOperation, ValueError):
            raise ValidationError(f"{field_name} must be a valid number.") from None
    else:
        raise ValidationError(f"{field_name} must be a number.")
    if not result.is_finite():
        raise ValidationError(f"{field_name} must be a finite number.")
    return result


def parse_money(value: str | int | float | Decimal, field_name: str) -> Decimal:
    """Convert a user-provided money value to a positive Decimal with two decimal places."""
    raw = _to_decimal(value, field_name)
    if raw <= 0:
        raise ValidationError(f"{field_name} must be greater than zero.")
    if raw > MAX_MONEY_AMOUNT:
        raise ValidationError(f"{field_name} must not exceed {MAX_MONEY_AMOUNT:,}.")
    amount = _quantize(raw)
    if amount <= 0:
        raise ValidationError(f"{field_name} must be at least 0.01.")
    return amount


def parse_positive_quantity(value: str | int | float, field_name: str = "quantity") -> int:
    """Convert a user-provided quantity to a positive integer."""
    raw = _to_decimal(value, field_name)
    if raw != raw.to_integral_value():
        raise ValidationError(f"{field_name} must be a whole number (no fractional shares).")
    if raw <= 0:
        raise ValidationError(f"{field_name} must be greater than zero.")
    if raw > MAX_QUANTITY:
        raise ValidationError(f"{field_name} must not exceed {MAX_QUANTITY:,}.")
    return int(raw)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_optional_as_of(value: str | datetime | None) -> datetime | None:
    """Parse optional ISO datetime for historical reports.

    Naive datetimes are treated as UTC. Empty strings mean "no value".
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_utc(value)
    if not isinstance(value, str):
        raise ValidationError("Timestamp must be an ISO-8601 string.")
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_TIMESTAMP_INPUT_LENGTH:
        raise ValidationError("Timestamp is too long.")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationError(
            "Timestamp must be ISO-8601, e.g. 2024-01-31T12:00:00+00:00."
        ) from None
    return _to_utc(parsed)


def _validate_owner_name(owner_name: str) -> str:
    if not isinstance(owner_name, str):
        raise ValidationError("Owner name must be text.")
    cleaned = owner_name.strip()
    if not cleaned:
        raise ValidationError("Owner name is required.")
    if len(cleaned) > MAX_OWNER_NAME_LENGTH:
        raise ValidationError(
            f"Owner name must be at most {MAX_OWNER_NAME_LENGTH} characters."
        )
    if _CONTROL_CHARS_RE.search(cleaned):
        raise ValidationError("Owner name contains invalid characters.")
    return cleaned


def _normalize_account_id(account_id: str) -> str:
    if not isinstance(account_id, str):
        raise AccountNotFoundError("Account not found.")
    cleaned = account_id.strip()
    if not cleaned or len(cleaned) > MAX_ACCOUNT_ID_LENGTH:
        raise AccountNotFoundError("Account not found.")
    return cleaned


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class AccountRepository:
    """Abstract persistence boundary for accounts."""

    def create(self, account: Account) -> None:
        raise NotImplementedError

    def get(self, account_id: str) -> Account:
        raise NotImplementedError

    def list_accounts(self) -> list[Account]:
        raise NotImplementedError

    def save(self, account: Account) -> None:
        raise NotImplementedError


def _copy_account(account: Account) -> Account:
    # Transactions are frozen dataclasses, so copying the list is enough.
    return Account(
        account_id=account.account_id,
        owner_name=account.owner_name,
        created_at=account.created_at,
        initial_deposit=account.initial_deposit,
        cash_balance=account.cash_balance,
        holdings=dict(account.holdings),
        transactions=list(account.transactions),
    )


class InMemoryAccountRepository(AccountRepository):
    """Thread-safe in-memory store. Stores and returns defensive copies."""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._lock = threading.RLock()

    def create(self, account: Account) -> None:
        with self._lock:
            if account.account_id in self._accounts:
                raise ValidationError("Account already exists.")
            if len(self._accounts) >= MAX_ACCOUNTS:
                raise ValidationError("Maximum number of accounts reached.")
            self._accounts[account.account_id] = _copy_account(account)

    def get(self, account_id: str) -> Account:
        key = _normalize_account_id(account_id)
        with self._lock:
            account = self._accounts.get(key)
            if account is None:
                raise AccountNotFoundError("Account not found.")
            return _copy_account(account)

    def list_accounts(self) -> list[Account]:
        with self._lock:
            accounts = [_copy_account(a) for a in self._accounts.values()]
        accounts.sort(key=lambda a: a.created_at)
        return accounts

    def save(self, account: Account) -> None:
        with self._lock:
            if account.account_id not in self._accounts:
                raise AccountNotFoundError("Account not found.")
            self._accounts[account.account_id] = _copy_account(account)

    def clear(self) -> None:
        with self._lock:
            self._accounts.clear()


# ---------------------------------------------------------------------------
# Account service
# ---------------------------------------------------------------------------


class AccountService:
    """Business rules, ledger management and reporting."""

    def __init__(self, repository: AccountRepository) -> None:
        if repository is None:
            raise ValueError("repository is required")
        self._repository = repository
        # One lock serializes every read-modify-write so checks and updates
        # happen together (no overdraft or overselling under concurrency).
        self._lock = threading.RLock()

    # -- internal helpers --------------------------------------------------

    @staticmethod
    def _next_timestamp(account: Account | None) -> datetime:
        """Return a UTC timestamp strictly greater than the last ledger entry."""
        now = utc_now()
        if account is not None and account.transactions:
            last = account.transactions[-1].timestamp
            if now <= last:
                now = last + timedelta(microseconds=1)
        return now

    @staticmethod
    def _ensure_ledger_capacity(account: Account) -> None:
        if len(account.transactions) >= MAX_TRANSACTIONS_PER_ACCOUNT:
            raise ValidationError("Transaction limit reached for this account.")

    @staticmethod
    def _make_transaction(
        account: Account,
        transaction_type: TransactionType,
        cash_delta: Decimal,
        amount: Decimal | None = None,
        symbol: str | None = None,
        quantity: int | None = None,
        price: Decimal | None = None,
        notes: str = "",
        timestamp: datetime | None = None,
    ) -> Transaction:
        return Transaction(
            transaction_id=str(uuid.uuid4()),
            account_id=account.account_id,
            transaction_type=transaction_type,
            timestamp=timestamp or AccountService._next_timestamp(account),
            amount=amount,
            symbol=symbol,
            quantity=quantity,
            price=price,
            cash_delta=cash_delta,
            notes=notes,
        )

    # -- commands ------------------------------------------------------------

    def create_account(
        self, owner_name: str, initial_deposit: str | int | float | Decimal
    ) -> Account:
        """Create an account with an initial deposit transaction."""
        name = _validate_owner_name(owner_name)
        amount = parse_money(initial_deposit, "Initial deposit")
        with self._lock:
            created_at = utc_now()
            account = Account(
                account_id=str(uuid.uuid4()),
                owner_name=name,
                created_at=created_at,
                initial_deposit=amount,
                cash_balance=amount,
                holdings={},
                transactions=[],
            )
            txn = self._make_transaction(
                account,
                TransactionType.DEPOSIT,
                cash_delta=amount,
                amount=amount,
                notes="Initial deposit",
                timestamp=created_at,
            )
            account.transactions.append(txn)
            self._repository.create(account)
            return _copy_account(account)

    def deposit(self, account_id: str, amount: str | int | float | Decimal) -> Transaction:
        """Deposit funds into an account."""
        value = parse_money(amount, "Deposit amount")
        with self._lock:
            account = self._repository.get(account_id)
            self._ensure_ledger_capacity(account)
            new_balance = account.cash_balance + value
            if new_balance > MAX_CASH_BALANCE:
                raise ValidationError("Deposit would exceed the maximum allowed balance.")
            txn = self._make_transaction(
                account, TransactionType.DEPOSIT, cash_delta=value, amount=value,
                notes="Deposit",
            )
            account.cash_balance = new_balance
            account.transactions.append(txn)
            self._repository.save(account)
            return txn

    def withdraw(self, account_id: str, amount: str | int | float | Decimal) -> Transaction:
        """Withdraw funds from an account if cash balance remains non-negative."""
        value = parse_money(amount, "Withdrawal amount")
        with self._lock:
            account = self._repository.get(account_id)
            self._ensure_ledger_capacity(account)
            if value > account.cash_balance:
                raise InsufficientFundsError(
                    f"Insufficient funds: requested {value:,.2f}, "
                    f"available {account.cash_balance:,.2f}."
                )
            txn = self._make_transaction(
                account, TransactionType.WITHDRAWAL, cash_delta=-value, amount=value,
                notes="Withdrawal",
            )
            account.cash_balance = account.cash_balance - value
            account.transactions.append(txn)
            self._repository.save(account)
            return txn

    def buy_shares(self, account_id: str, symbol: str, quantity: str | int | float) -> Transaction:
        """Buy shares if account has sufficient cash."""
        sym = normalize_symbol(symbol)
        qty = parse_positive_quantity(quantity)
        with self._lock:
            account = self._repository.get(account_id)
            self._ensure_ledger_capacity(account)
            price = get_share_price(sym)
            cost = _quantize(price * qty)
            if cost > account.cash_balance:
                raise InsufficientFundsError(
                    f"Insufficient funds: buying {qty} {sym} costs {cost:,.2f}, "
                    f"available {account.cash_balance:,.2f}."
                )
            txn = self._make_transaction(
                account, TransactionType.BUY, cash_delta=-cost, amount=cost,
                symbol=sym, quantity=qty, price=price,
                notes=f"Bought {qty} {sym} @ {price:,.2f}",
            )
            account.cash_balance = account.cash_balance - cost
            account.holdings[sym] = account.holdings.get(sym, 0) + qty
            account.transactions.append(txn)
            self._repository.save(account)
            return txn

    def sell_shares(self, account_id: str, symbol: str, quantity: str | int | float) -> Transaction:
        """Sell shares if account has sufficient holdings."""
        sym = normalize_symbol(symbol)
        qty = parse_positive_quantity(quantity)
        with self._lock:
            account = self._repository.get(account_id)
            self._ensure_ledger_capacity(account)
            owned = account.holdings.get(sym, 0)
            if owned < qty:
                raise InsufficientHoldingsError(
                    f"Insufficient holdings: trying to sell {qty} {sym}, own {owned}."
                )
            price = get_share_price(sym)
            proceeds = _quantize(price * qty)
            txn = self._make_transaction(
                account, TransactionType.SELL, cash_delta=proceeds, amount=proceeds,
                symbol=sym, quantity=qty, price=price,
                notes=f"Sold {qty} {sym} @ {price:,.2f}",
            )
            account.cash_balance = account.cash_balance + proceeds
            remaining = owned - qty
            if remaining:
                account.holdings[sym] = remaining
            else:
                account.holdings.pop(sym, None)
            account.transactions.append(txn)
            self._repository.save(account)
            return txn

    # -- queries -------------------------------------------------------------

    def get_account(self, account_id: str) -> Account:
        """Return account by id (a defensive copy)."""
        with self._lock:
            return self._repository.get(account_id)

    def list_accounts(self) -> list[Account]:
        """Return all accounts (defensive copies)."""
        with self._lock:
            return self._repository.list_accounts()

    def list_transactions(
        self,
        account_id: str,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
    ) -> list[Transaction]:
        """Return transactions for an account, optionally filtered by inclusive time range."""
        start_dt = parse_optional_as_of(start)
        end_dt = parse_optional_as_of(end)
        if start_dt is not None and end_dt is not None and start_dt > end_dt:
            raise ValidationError("Start time must not be after end time.")
        account = self.get_account(account_id)
        # sorted() is stable, so entries with the same timestamp stay in append order.
        txns = sorted(account.transactions, key=lambda t: t.timestamp)
        if start_dt is not None:
            txns = [t for t in txns if t.timestamp >= start_dt]
        if end_dt is not None:
            txns = [t for t in txns if t.timestamp <= end_dt]
        return txns

    @staticmethod
    def _replay(
        transactions: list[Transaction], as_of: datetime | None
    ) -> tuple[Decimal, dict[str, int], Decimal, Decimal, list[Transaction]]:
        cash = Decimal("0.00")
        holdings: dict[str, int] = {}
        deposits = Decimal("0.00")
        withdrawals = Decimal("0.00")
        applied: list[Transaction] = []
        for txn in sorted(transactions, key=lambda t: t.timestamp):
            if as_of is not None and txn.timestamp > as_of:
                break
            applied.append(txn)
            cash += txn.cash_delta
            ttype = txn.transaction_type
            if ttype is TransactionType.DEPOSIT:
                deposits += txn.amount or Decimal("0")
            elif ttype is TransactionType.WITHDRAWAL:
                withdrawals += txn.amount or Decimal("0")
            elif ttype is TransactionType.BUY and txn.symbol and txn.quantity:
                holdings[txn.symbol] = holdings.get(txn.symbol, 0) + txn.quantity
            elif ttype is TransactionType.SELL and txn.symbol and txn.quantity:
                remaining = holdings.get(txn.symbol, 0) - txn.quantity
                if remaining > 0:
                    holdings[txn.symbol] = remaining
                else:
                    holdings.pop(txn.symbol, None)
        return _quantize(cash), holdings, _quantize(deposits), _quantize(withdrawals), applied

    def get_holdings_at(self, account_id: str, as_of: datetime | str | None = None) -> dict[str, int]:
        """Reconstruct holdings as of timestamp using ledger replay."""
        as_of_dt = parse_optional_as_of(as_of)
        account = self.get_account(account_id)
        _, holdings, _, _, _ = self._replay(account.transactions, as_of_dt)
        return dict(sorted(holdings.items()))

    def get_cash_balance_at(self, account_id: str, as_of: datetime | str | None = None) -> Decimal:
        """Reconstruct cash balance as of timestamp using ledger replay."""
        as_of_dt = parse_optional_as_of(as_of)
        account = self.get_account(account_id)
        cash, _, _, _, _ = self._replay(account.transactions, as_of_dt)
        return cash

    def get_portfolio_snapshot(
        self,
        account_id: str,
        as_of: datetime | str | None = None,
    ) -> PortfolioSnapshot:
        """Return cash, holdings, value, and P/L as of timestamp.

        Market value always uses *current* prices; there is no historical price
        source (a documented limitation).
        """
        as_of_dt = parse_optional_as_of(as_of)
        account = self.get_account(account_id)
        cash, holdings, deposits, withdrawals, applied = self._replay(
            account.transactions, as_of_dt
        )
        market_value = Decimal("0.00")
        for sym, qty in holdings.items():
            market_value += get_share_price(sym) * qty
        market_value = _quantize(market_value)
        equity = _quantize(cash + market_value)
        # Only count the initial deposit if it is inside the requested window.
        initial = account.initial_deposit if applied else Decimal("0.00")
        report_time = as_of_dt if as_of_dt is not None else utc_now()
        return PortfolioSnapshot(
            account_id=account.account_id,
            as_of=report_time,
            cash_balance=cash,
            holdings=dict(sorted(holdings.items())),
            holdings_market_value=market_value,
            total_equity=equity,
            total_deposits=deposits,
            total_withdrawals=withdrawals,
            profit_loss=_quantize(equity + withdrawals - deposits),
            change_from_initial_deposit=_quantize(equity - initial),
        )


# ---------------------------------------------------------------------------
# Formatting helpers for UI (plain strings only; no HTML)
# ---------------------------------------------------------------------------


def _fmt_money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{_quantize(value):,.2f}"


def _fmt_signed_money(value: Decimal) -> str:
    q = _quantize(value)
    return f"+{q:,.2f}" if q > 0 else f"{q:,.2f}"


def _fmt_time(value: datetime) -> str:
    return _to_utc(value).isoformat()


def account_to_summary_rows(account: Account) -> list[list[str]]:
    """Convert account summary into rows suitable for gr.Dataframe."""
    holdings_text = ", ".join(
        f"{sym}: {qty}" for sym, qty in sorted(account.holdings.items()) if qty
    ) or "None"
    return [
        ["Account ID", account.account_id],
        ["Owner", account.owner_name],
        ["Created At", _fmt_time(account.created_at)],
        ["Initial Deposit", _fmt_money(account.initial_deposit)],
        ["Cash Balance", _fmt_money(account.cash_balance)],
        ["Holdings", holdings_text],
        ["Transactions", str(len(account.transactions))],
    ]


def accounts_to_rows(accounts: list[Account]) -> list[list[str]]:
    """Convert accounts into rows: Account ID, Owner, Created At, Cash Balance, Initial Deposit."""
    return [
        [
            a.account_id,
            a.owner_name,
            _fmt_time(a.created_at),
            _fmt_money(a.cash_balance),
            _fmt_money(a.initial_deposit),
        ]
        for a in accounts
    ]


def holdings_to_rows(snapshot: PortfolioSnapshot) -> list[list[str]]:
    """Convert holdings snapshot into rows: Symbol, Quantity, Current Price, Market Value."""
    rows: list[list[str]] = []
    for sym, qty in sorted(snapshot.holdings.items()):
        if qty <= 0:
            continue
        price = get_share_price(sym)
        rows.append([sym, str(qty), _fmt_money(price), _fmt_money(price * qty)])
    return rows


def transactions_to_rows(transactions: list[Transaction]) -> list[list[str]]:
    """Convert transactions into rows suitable for gr.Dataframe.

    Columns: Timestamp, Transaction ID, Type, Symbol, Quantity, Price, Amount,
    Cash Delta, Notes.
    """
    return [
        [
            _fmt_time(t.timestamp),
            t.transaction_id,
            t.transaction_type.value,
            t.symbol or "",
            "" if t.quantity is None else str(t.quantity),
            _fmt_money(t.price),
            _fmt_money(t.amount),
            _fmt_signed_money(t.cash_delta),
            t.notes,
        ]
        for t in transactions
    ]


def snapshot_to_summary_rows(snapshot: PortfolioSnapshot) -> list[list[str]]:
    """Convert portfolio snapshot into Metric/Value rows suitable for gr.Dataframe."""
    return [
        ["As Of", _fmt_time(snapshot.as_of)],
        ["Cash Balance", _fmt_money(snapshot.cash_balance)],
        ["Holdings Market Value", _fmt_money(snapshot.holdings_market_value)],
        ["Total Equity", _fmt_money(snapshot.total_equity)],
        ["Total Deposits", _fmt_money(snapshot.total_deposits)],
        ["Total Withdrawals", _fmt_money(snapshot.total_withdrawals)],
        ["Profit/Loss", _fmt_signed_money(snapshot.profit_loss)],
        ["Change From Initial Deposit", _fmt_signed_money(snapshot.change_from_initial_deposit)],
    ]
