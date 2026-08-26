# SkladPro.Nod — Business Invariants Test Matrix

> **Purpose**: Document all mathematically verified business invariants, formulas, and their test coverage.
> **Status**: Based on independent audit of all backend code (not relying on previous audits).

---

## 1. CLIENT DEBT

### Formula
```
DEBT = Σ(valid order totals) - Σ(valid payments)
```

### Valid Orders
- `is_archived = False`
- `status != 'cancelled'`

### Valid Payments
- Linked to valid orders (`order_id IN valid_order_ids`)
- OR `order = NULL` (advance payments)

### Implementation
- `Client.recalculate_financials()` — uses `SELECT FOR UPDATE` on Client row
- Called on: Payment creation, Order update, Order delivery, Order cancellation, Order client change

### Test Coverage ✅
- `tests.py::ClientRecalculateFinancialsTests::test_recalculate_with_no_orders_resets_to_zero`
- `tests.py::ClientRecalculateFinancialsTests::test_payment_on_cancelled_order_does_not_offset_other_debt`
- `tests_derived_fields.py` — derived field calculations

### Edge Cases Verified
- ✅ Cancelled order payments don't offset other debts
- ✅ Advance payments (order=NULL) count toward client debt reduction
- ✅ Concurrent payment + order update protected by row lock
- ✅ Auto-archive when debt=0 and no active orders

---

## 2. ORDER TOTALS & PAYMENTS

### Formula
```
order.total_amount = quantity × unit_price (set manually by owner)
order.paid_amount = Σ(Payment.amount where order_id = order.id)
order.payment_status = PAID if paid_amount >= total_amount
                      PARTIAL if paid_amount > 0
                      UNPAID if paid_amount = 0
```

### Payment Application
- `Order.apply_payment_amount(amount)` — uses `SELECT FOR UPDATE` on Order row
- Rejects overpayment: `amount > (total_amount - paid_amount)` → 400
- Rejects payment on cancelled order → 400
- Updates `payment_status` atomically

### Test Coverage ✅
- `tests_derived_fields.py` — order totals
- `tests.py::PaymentAtomicityTests::test_overpayment_leaves_no_orphan_payment`
- `tests.py::PaymentAtomicityTests::test_payment_for_cancelled_order_leaves_no_orphan`
- `tests_race.py::PaymentRaceTests::test_concurrent_payments_are_not_lost`

### Edge Cases Verified
- ✅ Concurrent payments serialized by row lock (no lost updates)
- ✅ Overpayment rejected under lock (no race condition)
- ✅ Orphan Payment prevention (atomic Payment creation + apply_payment_amount)
- ✅ Payment on cancelled order rejected

---

## 3. WORKER EARNINGS

### Formula
```
labor_cost = work.quantity × LaborRate.rate_per_unit
```
**Rate Selection**:
- By `work.operation` (worker specifies operation)
- If no operation: only 1 rate exists for product → use it
- If multiple rates and no operation → reject (MissingLaborRateError)

### Worker Earnings (all-time)
```
total_earned = Σ(WorkRecord.labor_cost WHERE status = CONFIRMED)
total_paid = Σ(WorkerPayment.amount)
worker_debt = max(total_earned - total_paid, 0)
```

### Period Worker Payments (reports)
```
worker_payments = Σ(WorkerPayment.amount WHERE payment_date IN period)
```

### Implementation
- `calculate_labor_cost(work)` in `production/services.py`
- `confirm_work()` accrues labor_cost on WorkRecord
- `WorkerPayment` records actual payouts
- `my_earnings` endpoint shows worker's own confirmed works

### Test Coverage ✅
- `tests_labor_rate_k.py::ConfirmRequiresLaborRateTests`
- `tests_labor_rate_k.py::LaborRateOperationTests`
- `tests_labor_rate_k.py::LaborRateOnProductCardTests`
- `tests_finance_math_k.py` — worker_payments in net_profit

### Edge Cases Verified
- ✅ Rate selected by operation (not alphabetical)
- ✅ Multiple rates without operation → error (not guessed)
- ✅ Rejected work: no labor_cost accrued
- ✅ Cancelled order: work confirmation blocked
- ✅ Worker sees only own labor_cost; admin sees none

---

## 4. PRODUCTION → STOCK FLOW

### Recipe Requirements
```
For each RecipeItem: required_qty = quantity_required × work_quantity
consumed_quantity = work.quantity + work.defect_quantity  (defect also consumes material)
```

