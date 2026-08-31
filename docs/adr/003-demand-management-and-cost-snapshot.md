# ADR-003: Demand Management & Cost Price Snapshot

## Status

Accepted

## Context

In a stone processing ERP, raw materials (marble, granite slabs) are expensive and shared across multiple orders. Two key accounting problems must be solved:

1. **Demand vs. Physical Stock**: When an order is created, materials are "needed" but not yet consumed. Physical reservation (locking stock when an order is placed) would cause artificial shortages — an order placed today might not start production for a week.

2. **Cost of Goods Sold (COGS)**: When an order is delivered, its cost must be frozen. If raw material prices change later (new supplier, market price), the COGS of already-delivered orders must NOT change.

## Decision

### 1. Demand Management (Virtual Reservation)

Each `RawMaterial` has a `required_for_orders` field that tracks total demand from active orders:

```python
class RawMaterial(models.Model):
    quantity = models.DecimalField(...)          # physical stock
    required_for_orders = models.DecimalField(...)  # virtual demand
```

- **On order creation/update**: `required_for_orders` is recalculated from all active orders' recipes.
- **Low stock check**: `available = quantity - required_for_orders`. If `available < min_stock`, the card shows a red shortage flag (`is_shortage=True`).
- **No physical lock**: Materials are only consumed when `confirm_work()` is called.
- **Overbooking is allowed**: `required_for_orders` can exceed `quantity` — this surfaces as a shortage warning, not a hard block.

### 2. Cost Price Snapshot

When an order transitions to `DELIVERED` status, the cost price is frozen:

```python
def save(self, *args, **kwargs):
    if self.status == Order.Status.DELIVERED and self.delivered_at is None:
        self.delivered_at = timezone.now()
        self.cost_price = self.product.cost_price  # snapshot
    super().save(*args, **kwargs)
```

- **One-time fix**: `delivered_at` being `None` gates the snapshot — subsequent saves don't overwrite.
- **Isolation**: Later edits to `product.cost_price` (e.g., new supplier price) do NOT affect delivered orders.

### 3. Atomic Material Consumption

`confirm_work()` in `production/services.py` uses `@transaction.atomic` + `select_for_update()`:

```python
@transaction.atomic
def confirm_work(work_record_id, ...):
    work = WorkRecord.objects.select_for_update().get(id=work_record_id)
    for item in work.order.product.recipe.items.all():
        material = RawMaterial.objects.select_for_update().get(id=item.material_id)
        required = item.quantity_per_unit * work.quantity
        if material.quantity < required:
            raise MaterialShortageError(...)
        material.quantity -= required
        material.save()
    # ... create FinishedProduct, calculate labor_cost
```

## Consequences

- **Accurate demand visibility**: Admin dashboard shows real shortage warnings.
- **Correct COGS**: Financial reports reflect true cost at time of delivery.
- **No phantom reservations**: Stock is consumed only when work is confirmed.
- **Atomic safety**: `select_for_update` prevents race conditions during concurrent confirmations (verified in `tests_race_conditions.py`).
