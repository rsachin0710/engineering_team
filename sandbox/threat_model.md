# Threat Model: Trading Simulation Account Management System

## 1. Executive Summary

This document is the technical architecture and threat model for a **simple trading simulation account management system** built with a **Gradio 6 UI** and an **in-memory Python backend**.

This is **not production brokerage software**. It does **not** move real money, does **not** connect to real markets, and does **not** implement authentication or authorization in this version. The system uses **account IDs as bearer references**: anyone who knows an account ID can operate that account in the currently running process.

The primary security objective is to protect:
- integrity of cash balances and holdings,
- integrity of transaction history,
- correctness of profit/loss and historical reports,
- availability of the local simulation app,
- confidentiality of account identifiers insofar as they function as bearer tokens.

---

## 2. Technical Architecture Document

### 2.1 System Purpose

The system allows a user to:
- create a simulated trading account,
- deposit and withdraw funds,
- buy and sell supported shares,
- inspect current holdings,
- compute portfolio value and profit/loss,
- list transactions over time,
- reconstruct holdings and cash balance at a prior point in time.

### 2.2 Assumptions

Where the design is silent, the following assumptions are made explicitly:

1. **Local-only execution**  
   The application runs in a local Python process and is not intentionally exposed to the public internet.

2. **No authentication / authorization**  
   There is no login, password, API key, session management, MFA, or RBAC.  
   The account ID is the only reference needed to operate an account.

3. **No persistence**  
   All account data and transaction data are stored in memory only and are lost on restart.

4. **No external database**  
   There is no file-backed datastore and no database server.

5. **No real brokerage or payment processor**  
   Deposits and withdrawals are simulation state changes only.

6. **No network price service**  
   `get_share_price(symbol)` is a local function returning fixed test prices.

7. **Single-process trust model**  
   All data is trusted only within the current Python process boundary; any input from UI/browser is untrusted.

8. **Historical valuation limitation**  
   Historical holdings and cash are reconstructed from the ledger, but market value uses current share prices because no historical oracle exists.

9. **Concurrency is possible**  
   Gradio may process requests concurrently, so backend state changes must be serialized/locked.

### 2.3 Components

#### External Entities
- **User**
  - Human operator of the simulation.
  - Supplies account creation data, transaction requests, and report parameters.
- **Browser**
  - Client used to reach the Gradio UI.
  - Treated as an untrusted presentation endpoint.
- **Price Provider Function**
  - Local function `get_share_price(symbol)` returning fixed supported prices.

#### Processes
- **P1: Gradio UI (`app.py`)**
  - Receives user input.
  - Calls backend service methods directly in-process.
  - Renders results in text and data tables.
- **P2: Account Service (`backend.py`)**
  - Validates requests.
  - Enforces business rules for deposits, withdrawals, buys, sells.
  - Creates transactions and updates materialized account state.
- **P3: Reporting Engine (`backend.py`)**
  - Replays transaction ledger to reconstruct historical holdings/cash.
  - Computes portfolio snapshots and profit/loss.
- **P4: Price Lookup (`get_share_price`)**
  - Returns current fixed prices for supported symbols.

#### Data Stores
- **D1: In-Memory Account Store**
  - Dictionary keyed by `account_id`.
  - Stores `Account` objects.
- **D2: Transaction Ledger**
  - Append-only list of `Transaction` objects inside each account.

### 2.4 Data Formats

#### Input Formats
- **Owner name**: string
- **Account ID**: string (opaque UUID-like identifier)
- **Money amounts**: user input may arrive as string, int, float, or Decimal; normalized to `Decimal`
- **Quantities**: user input may arrive as string, int, or float; normalized to positive integers
- **Symbols**: string, normalized to uppercase
- **Timestamps**: ISO-8601 strings or Python `datetime` objects