### confirm_work() Atomic Transaction
1. Lock WorkRecord (status = AWAITING_CONFIRMATION)
2. Lock all RawMaterials (ordered by PK to prevent deadlock)
3. Check material availability (quantity >= required)
4. Calculate labor_cost
5. Deduct material.quantity, reduce reserved_for_orders
6. Create StockMovement(PRODUCTION_OUT) for each material
7. Increment FinishedProduct.quantity
7. Recalculate FinishedProduct.cost_price (weighted avg)
8. Create StockMovement(PRODUCTION_IN)
9. Set WorkRecord.labor_cost, status = CONFIRMED
10. Update Task/Order status

### Defect Handling
- Material consumed: `quantity + defect_quantity`
- Finished product received: `quantity` only (defect not added to stock)
- COGS includes defect cost (materials consumed for defect)

### Test Coverage ✅
- `tests_defect_k.py::DefectConsumptionTests`
- `tests_race.py::WarehouseRaceTests::test_confirm_work_deducts_stock_exactly_once`

### Edge Cases Verified
- ✅ Defect consumes material but doesn't create finished product
- ✅ Shortage check includes defect quantity
- ✅ Double confirmation prevented (AlreadyProcessedError)
- ✅ Cancelled order blocks confirmation (zombie task protection)
- ✅ Material reservation released on confirmation

---

## 5. WEIGHTED AVERAGE COST (WAC)

### RawMaterial.avg_cost_price
```
new_avg = (old_qty × old_avg + new_qty × new_price) / (old_qty + new_qty)
```
- Updated in `record_incoming()` for RawMaterial when price > 0
- `purchase_price` = last incoming price

### FinishedProduct.cost_price
```
batch_cost = (Σ(material.required × material.avg_cost_price) + labor_cost) / work.quantity
new_cost_price = (old_qty × old_cost + work_qty × batch_cost) / (old_qty + work_qty)
```
- Updated in `record_incoming()` (when price > 0) AND `confirm_work()`

### Quantization
- All monetary values: `quantize(Decimal('0.01'))`

### Test Coverage ✅
- `tests_quantity_guard_k.py::test_stock_changes_only_through_operations`
- `tests_quantity_guard_k.py::test_journal_matches_stock_after_operations`
- `tests_labor_rate_k.py` — confirm_work updates cost_price

### Edge Cases Verified
- ✅ Zero starting cost (old_avg = 0)
- ✅ Zero starting quantity
- ✅ Incoming without price (price=0 skips cost update)
- ✅ Production updates cost_price with material + labor
- ✅ Outgoing/loss/adjustment doesn't change avg cost

---

## 6. COGS (COST OF GOODS SOLD)

### Formula
```
COGS = Σ(delivered_order.quantity × delivered_order.cost_price)
```
- `Order.cost_price` = snapshot at FIRST delivery (Order.save() hook)
- `delivered_at` = timestamp of first DELIVERED status transition
- Reports filter by `delivered_at__date` range (not created_at)

### Gross Profit
```
gross_profit = revenue - COGS
```

### Test Coverage ✅
- `tests_finance_math_k.py` — COGS = 30,000 for 3 units @ 10,000
- `tests_cogs_period_k.py` — period boundaries

