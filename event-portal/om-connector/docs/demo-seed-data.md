# EP Seed Data for the ALDI Workshop Demo

This is the exact content the workshop script (`workshop-demo-script.md`)
assumes lives in your Solace Cloud Event Portal demo account before the
session starts. Stage it via the EP UI, or paste the JSON Schemas below
into the schema editor — they are written to show off the connector's
recursive parser.

Stage time: ~20 minutes by hand. (We can script this against the EP API
in a follow-up if needed.)

## Domains

### `aldi-orders-demo` — the primary demo domain

Description:
> ALDI order processing event domain — created/shipped/cancelled events,
> shared between the order-processor and inventory-service applications.

Owner: set to **your own e-mail** (matches the OM Keycloak user — Act 2
demonstrates the owner resolver).

### `aldi-internal-test` — counter-example for the filter

Description:
> Internal-only test events. Should never appear in OM.

Owner: anything; not relevant.

Contents: one event `SomeInternalEvent v1.0.0` with an empty schema.
The whole point is that it gets filtered out in Act 4.

## Events under `aldi-orders-demo`

All three events use a region variable in the topic address, so the
demo can show that the address reconstruction handles literals AND
variables.

### Event 1 — `OrderCreated`

- Version: `1.0.0`
- State: `Released`
- Topic address levels:
  1. `aldi` (literal)
  2. `orders` (literal)
  3. `region` (variable)
  4. `created` (literal)
- Schema format: `JSON Schema`
- Schema name: `OrderCreatedPayload`
- Schema content:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "OrderCreatedPayload",
  "type": "object",
  "required": ["orderId", "customer", "items"],
  "properties": {
    "orderId": {
      "type": "string",
      "description": "Globally unique order identifier (UUID v4)."
    },
    "createdAt": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp when the order was placed."
    },
    "customer": {
      "$ref": "#/definitions/Customer",
      "description": "Customer who placed the order."
    },
    "items": {
      "type": "array",
      "description": "Line items in the order.",
      "items": { "$ref": "#/definitions/OrderItem" }
    },
    "totalAmount": {
      "type": "number",
      "description": "Total amount in EUR (gross)."
    }
  },
  "definitions": {
    "Customer": {
      "type": "object",
      "required": ["id", "email"],
      "properties": {
        "id":    { "type": "string", "description": "Customer ID." },
        "email": { "type": "string", "description": "Customer e-mail." },
        "address": { "$ref": "#/definitions/Address" }
      }
    },
    "Address": {
      "type": "object",
      "properties": {
        "street":      { "type": "string" },
        "zip":         { "type": "string" },
        "city":        { "type": "string" },
        "countryCode": { "type": "string", "description": "ISO 3166-1 alpha-2." }
      }
    },
    "OrderItem": {
      "type": "object",
      "required": ["sku", "qty"],
      "properties": {
        "sku":   { "type": "string", "description": "Stock keeping unit." },
        "qty":   { "type": "integer", "description": "Quantity ordered." },
        "price": { "type": "number", "description": "Per-unit price in EUR." }
      }
    }
  }
}
```

> This schema exercises `$ref` resolution (Customer → Address) and
> array-of-record children (items → OrderItem). When you click into
> `OrderCreated_v1.0.0` in OM during Act 2, you should be able to drill
> from `customer` → `address` → `zip` — that confirms the recursive
> parser works.

### Event 2 — `OrderShipped`

- Version: `1.0.0`
- State: `Released`
- Topic address levels: `aldi` / `orders` / `{region}` / `shipped`
- Schema format: `JSON Schema`
- Schema name: `OrderShippedPayload`
- Schema content:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "OrderShippedPayload",
  "type": "object",
  "required": ["orderId", "shippedAt", "tracking"],
  "properties": {
    "orderId":   { "type": "string" },
    "shippedAt": { "type": "string", "format": "date-time" },
    "tracking": {
      "type": "object",
      "properties": {
        "carrier":   { "type": "string", "description": "DHL, DPD, Hermes, ..." },
        "trackingId":{ "type": "string" }
      }
    }
  }
}
```

### Event 3 — `OrderCancelled`

