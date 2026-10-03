Here is the complete `test_backend.py` file content:

```python
import threading
import unittest
from decimal import Decimal

from backend import (
    AccountNotFoundError,
    AccountService,
    InMemoryAccountRepository,
    InsufficientFundsError,
    InsufficientHoldingsError,
    PortfolioSnapshot,
    SUPPORTED_SYMBOLS,
    TransactionType,
    UnsupportedSymbolError,
    ValidationError,
    account_to_summary_rows,
    accounts_to_rows,
    get_share_price,
    holdings_to_rows,
    snapshot_to_summary_rows,
    transactions_to_rows,
)


def make_service():
    return AccountService(InMemoryAccountRepository())


class AccountServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = make_service()
        self.account = self.service.create_account("Alice", "1000")
        self.account_id = self.account.account_id

    def test_create_account_with_initial_deposit(self):
        self.assertEqual(self.account.owner_name, "Alice")
        self.assertEqual(self.account.cash_balance, Decimal("1000.00"))
        self.assertEqual(self.account.initial_deposit, Decimal("1000.00"))
        self.assertEqual(len(self.account.transactions), 1)
        self.assertEqual(self.account.transactions[0].transaction_type, TransactionType.DEPOSIT)

    def test_create_account_rejects_empty_owner(self):
        with self.assertRaises(ValidationError):
            self.service.create_account("   ", 10)

    def test_create_account_rejects_non_positive_initial_deposit(self):
        for bad in [0, -1, "0", "-5", 0.001, True]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    self.service.create_account("Bob", bad)

    def test_deposit_increases_cash_balance(self):
        self.service.deposit(self.account_id, 250.10)
        self.assertEqual(self.service.get_account(self.account_id).cash_balance, Decimal("1250.10"))

    def test_deposit_rejects_negative_amount(self):
        with self.assertRaises(ValidationError):
            self.service.deposit(self.account_id, -10)

    def test_withdraw_decreases_cash_balance(self):
        self.service.withdraw(self.account_id, "250.10")
        self.assertEqual(self.service.get_account(self.account_id).cash_balance, Decimal("749.90"))

    def test_withdraw_rejects_overdraft(self):
        with self.assertRaises(InsufficientFundsError):
            self.service.withdraw(self.account_id, "1000.01")

    def test_withdraw_rejects_negative_amount(self):
        with self.assertRaises(ValidationError):
            self.service.withdraw(self.account_id, -1)

    def test_buy_shares_decreases_cash_and_increases_holdings(self):
        self.service.buy_shares(self.account_id, "aapl", 2)
        acc = self.service.get_account(self.account_id)
        self.assertEqual(acc.cash_balance, Decimal("700.00"))
        self.assertEqual(acc.holdings, {"AAPL": 2})

    def test_buy_rejects_insufficient_funds(self):
        with self.assertRaises(InsufficientFundsError):
            self.service.buy_shares(self.account_id, "GOOGL", 1)

    def test_buy_rejects_unknown_symbol(self):
        with self.assertRaises(UnsupportedSymbolError):
            self.service.buy_shares(self.account_id, "MSFT", 1)

    def test_buy_rejects_non_positive_quantity(self):
        for bad in [0, -1]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    self.service.buy_shares(self.account_id, "AAPL", bad)

    def test_buy_rejects_fractional_quantity(self):
        for bad in [1.5, "2.5"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    self.service.buy_shares(self.account_id, "AAPL", bad)

    def test_sell_shares_increases_cash_and_decreases_holdings(self):
        self.service.buy_shares(self.account_id, "AAPL", 2)
        self.service.sell_shares(self.account_id, "AAPL", 1)
        acc = self.service.get_account(self.account_id)
        self.assertEqual(acc.cash_balance, Decimal("850.00"))
        self.assertEqual(acc.holdings, {"AAPL": 1})

    def test_sell_rejects_insufficient_holdings(self):
        with self.assertRaises(InsufficientHoldingsError):
            self.service.sell_shares(self.account_id, "AAPL", 1)

    def test_sell_removes_zero_holding(self):
        self.service.buy_shares(self.account_id, "AAPL", 2)
        self.service.sell_shares(self.account_id, "AAPL", 2)
        self.assertEqual(self.service.get_account(self.account_id).holdings, {})

    def test_sell_rejects_unknown_symbol(self):
        with self.assertRaises(UnsupportedSymbolError):
            self.service.sell_shares(self.account_id, "XYZ", 1)

    def test_portfolio_snapshot_calculates_total_equity(self):
        self.service.buy_shares(self.account_id, "AAPL", 2)
        snapshot = self.service.get_portfolio_snapshot(self.account_id)
        self.assertEqual(snapshot.total_equity, Decimal("1000.00"))
        self.assertEqual(snapshot.holdings_market_value, Decimal("300.00"))

    def test_portfolio_snapshot_calculates_profit_loss_cashflow_adjusted(self):
        self.service.buy_shares(self.account_id, "AAPL", 2)
        snapshot = self.service.get_portfolio_snapshot(self.account_id)
        self.assertEqual(snapshot.profit_loss, Decimal("0.00"))

    def test_portfolio_snapshot_after_withdrawal_cashflow_adjusted(self):
        self.service.withdraw(self.account_id, 100)
        snapshot = self.service.get_portfolio_snapshot(self.account_id)
        self.assertEqual(snapshot.total_equity, Decimal("900.00"))
        self.assertEqual(snapshot.profit_loss, Decimal("0.00"))
        self.assertEqual(snapshot.change_from_initial_deposit, Decimal("-100.00"))

    def test_get_holdings_at_reconstructs_past_holdings(self):
        t1 = self.service.buy_shares(self.account_id, "AAPL", 2)
        t2 = self.service.buy_shares(self.account_id, "TSLA", 1)
        self.assertEqual(self.service.get_holdings_at(self.account_id, t1.timestamp), {"AAPL": 2})
        self.assertEqual(self.service.get_holdings_at(self.account_id, t2.timestamp), {"AAPL": 2, "TSLA": 1})
        self.assertEqual(self.service.get_holdings_at(self.account_id, "2000-01-01T00:00:00Z"), {})

    def test_get_cash_balance_at_reconstructs_past_balance(self):
        t1 = self.service.buy_shares(self.account_id, "AAPL", 2)
        t2 = self.service.deposit(self.account_id, 500)
        self.assertEqual(self.service.get_cash_balance_at(self.account_id, t1.timestamp), Decimal("700.00"))
        self.assertEqual(self.service.get_cash_balance_at(self.account_id, t2.timestamp.isoformat()), Decimal("1200.00"))

    def test_list_transactions_filters_by_time_range(self):
        t1 = self.service.deposit(self.account_id, 50)
        t2 = self.service.withdraw(self.account_id, 25)
        t3 = self.service.buy_shares(self.account_id, "AAPL", 1)
        txns = self.service.list_transactions(self.account_id, t1.timestamp, t2.timestamp)
        self.assertEqual([t.transaction_id for t in txns], [t1.transaction_id, t2.transaction_id])
        self.assertEqual(self.service.list_transactions(self.account_id)[0].transaction_type, TransactionType.DEPOSIT)
        with self.assertRaises(ValidationError):
            self.service.list_transactions(self.account_id, t3.timestamp, t2.timestamp)

    def test_get_unknown_account_raises_account_not_found(self):
        with self.assertRaises(AccountNotFoundError):
            self.service.get_account("missing")

    def test_account_defensive_copy(self):
        acc = self.service.get_account(self.account_id)
        acc.cash_balance = Decimal("999999.99")
        acc.holdings["AAPL"] = 100
        self.assertEqual(self.service.get_account(self.account_id).cash_balance, Decimal("1000.00"))
        self.assertEqual(self.service.get_account(self.account_id).holdings, {})

    def test_supported_symbols_and_price_lookup(self):
        self.assertEqual(tuple(SUPPORTED_SYMBOLS), ("AAPL", "TSLA", "GOOGL"))
        self.assertEqual(get_share_price("tsla"), Decimal("250.00"))

    def test_formatting_helpers(self):
        snapshot = self.service.get_portfolio_snapshot(self.account_id)
        self.assertEqual(len(account_to_summary_rows(self.service.get_account(self.account_id))), 7)
        self.assertEqual(len(accounts_to_rows(self.service.list_accounts())[0]), 5)
        self.assertEqual(holdings_to_rows(snapshot), [])
        self.assertEqual(len(snapshot_to_summary_rows(snapshot)), 8)
        self.assertEqual(len(transactions_to_rows(self.service.list_transactions(self.account_id))[0]), 9)

    def test_concurrent_withdrawals(self):
        errs = []

        def work():
            try:
                self.service.withdraw(self.account_id, 10)
            except InsufficientFundsError:
                errs.append(1)

        threads = [threading.Thread(target=work) for _ in range(150)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(self.service.get_account(self.account_id).cash_balance, Decimal("0.00"))
        self.assertEqual(len(errs), 50)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

Unit test results:
- Ran: 28 tests
- Passed: 28
- Failed: 0

Command used:
```bash
uv run python -m unittest test_backend.py
```