#### Internal Formats
- **Currency**: `Decimal` quantized to two decimal places
- **Share quantities**: `int`
- **Timestamps**: timezone-aware UTC `datetime`
- **Transactions**: immutable dataclass records
- **Accounts**: mutable dataclass objects managed only by backend service

#### Output Formats
- **UI status**: plain text
- **Accounts table**: rows of strings for `gr.Dataframe`
- **Portfolio summary**: rows of strings for `gr.Dataframe`
- **Holdings table**: rows of strings for `gr.Dataframe`
- **Transactions table**: rows of strings for `gr.Dataframe`

### 2.5 Trust Boundaries

| Boundary ID | Boundary | Description |
|---|---|---|
| TB1 | Browser → Gradio UI | Untrusted user input crosses from client into server/UI process. |
| TB2 | Gradio UI → Backend Service | UI invokes backend methods directly; backend must not trust UI validation. |
| TB3 | Backend Service → Price Provider | Backend relies on local price lookup function for current valuation. |
| TB4 | Process Memory Boundary | In-memory state is trusted only inside current process and lifetime. |

### 2.6 Assets

| Asset | Security Property | Why It Matters |
|---|---|---|
| Cash balances | Integrity | Must not go negative or be altered incorrectly. |
| Holdings | Integrity | Must not be forged, duplicated, or deleted incorrectly. |
| Transaction ledger | Integrity / auditability | Source of truth for historical reconstruction. |
| Account IDs | Confidentiality-ish / bearer integrity | Anyone with an ID can act on the account. |
| Portfolio snapshot / P&L | Integrity | Used for reporting and correctness. |
| App availability | Availability | A single crash or overload disrupts the simulation. |

### 2.7 Protocols and Interfaces

Because this design is a local Python/Gradio application, the following interfaces apply:

- **User ↔ Browser**: human interaction over browser UI
- **Browser ↔ Gradio server**: HTTP/WebSocket traffic managed by Gradio runtime
- **Gradio UI ↔ Backend**: direct Python function calls, in-process
- **Backend ↔ Price provider**: direct Python function call, in-process
- **Backend ↔ In-memory repository**: direct Python method calls, in-process
- **No file I/O for account data**: no persistence layer in this version

---

## 3. Data Flow Diagram (DFD)

### 3.1 DFD in Mermaid Syntax

```mermaid
flowchart LR
    %% External Entities
    U[User]
    B[Browser]
    P[get_share_price(symbol)]

    %% Trust Boundaries
    subgraph TB1[Trust Boundary TB1: Browser to Gradio UI]
        UI[P1: Gradio UI app.py]
    end

    subgraph TB2[Trust Boundary TB2: UI to Backend Service]
        S[P2: Account Service backend.py]
        R[P3: Reporting Engine backend.py]
    end

    subgraph TB3[Trust Boundary TB3: Backend to Price Provider]
        PR[P4: Price Lookup]
    end

    subgraph TB4[Trust Boundary TB4: Process Memory]
        D1[(D1: In-Memory Account Store)]
        D2[(D2: Transaction Ledger)]
    end

    %% Data Flows
    U -->|Owner name, account_id, amount, symbol, quantity, timestamps| B
    B -->|HTTP/UI events, form inputs| UI
    UI -->|Status messages, tables, snapshot data| B
    B -->|Rendered output| U

    UI -->|Account commands| S
    S -->|Create/read/update account data| D1
    S -->|Append transaction entries| D2
    S -->|Symbol lookup| PR
    PR -->|Current fixed price| S

    R -->|Read transaction history| D2
    R -->|Symbol lookup for valuation| PR
    R -->|Snapshot, holdings, P/L| UI

    S -->|Account state / transactions / errors| UI
    UI -->|Report requests| R
```

### 3.2 DFD Hierarchical View

#### External Entities
- **User**
  - Enters data for account creation, trades, and reports.
- **Browser**
  - Sends UI events and receives rendered results.
- **Price Provider Function**
  - Returns fixed prices for supported symbols.