- Version: `1.0.0`
- State: `Draft`  (intentionally Draft — shows the lifecycle tag mapping)
- Topic address levels: `aldi` / `orders` / `{region}` / `cancelled`
- Schema format: `JSON Schema`
- Schema name: `OrderCancelledPayload`
- Schema content:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "OrderCancelledPayload",
  "type": "object",
  "required": ["orderId", "reason"],
  "properties": {
    "orderId": { "type": "string" },
    "reason": {
      "type": "string",
      "enum": ["OUT_OF_STOCK", "CUSTOMER_REQUEST", "PAYMENT_FAILED", "FRAUD"],
      "description": "Cancellation reason. Free-text not allowed."
    },
    "cancelledAt": { "type": "string", "format": "date-time" }
  }
}
```

> `state: Draft` is deliberate. In OM the topic shows the
> `EventPortal.Draft` tag, while the other two show `EventPortal.Released`.
> Gives an obvious visual difference in the topic list.

## Applications under `aldi-orders-demo`

### Application 1 — `order-processor`

- Version: `1.0.0`
- State: `Released`
- Description: `Processes OrderCreated events; emits OrderShipped or
  OrderCancelled depending on inventory.`
- Owner: same as the domain.
- Declared **consumed** event versions:
  - `OrderCreated v1.0.0`
- Declared **published** event versions:
  - `OrderShipped v1.0.0`
  - `OrderCancelled v1.0.0`

### Application 2 — `inventory-service`

- Version: `1.0.0`
- State: `Released`
- Description: `Maintains inventory levels reactively from all order events.`
- Owner: same as the domain.
- Declared **consumed** event versions:
  - `OrderCreated v1.0.0`
  - `OrderShipped v1.0.0`
  - `OrderCancelled v1.0.0`
- Declared **published** event versions: *(none)*

## Counter-example under `aldi-internal-test`

### Event — `SomeInternalEvent`

- Version: `1.0.0`
- State: `Released`
- Topic address: `aldi/internal/probe`
- Schema: any minimal `{}` JSON Schema is fine.

This event only exists to be filtered out during Act 4. It must NOT
appear in OM after a workflow run with the default
`domainFilterPattern.excludes: [".*-internal.*", ".*-test$"]`.

## Workflow config that matches this seed data

For Act 2 (Pull) the connection options should look like this — copy
into the OM workflow form:

```yaml
apiUrl: https://api.solace.cloud/api/v2
apiToken: "secret:solace-eventportal-api-token"
mode: rest_api

domainFilterPattern: |
  {"includes": ["^aldi-orders-demo$"], "excludes": [".*-internal.*", ".*-test$"]}
eventFilterPattern: |
  {"includes": [".*"]}
schemaFilterPattern: |
  {"includes": [".*"]}
applicationFilterPattern: |
  {"includes": [".*"]}

includeLineage: "true"
ingestAllVersions: "false"
emitDomains: "true"
# OFF — Solace Cloud EP v2 has no /architecture/modeledEventMeshes
# endpoint (404), so there are no modeled meshes to ingest.
emitDataProducts: "false"
# OFF — EP v2 returns user-ids on createdBy/changedBy, not e-mails,
# and exposes no /users/{id} lookup. Static mapping support is planned.
resolveOwners: "false"

sampleDataEnabled: "false"   # flip to true for optional Act 6
```

## Expected OM state after Act 2

Use this as the visual "passes the demo" checklist:

- **Domain** `aldi-orders-demo` exists. (Owner stays unset for the
  workshop — EP v2 returns user-ids, not e-mails; the connector cannot
  resolve them against OM users without a static mapping.)
- **MessagingService** `solace-event-portal` contains 3 topics:
  - `OrderCreated_v1.0.0` with tag `EventPortal.Released`
  - `OrderShipped_v1.0.0` with tag `EventPortal.Released`
  - `OrderCancelled_v1.0.0` with tag `EventPortal.Draft`
- **PipelineService** `solace-event-portal-apps` contains 2 pipelines:
  - `order-processor_v1.0.0` (tag `EventPortal.Application`)
  - `inventory-service_v1.0.0` (tag `EventPortal.Application`)
- **Lineage** view of `OrderCreated_v1.0.0` shows
  `order-processor` and `inventory-service` as downstream consumers,
  no upstream producers.
- **Lineage** view of `OrderShipped_v1.0.0` shows
  `order-processor` as upstream producer and `inventory-service`
  as downstream consumer.
- Schema-fields view of `OrderCreated_v1.0.0` lets you drill from
  `customer` into `address` into `zip`.
- `aldi-internal-test` does **not** appear anywhere in OM.
