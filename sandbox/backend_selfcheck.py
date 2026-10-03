import threading
import unittest
from decimal import Decimal

from backend import *  # noqa
from backend import AccountService, InMemoryAccountRepository


def svc():
    return AccountService(InMemoryAccountRepository())


class T(unittest.TestCase):
    def setUp(self):
        self.s = svc()
        self.a = self.s.create_account("Alice", "1000")
        self.id = self.a.account_id

    def test_create(self):
        self.assertEqual(self.a.cash_balance, Decimal("1000.00"))
        self.assertEqual(len(self.a.transactions), 1)
        self.assertEqual(self.a.transactions[0].transaction_type, TransactionType.DEPOSIT)
        self.assertIsNotNone(self.a.created_at.tzinfo)
        for bad in ["", "   ", "x" * 101, "a\x00b", None]:
            with self.assertRaises(ValidationError):
                self.s.create_account(bad, 10)
        for bad in [0, -5, "abc", float("nan"), float("inf"), "1e10", True, "0.001", None, "NaN"]:
            with self.assertRaises(ValidationError):
                self.s.create_account("Bob", bad)

    def test_funds(self):
        self.s.deposit(self.id, 250.10)
        self.assertEqual(self.s.get_account(self.id).cash_balance, Decimal("1250.10"))
        self.s.withdraw(self.id, "250.10")
        self.assertEqual(self.s.get_account(self.id).cash_balance, Decimal("1000.00"))
        with self.assertRaises(InsufficientFundsError):
            self.s.withdraw(self.id, "1000.01")
        self.s.withdraw(self.id, 1000)
        self.assertEqual(self.s.get_account(self.id).cash_balance, Decimal("0"))
        with self.assertRaises(ValidationError):
            self.s.deposit(self.id, -1)
        with self.assertRaises(ValidationError):
            self.s.withdraw(self.id, 0)

    def test_trades(self):
        self.s.buy_shares(self.id, " aapl ", 2)
        acc = self.s.get_account(self.id)
        self.assertEqual(acc.cash_balance, Decimal("700.00"))
        self.assertEqual(acc.holdings, {"AAPL": 2})
        with self.assertRaises(InsufficientFundsError):
            self.s.buy_shares(self.id, "GOOGL", 1)
        for bad in ["XYZ", "UNKNOWNSYMBOL", "<script>"]:
            with self.assertRaises(UnsupportedSymbolError):
                self.s.buy_shares(self.id, bad, 1)
            with self.assertRaises(UnsupportedSymbolError):
                self.s.sell_shares(self.id, bad, 1)
        for bad in [0, -1, 1.5, "2.5", "abc", True]:
            with self.assertRaises(ValidationError):
                self.s.buy_shares(self.id, "AAPL", bad)
        self.s.buy_shares(self.id, "AAPL", 2.0)
        with self.assertRaises(InsufficientHoldingsError):
            self.s.sell_shares(self.id, "AAPL", 5)
        with self.assertRaises(InsufficientHoldingsError):
            self.s.sell_shares(self.id, "TSLA", 1)
        self.s.sell_shares(self.id, "AAPL", "4")
        acc = self.s.get_account(self.id)
        self.assertEqual(acc.holdings, {})
        self.assertEqual(acc.cash_balance, Decimal("1000.00"))

    def test_snapshot_and_history(self):
        t1 = self.s.buy_shares(self.id, "AAPL", 2)
        snap = self.s.get_portfolio_snapshot(self.id)
        self.assertEqual(snap.total_equity, Decimal("1000.00"))
        self.assertEqual(snap.profit_loss, Decimal("0.00"))
        t2 = self.s.deposit(self.id, 500)
        t3 = self.s.buy_shares(self.id, "TSLA", 1)
        t4 = self.s.withdraw(self.id, 100)
        snap = self.s.get_portfolio_snapshot(self.id)
        self.assertEqual(snap.total_equity, Decimal("1400.00"))
        self.assertEqual(snap.profit_loss, Decimal("0.00"))
        self.assertEqual(snap.change_from_initial_deposit, Decimal("400.00"))
        self.assertEqual(self.s.get_holdings_at(self.id, t1.timestamp), {"AAPL": 2})
        self.assertEqual(self.s.get_holdings_at(self.id, t3.timestamp), {"AAPL": 2, "TSLA": 1})
        self.assertEqual(self.s.get_cash_balance_at(self.id, t1.timestamp), Decimal("700.00"))
        self.assertEqual(self.s.get_cash_balance_at(self.id, t2.timestamp.isoformat()), Decimal("1200.00"))
        self.assertEqual(self.s.get_cash_balance_at(self.id), Decimal("850.00"))
        txs = self.s.list_transactions(self.id, t2.timestamp, t3.timestamp)
        self.assertEqual([t.transaction_id for t in txs], [t2.transaction_id, t3.transaction_id])
        self.assertEqual(len(self.s.list_transactions(self.id)), 5)
        ts = [t.timestamp for t in self.s.list_transactions(self.id)]
        self.assertEqual(ts, sorted(set(ts)))
        with self.assertRaises(ValidationError):
            self.s.list_transactions(self.id, t3.timestamp, t2.timestamp)
        with self.assertRaises(ValidationError):
            self.s.get_portfolio_snapshot(self.id, "not a date")
        old = self.s.get_portfolio_snapshot(self.id, "2000-01-01T00:00:00Z")
        self.assertEqual(old.total_equity, Decimal("0.00"))
        self.assertEqual(old.change_from_initial_deposit, Decimal("0.00"))
        # formatting
        self.assertEqual(len(snapshot_to_summary_rows(snap)), 8)
        self.assertEqual(holdings_to_rows(snap)[0], ["AAPL", "2", "150.00", "300.00"])
        self.assertEqual(len(transactions_to_rows(txs)[0]), 9)
        self.assertEqual(len(accounts_to_rows(self.s.list_accounts())[0]), 5)
        self.assertTrue(account_to_summary_rows(self.s.get_account(self.id)))
        self.assertTrue(all(isinstance(c, str) for r in transactions_to_rows(txs) for c in r))

    def test_isolation_and_lookup(self):
        acc = self.s.get_account(self.id)
        acc.cash_balance = Decimal("999999")
        acc.holdings["AAPL"] = 100
        self.assertEqual(self.s.get_account(self.id).cash_balance, Decimal("1000.00"))
        self.assertEqual(self.s.get_account(self.id).holdings, {})
        for bad in ["nope", "", None, "x" * 1000, 123]:
            with self.assertRaises(AccountNotFoundError):
                self.s.get_account(bad)
        self.assertEqual(get_share_price("tsla"), Decimal("250.00"))

    def test_concurrency(self):
        errs = []

        def work():
            try:
                self.s.withdraw(self.id, 10)
            except InsufficientFundsError:
                errs.append(1)

        threads = [threading.Thread(target=work) for _ in range(150)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(self.s.get_account(self.id).cash_balance, Decimal("0.00"))
        self.assertEqual(len(errs), 50)


if __name__ == "__main__":
    unittest.main(verbosity=1)