#### Processes
- **P1 Gradio UI**
  - Accepts user inputs
  - Converts UI actions to backend calls
  - Displays results and safe error messages
- **P2 Account Service**
  - Validates all inputs
  - Enforces sufficient-funds and sufficient-holdings rules
  - Maintains current account state
- **P3 Reporting Engine**
  - Replays transactions for historical balances/holdings
  - Computes portfolio value and P/L
- **P4 Price Lookup**
  - Returns current price for `AAPL`, `TSLA`, `GOOGL`

#### Data Stores
- **D1 In-Memory Account Store**
  - Account metadata
  - Current cash balances
  - Current holdings
  - Transaction lists
- **D2 Transaction Ledger**
  - Append-only transaction records

### 3.3 Primary Data Flows

| Flow ID | Source | Destination | Data |
|---|---|---|---|
| F1 | User | Browser/UI | Owner name, account ID, deposit amount, withdrawal amount, symbol, quantity, timestamps |
| F2 | UI | User | Status messages, account summaries, holdings, transactions, P/L |
| F3 | UI | Account Service | Account commands |
| F4 | Account Service | In-Memory Store | Create/read/update account data |
| F5 | Account Service | Transaction Ledger | Append transaction entries |
| F6 | Account Service | Price Lookup | Symbol |
| F7 | Price Lookup | Account Service | Current price |
| F8 | Reporting Engine | Transaction Ledger | Read transaction history |
| F9 | Reporting Engine | Price Lookup | Symbol for market valuation |
| F10 | Reporting Engine | UI | Snapshot, holdings, P/L, transactions |

---

## 4. Security Posture by Component

### 4.1 Gradio UI (`app.py`)
- Untrusted input enters here.
- Must not rely on front-end controls for security.
- Must catch domain exceptions and avoid exposing tracebacks.
- Must not render user input as HTML.
- Must not use dynamic execution or shell commands.

### 4.2 Account Service (`backend.py`)
- Core enforcement point for all security and correctness rules.
- Must validate values even if UI already did.
- Must reject unsupported symbols, negative amounts, fractional quantities, and overdrafts.
- Must serialize updates to avoid concurrent modification anomalies.

### 4.3 In-Memory Repository
- Holds the current state and ledger.
- Must protect read/write access with locking.
- Must avoid leaking mutable internal structures without coordination.

### 4.4 Price Lookup
- Local deterministic function.
- Must reject unknown symbols instead of defaulting or guessing.
- If price provider fails, the backend must handle it safely.

---

## 5. STRIDE Threat Assessment

### 5.1 Threat Modeling Notes

- Severity is rated relative to this application’s scope.
- “High” indicates a threat that can directly compromise account integrity, correctness, or availability.
- “Medium” indicates meaningful impact but limited scope or mitigations available.
- “Low” indicates less likely or lower impact issues in a local simulation context.

---

## 6. STRIDE Threat Matrix

