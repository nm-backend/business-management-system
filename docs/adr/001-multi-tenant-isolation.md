# ADR-001: Multi-Tenant Isolation via Company FK

## Status

Accepted

## Context

SkladPro.Nod is a multi-tenant SaaS ERP system where each business (company) must have complete data isolation. Multiple companies share a single PostgreSQL database and Django deployment. Financial data, orders, warehouse, and production records of one company must never leak to another.

## Decision

We use a **shared-database, shared-schema** multi-tenancy approach with a `company` foreign key on every business model:

```python
class Order(models.Model):
    company = models.ForeignKey('companies.Company', on_delete=models.CASCADE)
    # ... business fields
```

Isolation is enforced at **three layers**:

### 1. Queryset Filtering (CompanyScopedViewSet)

All API viewsets inherit from `CompanyScopedViewSet`, which filters the queryset by the requesting user's company:

```python
class CompanyScopedViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        return super().get_queryset().filter(
            company_id=self.request.user.company_id
        )
```

### 2. Serializer-Level Isolation (Dual Serializer Pattern)

Financial fields are included only in owner-specific serializers. Admin/worker serializers physically exclude cost, price, and payment amount fields (see ADR-002).

### 3. Permission Classes

`IsCompanyMember` verifies the user belongs to the company. Role-specific permissions (`IsOwner`, `IsAdmin`) gate access to financial endpoints.

## Consequences

- **Simple**: No separate schemas, no connection routing, no schema switchers.
- **Efficient**: Single database, single connection pool, standard Django ORM.
- **Scalable to ~1000 companies**: Beyond that, schema-per-tenant or Citus may be needed.
- **Risk**: A missing `company_id` filter in any queryset is a data leak — mitigated by comprehensive isolation tests (`tests_money_isolation.py`, `tests_financial_isolation_v2.py`).
- **Migration safety**: All new models MUST include a `company` FK with `db_index=True`.