### Edge Cases Verified
- ✅ COGS fixed at delivery (later cost_price changes don't affect past orders)
- ✅ Custom product (no product) → cost_price = 0
- ✅ Period boundaries: delivered_at inclusive, delivered_at__date range

---

## 7. PROFIT CALCULATIONS

### Net Profit (Period)
```
net_profit = revenue - COGS - (expenses_total - salaries) - worker_payments
```
Where:
- `revenue` = Σ(Payment.amount in period)
- `expenses_total` = Σ(Expense.amount in period)
- `salaries` = Σ(Expense.amount WHERE category IN [SALARY, ADVANCE])
- `worker_payments` = Σ(WorkerPayment.amount in period)

**Logic**: Salary expenses (accrual) excluded; actual WorkerPayment (cash) subtracted.

### Cash Position (All-Time)
```
cash = Σ(all Payments) - Σ(all non-salary Expenses) - Σ(all WorkerPayments)
```
⚠️ **ISSUE**: Cash is all-time, not period-filtered (inconsistent with other metrics)

### Test Coverage ✅
- `tests_finance_math_k.py::test_every_figure_matches_the_scenario`
- `tests_finance_math_k.py::test_net_profit_is_gross_minus_expenses_minus_payouts`
- `tests_finance_math_k.py::test_timeline_profit_equals_card_profit`
- `tests_net_profit_k.py::test_worker_payments_reduce_net_profit`
- `tests_net_profit_k.py::test_net_profit_and_cash_agree_on_worker_payments`

### Edge Cases Verified
- ✅ Timeline profit = Card profit (same formula)
- ✅ Month grouping: DateTime vs DateField normalized
- ✅ Worker payments reduce both net_profit and cash consistently

---

## 8. STOCK INVARIANTS

### Invariants (Application-Level)
```
RawMaterial/FinishedProduct:
  quantity >= 0                    ✅ MinValueValidator(0)
  reserved_for_orders >= 0         ✅ MinValueValidator(0) + max(..., 0)
  reserved_for_orders <= quantity  ❌ NO DB CONSTRAINT (app logic only)
  available_quantity = quantity - reserved_for_orders  ✅ property

is_low_stock = available_quantity <= min_stock
```

### Reservation Flow
- **Reserve**: `reserve_product()`, `reserve_raw_materials()` — SELECT FOR UPDATE + PK order
- **Release**: `release_product()`, `release_raw_materials()` — subtracts consumed qty
- **Delivery**: release reserve → record_outgoing(ignore_reserved=True) → deduct quantity
- **Confirmation**: deduct quantity + release reserve in same transaction

### Test Coverage ✅
- `tests_quantity_guard_k.py` — stock changes only via operations
- `tests_reservation_k.py` — reservation logic
- `tests_race.py` — concurrent reservation/confirmation

### Missing
- ❌ DB CheckConstraint: `reserved_for_orders <= quantity`

---

## 9. SUBSCRIPTION SYSTEM

### Dual System ⚠️ CRITICAL
| Aspect | Company Model | billing.Subscription |
|--------|--------------|---------------------|
| Status | ACTIVE, GRACE, EXPIRED, FROZEN, CANCELLED | ACTIVE, EXPIRED, FROZEN |
| Plan | FK to SubscriptionPlan | CharField (free/pro) |
| Grace Period | ✅ (grace_period_days) | ❌ |
| Celery Tasks | `start_grace`, `expire_company` | `freeze_subscription`, `send_expiry_reminders` |
| API Control | SuperAdmin only | Owner (renew) + SuperAdmin |

### Middleware Check
```python
_is_blocked(company):
  1. company.effective_subscription_status IN [expired, frozen, cancelled]
  2. OR billing.Subscription.is_blocked
```
**Risk**: Drift between two systems → inconsistent access control

### Sync
- `_sync_company_fields(sub)` syncs billing → Company (one-way)
- No reverse sync (Company → billing)

### Test Coverage ✅
- `tests_subscription*.py` — comprehensive lifecycle tests
- `tests_race.py` — subscription renewal race tests (billing)

---

## 10. TRANSACTION ATOMICITY

### Verified Atomic Operations ✅
| Operation | Lock Scope | Rollback Coverage |
|-----------|------------|-------------------|
| `confirm_work()` | WorkRecord + RawMaterials + FinishedProduct | Full (stock + labor + status) |
| `Order.deliver()` | Order + FinishedProduct | Full (stock + status + finance) |
| `Order.cancel()` | Order + FinishedProduct + RawMaterials | Full (stock return + status) |
| `Payment.create()` | Order + Client | Full (Payment + paid_amount + client debt) |
| `Order.update()` | Order + old/new Product + Client | Full (reserves + finance) |
| Subscription ops | Company/Subscription row | Full (status + dates + audit) |

### Lock Ordering (Deadlock Prevention)
- RawMaterials locked by PK order in: `reserve_raw_materials`, `release_raw_materials`, `confirm_work`

---

## 11. CONCURRENCY TESTS ✅

### Covered Race Conditions
| Test | Threads | Verified |
|------|---------|----------|
| AccessKey issue | 16 | Exactly 1 active key |
| AccessKey redeem | 8 | Exactly 1 success |
| WorkRecord confirm | 6 | Stock deducted exactly once |
| Conversation create | 8 | Exactly 1 conversation |
| Payment apply | 16 | paid_amount = 16 (no lost updates) |

**Requirement**: PostgreSQL (SELECT FOR UPDATE not functional on SQLite)

---

## 12. SOFT DELETE / HARD DELETE STATUS

| Model | SoftDeleteModel | API DELETE | Status |
|-------|-----------------|------------|--------|
| Client | ✅ | archive() | ✅ Protected |
| Order | ✅ | cancel() + archive() | ✅ Protected |
| RawMaterial | ✅ | **HARD DELETE** | ❌ BUG |
| FinishedProduct | ✅ | **HARD DELETE** | ❌ BUG |
| Recipe | ❌ | MethodNotAllowed | ✅ Protected |
| RecipeItem | ❌ | MethodNotAllowed | ✅ Protected |
| Expense | ❌ | **HARD DELETE** | ❌ BUG |
| WorkerPayment | ❌ | **HARD DELETE** | ❌ BUG |
| LaborRate | ❌ | **HARD DELETE** | ❌ BUG |
| Payment | ❌ | MethodNotAllowed | ✅ Protected |
| Task | ❌ | MethodNotAllowed | ✅ Protected |
| WorkRecord | ❌ | MethodNotAllowed | ✅ Protected |
| AuditLog | ❌ | No API | ✅ Immutable |
| Subscription | ❌ | No API (admin read-only) | ✅ Protected |
| Invoice | ❌ | No API | ✅ Protected |

---

## 13. MISSING TESTS (Test Matrix Gaps)

### High Priority
- [ ] **Cash period filtering** — cash metric should be period-filtered or clearly labeled all-time
- [ ] **DB CheckConstraint**: `reserved_for_orders <= quantity` on RawMaterial/FinishedProduct
- [ ] **Subscription dual system sync test** — verify Company and billing.Subscription stay in sync
- [ ] **RawMaterial/FinishedProduct destroy** — should call `archive()` not hard delete
- [ ] **Expense/WorkerPayment/LaborRate destroy** — should prohibit or soft delete
- [ ] **WebSocket company isolation** — verify channel layer filters by company
- [ ] **Export permissions** — CSV/PDF exports respect role-based field visibility

### Medium Priority
- [ ] **Worker balance period filtering** — `worker_debts` in analytics uses all-time, not period
- [ ] **Double counting detection** — test: Expense.SALARY + WorkerPayment for same amount
- [ ] **Material loss double counting** — test: production defect + Expense.DEFECT
- [ ] **Concurrent subscription renewal** — Celery freeze vs SuperAdmin extend
- [ ] **Month boundary timezone** — payment_date (DateTime) vs expense date (Date) vs delivered_at

### Low Priority
- [ ] **Large quantity precision** — Decimal(15,3) vs Decimal(15,2) boundaries
- [ ] **Year boundary reports** — period=year across year change
- [ ] **Refund flow** — Payment with negative amount (not supported, use Expense.CLIENT_REFUND)

---

## 14. EDGE CASES TO VERIFY IN TESTS

| Category | Cases |
|----------|-------|
| Zero/Null | 0, 0.001, NULL quantities, NULL prices |
| Boundaries | 1, 999.99, 1000000, very large qty |
| Payments | partial, exact, overpayment (rejected), advance (order=NULL) |
| Orders | cancel, deliver, return, custom product |
| Production | defect=0, defect>0, rejected, cancelled order |
| Subscription | trial, grace, expired, frozen, renew, extend, concurrent |
| Time | same-day, month-end, year-end, timezone boundary |
| Concurrency | duplicate request, retry, parallel operations |

---

## 15. REGRESSION TEST TEMPLATE

```python
# For each financial invariant:
def test_invariant_name(self):
    # BEFORE: Set up known state
    stock_before = material.quantity
    # ... create orders, payments, etc.
    
    # ACTION: Execute business operation
    confirm_work(work, owner)
    
    # EXPECTED: Mathematical calculation
    expected_stock = stock_before - required_qty
    
    # AFTER: Verify database state
    material.refresh_from_db()
    self.assertEqual(material.quantity, expected_stock)
    # Also verify StockMovement created
    # Also verify no double counting in reports
```

---

## 16. CRITICAL FIXES NEEDED

| # | Issue | Severity | Fix |
|---|-------|----------|-----|
| 1 | Dual subscription system drift | 🔴 CRITICAL | Consolidate to single source of truth |
| 2 | Cash metric all-time vs period | 🔴 CRITICAL | Period-filter cash or label clearly |
| 3 | RawMaterial/FinishedProduct hard delete | 🔴 CRITICAL | Override destroy → archive() |
| 4 | Expense/WorkerPayment/LaborRate hard delete | 🔴 CRITICAL | Prohibit DELETE or soft delete |
| 5 | Missing CheckConstraint reserved<=quantity | 🟠 HIGH | Add DB constraint after data validation |
| 6 | Worker debt all-time in period report | 🟠 HIGH | Period-filter worker_paid_total |
| 7 | No GRACE in billing.Subscription | 🟠 HIGH | Add GRACE status or remove from Company |

---

*Generated by independent audit. All formulas mathematically verified against implementation.*