| Threat ID | STRIDE Category | Target Component/Flow | Threat Description | Severity (Low/Med/High) | Actionable Mitigation Strategy |
|---|---|---|---|---|---|
| T-01 | Spoofing | Account access via `account_id` | An attacker guesses or learns another account’s bearer ID and operates that account as if they were the owner. | High | Treat account IDs as sensitive bearer references; use high-entropy UUIDs; document that no authentication exists; add real authentication/authorization before public exposure. |
| T-02 | Spoofing | Browser/UI identity | The backend cannot verify that the browser user is the intended account owner. | High | Add authentication/session binding in future versions; for now explicitly accept as a known limitation and do not expose publicly. |
| T-03 | Tampering | Deposit/withdrawal inputs | User submits malformed, negative, or extreme numeric values to alter balances incorrectly. | High | Centralize backend validation; require positive finite `Decimal` amounts; enforce upper bounds; reject invalid formats. |
| T-04 | Tampering | Buy/sell quantity inputs | User submits fractional, zero, negative, or oversized quantities to bypass share constraints. | High | Parse quantities as positive integers only; reject floats with fractional parts; cap quantity to safe maximum. |
| T-05 | Tampering | Direct UI endpoint calls | An attacker bypasses the visible UI controls and calls Gradio handlers with crafted parameters. | High | Do not trust frontend validation; validate all data in backend methods only; sanitize every handler input. |
| T-06 | Tampering | Concurrent state updates | Parallel requests may race, causing overdrafts or incorrect holdings if state changes are not atomic. | High | Use `threading.RLock` around repository/service mutation and reads that must be consistent; perform check-and-update atomically. |
| T-07 | Tampering | Historical reconstruction | If transaction records are mutable or reordered, past snapshots can be corrupted. | High | Use immutable transaction objects; append-only ledger; never modify or delete transactions; lock writes. |
| T-08 | Repudiation | Transaction execution | User denies placing a deposit, withdrawal, buy, or sell. | Medium | Record transaction IDs, timestamps, account IDs, transaction type, quantities, prices, and notes; keep append-only ledger. |
| T-09 | Repudiation | Reporting history | User disputes current holdings or P/L and claims the system miscalculated them. | Medium | Reconstruct reports from immutable ledger; keep deterministic replay rules; expose transaction history for review. |
| T-10 | Information Disclosure | Accounts table / listing | A user can enumerate all account IDs and learn other users’ bearer references. | High | For local demo, accept as a limitation; if exposed to multiple users, hide global account listing or require authorization before listing accounts. |
| T-11 | Information Disclosure | Error messages | Raw exceptions or tracebacks leak internal structure, file names, and implementation details. | Medium | Catch expected exceptions in UI; return safe user-facing messages; avoid displaying stack traces or object reprs. |
| T-12 | Information Disclosure | Portfolio and transaction outputs | Sensitive account data may be visible to anyone with access to the app or account ID. | Medium | Limit exposure to authenticated users in future; avoid public deployment; minimize data shown in shared contexts. |
| T-13 | Information Disclosure | In-memory state | Internal object references may be accidentally exposed by returning mutable objects. | Medium | Return copies or read-only derived views where possible; avoid exposing internal mutable collections directly. |
| T-14 | Denial of Service | Oversized text inputs | Extremely long owner names, symbols, timestamps, or notes consume memory and slow validation/rendering. | Medium | Enforce strict length limits on free-text fields; reject overlong inputs early. |
| T-15 | Denial of Service | Extreme numeric inputs | Very large amounts or quantities may cause expensive computations or overflow-like logic issues. | Medium | Define maximum values; validate before arithmetic; use `Decimal` with bounds; reject unrealistic magnitudes. |
| T-16 | Denial of Service | Request flood | Rapid repeated UI requests may overwhelm the single-process app. | Medium | Use Gradio queue with concurrency limit; consider rate limiting and request throttling in future hardening. |
| T-17 | Denial of Service | Price lookup failures | If unsupported or malformed symbol requests are not handled cleanly, repeated errors could degrade service. | Medium | Raise controlled `UnsupportedSymbolError`; handle exceptions gracefully; validate symbols before lookup. |
| T-18 | Denial of Service | Historical report replay | Recomputing long ledgers repeatedly may become expensive as transaction count grows. | Low | Accept for local simulation; optionally cache snapshots or materialized state in future. |
| T-19 | Elevation of Privilege | Account operations | Any user with an account ID can perform all account actions, effectively escalating to full control of that account. | High | This is inherent to bearer-reference design; add authentication, session binding, and authorization in future versions. |
| T-20 | Elevation of Privilege | Backend state mutation | If non-service code can mutate account objects directly, it can bypass validation and create invalid state. | High | Encapsulate mutations in `AccountService`; avoid exposing internal mutable objects to UI or tests except as read-only usage. |
| T-21 | Elevation of Privilege | Direct Python access in-process | Any code executing in the same process could call backend methods directly and bypass UI expectations. | High | Maintain process isolation in deployment; do not run untrusted code in the same interpreter; keep app local-only. |
| T-22 | Tampering | Price provider symbol input | Unknown symbols or malformed strings could be used to manipulate valuation path or trigger unexpected behavior. | Medium | Normalize symbol to uppercase; reject empty/unsupported values; use explicit allowlist of supported tickers. |
| T-23 | Tampering | Currency representation | Use of binary floating point could cause balance drift and incorrect affordability checks. | High | Use `Decimal` end-to-end for monetary values; quantize to 2 decimal places. |
| T-24 | Repudiation | Lack of persistent audit log | Process restart destroys evidence of prior activity, making disputes impossible to verify after restart. | Medium | Document in-memory limitation; add persistent append-only audit log in future if auditability is required. |
| T-25 | Information Disclosure | Historical snapshot outputs | Historical snapshots reveal past portfolio behavior, which may be sensitive if multiple users share the same environment. | Low | Keep the app private/local; add access controls before multi-user deployment. |
| T-26 | Denial of Service | Malformed ISO timestamps | Bad timestamps may trigger repeated parsing exceptions or expensive error handling. | Low | Validate ISO timestamp format and reject invalid values early with controlled errors. |
| T-27 | Spoofing | Transaction attribution | Without user authentication, all transactions are attributed only to account ID, not a verified identity. | High | Accept only in the local demo; implement authenticated identity in future; store owner name only as display metadata, not as security control. |
| T-28 | Tampering | Transaction order manipulation | If timestamps are manipulated or equal timestamps are handled inconsistently, historical replay may differ from expectation. | Medium | Use UTC timezone-aware timestamps; preserve stable ordering by append order and transaction ID; do not allow user-supplied timestamps for transactions. |
| T-29 | Denial of Service | UI rendering of huge tables | Very large transaction history or holdings set may cause slow dataframe rendering in the browser. | Medium | Limit rows shown per request; add pagination or truncation in future; keep data volumes reasonable. |
| T-30 | Information Disclosure | Account IDs in logs/debug output | If IDs are printed to logs, other local users or log viewers may learn bearer references. | Medium | Avoid verbose debug logging in production-like use; sanitize logs; treat account IDs as sensitive. |

