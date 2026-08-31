# ADR-002: Dual Serializer Pattern for Financial Data Isolation

## Status

Accepted

## Context

SkladPro.Nod has three roles with different data access levels:

| Role | Access Level |
|------|-------------|
| **Egasi (Owner)** | Full access: all financial fields, analytics, exports |
| **Administrator** | Quantities only: no cost, price, profit, or payment amounts |
| **Ishchi (Worker)** | Personal scope only: own tasks, own earnings |

The system must physically prevent financial data from reaching admin/worker API responses. Hiding fields on the frontend is insufficient — the server must never send them.

## Decision

Each model with financial fields has **two serializer variants**:

### Owner Serializer (full data)

```python
class RawMaterialOwnerSerializer(serializers.ModelSerializer):
    purchase_price = serializers.DecimalField(...)  # included
    avg_cost_price = serializers.DecimalField(...)  # included
    class Meta:
        fields = [..., 'purchase_price', 'avg_cost_price']
```

### Admin/Limited Serializer (no financial fields)

```python
class RawMaterialSerializer(serializers.ModelSerializer):
    # purchase_price, avg_cost_price physically absent from fields
    class Meta:
        fields = [..., 'quantity', 'unit', ...]
```

Views select the serializer dynamically:

```python
def get_serializer_class(self):
    if self.request.user.is_owner:
        return RawMaterialOwnerSerializer
    return RawMaterialSerializer
```

### Affected Modules

| Module | Owner Serializer | Admin Serializer | Fields Hidden |
|--------|-----------------|------------------|---------------|
| Warehouse | `RawMaterialOwnerSerializer` | `RawMaterialSerializer` | `purchase_price`, `avg_cost_price` |
| Warehouse | `FinishedProductOwnerSerializer` | `FinishedProductSerializer` | `cost_price`, `sale_price` |
| Orders | `OrderOwnerSerializer` | `OrderSerializer` | `total_amount`, `paid_amount` |
| Clients | `ClientOwnerSerializer` | `ClientAdminSerializer` | `debt`, `total_paid`; shows `has_debt` bool |
| Production | `WorkRecordSerializer` | `WorkRecordLimitedSerializer` | `labor_rate`, `labor_cost` |
| Finance | All endpoints gated by `FinancialDataPermission` | HTTP 403 | All fields |

## Consequences

- **Zero-trust**: Financial data never enters the HTTP response for non-owner roles.
- **No UI-dependent security**: Frontend hiding is irrelevant — the data is not sent.
- **Testable**: `tests_financial_isolation_v2.py` verifies every field for every role.
- **Trade-off**: ~2x serializer code per model. Acceptable for the security guarantee.