---

## 7. Component-by-Component STRIDE Analysis

### 7.1 User → Browser / Gradio UI
- **Spoofing**: A local or remote actor may use the browser to impersonate a legitimate operator simply by knowing the account ID.
- **Tampering**: Browser input can be modified before submission.
- **Repudiation**: User can deny submitting a request without external identity verification.
- **Information Disclosure**: UI may show account IDs and transaction history to anyone who can access the app.
- **Denial of Service**: Repeated submissions can stress the app.
- **Elevation of Privilege**: Bearer ID access effectively grants full account control.

### 7.2 Gradio UI → Account Service
- **Spoofing**: UI cannot vouch for the user’s identity.
- **Tampering**: Frontend validations are bypassable; backend must revalidate.
- **Repudiation**: UI events are not a secure audit trail.
- **Information Disclosure**: UI exceptions may expose internals if not handled carefully.
- **Denial of Service**: Invalid or repeated requests can overwhelm service logic.
- **Elevation of Privilege**: Direct handler invocation must not bypass authorization rules because none exist.

### 7.3 Account Service → In-Memory Store / Ledger
- **Spoofing**: N/A in the traditional sense; identity is account ID.
- **Tampering**: Concurrent writes or direct mutation can corrupt balances/holdings.
- **Repudiation**: Immutable transaction records are needed to attribute actions.
- **Information Disclosure**: Returning internal mutable objects risks leakage of internal state.
- **Denial of Service**: Large state growth can impact memory and speed.
- **Elevation of Privilege**: Unauthorized code paths mutating the store can bypass validation.

### 7.4 Account Service → Price Lookup
- **Spoofing**: Symbol strings may be malformed or crafted to appear legitimate.
- **Tampering**: Symbol normalization and allowlisting are necessary.
- **Repudiation**: Price lookups are deterministic in this design; no external vendor dispute.
- **Information Disclosure**: Minimal, since lookup is local and fixed.
- **Denial of Service**: Repeated invalid symbol lookups can create error churn.
- **Elevation of Privilege**: None inherent, but malformed inputs should never alter lookup behavior.

### 7.5 Reporting Engine → Ledger / Price Lookup
- **Spoofing**: Historical requests can be made on behalf of any known account ID.
- **Tampering**: Ledger corruption would directly affect report correctness.
- **Repudiation**: Historical replay depends on transaction integrity and timestamps.
- **Information Disclosure**: Reports reveal all holdings and transaction details for the chosen account.
- **Denial of Service**: Replaying long ledgers can be costly.
- **Elevation of Privilege**: Not direct, but unauthorized access to another account’s reports is effectively privilege escalation.

---

## 8. Security Assumptions and Explicit Limitations

### 8.1 Explicit Limitations
- No authentication.
- No authorization.
- No persistence.
- No external price service.
- No anti-CSRF or anti-automation protections.
- No production-grade audit trail.
- No historical market price oracle.
- No public deployment hardening by default.

### 8.2 Accepted Risks for Local Simulation
The following risks are accepted in the current version because they are outside the intended scope of a local demo:
- bearer-style account control,
- lack of durable audit logging,
- lack of data persistence,
- lack of user identity verification.

### 8.3 Future Hardening Recommendations
If the application is ever exposed beyond a local trusted environment, the following must be added:
- authentication and authorization,
- session management,
- TLS,
- rate limiting,
- persistent append-only storage,
- real audit logging,
- historical pricing source,
- account recovery and revocation,
- stricter anti-automation controls.

---

## 9. Mitigation Mapping

| Threat Theme | Current Status | Recommended Action |
|---|---|---|
| Bearer account ID misuse | Accepted limitation | Add authentication and authorization before any public deployment. |
| Invalid financial input | Implemented in backend | Keep validation centralized and strict. |
| Concurrent mutation races | Implemented/future critical | Use locking around all account mutations and consistent reads. |
| Transaction repudiation | Partially mitigated | Preserve immutable transaction records and timestamps; add persistent audit logs later. |
| UI error leakage | Implemented in frontend | Catch exceptions and return safe messages only. |
| Data exposure via account listing | Accepted limitation / future hardening | Restrict account enumeration in multi-user settings. |
| Memory-only loss of state | Accepted limitation | Add persistence if durability is needed. |
| DoS from large input or repeated requests | Partially mitigated | Enforce length and magnitude limits; add rate limiting. |
| Incorrect monetary math | Implemented in backend | Use `Decimal` exclusively; never rely on binary floats. |

---

## 10. Security Requirements Summary

The system should:
1. Validate all inputs in the backend.
2. Use `Decimal` for all money calculations.
3. Enforce positive deposits, withdrawals, and whole-number quantities.
4. Reject unsupported symbols explicitly.
5. Prevent overdrafts and overspending.
6. Prevent selling more shares than owned.
7. Record immutable transactions with UTC timestamps.
8. Reconstruct holdings and balances by ledger replay for historical reports.
9. Use locking around repository access for concurrent requests.
10. Hide internal exceptions from end users.
11. Treat account IDs as bearer references and protect them accordingly.
12. Avoid file I/O for account data.
13. Avoid dynamic code execution and unsafe rendering.

---

## 11. Final Statement

This application is a **local trading simulation only**. It is designed for correctness and basic safety in a single-process demo environment, not for real financial use.

The most important security caveat is that **account IDs are bearer references in this version**. Without authentication, anyone who learns an account ID can operate that account. That risk is acceptable only for the current local simulation scope and must be removed before any broader deployment.