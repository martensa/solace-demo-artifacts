# JPA Entity Generator CLI

A self-contained command-line tool that connects to an existing database, analyzes
its schema, and generates production-ready JPA entity classes, Spring Data
repositories, and DAO (Data Access Object) classes. The generated artifacts are
packaged into a JAR that can be used directly by a JPA-based database connector
for reading from or writing to the database.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Building from Source](#building-from-source)
- [Quick Start](#quick-start)
- [Commands Reference](#commands-reference)
  - [test-connection](#test-connection)
  - [list-tables](#list-tables)
  - [describe-table](#describe-table)
  - [generate](#generate)
- [Connector Modes](#connector-modes)
  - [SOURCE Mode](#source-mode)
  - [SINK Mode](#sink-mode)
- [Source Strategies](#source-strategies)
  - [SEQUENTIAL](#sequential)
  - [TIMESTAMP](#timestamp)
  - [READING_INDICATOR](#reading_indicator)
  - [Choosing a Strategy](#choosing-a-strategy)
- [Database Support](#database-support)
  - [PostgreSQL](#postgresql)
  - [MySQL](#mysql)
  - [Oracle](#oracle)
- [Type Mappings](#type-mappings)
- [Generated Artifacts](#generated-artifacts)
  - [Entity Classes](#entity-classes)
  - [Repository Interfaces](#repository-interfaces)
  - [DAO Classes](#dao-classes)
  - [Composite Key Classes](#composite-key-classes)
  - [View Entities](#view-entities)
- [Relationships](#relationships)
- [Output Structure](#output-structure)
- [Usage Examples](#usage-examples)
  - [Interactive Shell Mode](#interactive-shell-mode)
  - [Non-Interactive Mode](#non-interactive-mode)
  - [Selecting Specific Tables](#selecting-specific-tables)
  - [Source with Timestamp Strategy](#source-with-timestamp-strategy)
  - [Sink Generation](#sink-generation)
- [Integrating the Entity JAR](#integrating-the-entity-jar)
- [Project Structure](#project-structure)
- [Technology Stack](#technology-stack)
- [Troubleshooting](#troubleshooting)

## Overview

When building a JPA-based database connector that supports operations such as
**create**, **update**, **upsert**, **delete**, and **select**, a set of JPA
entity classes, Spring Data repositories, and DAOs must be generated for each
target database schema. This CLI tool automates that process entirely.

Source and sink entities are generated **separately** — each run targets a
specific connector mode (SOURCE or SINK), producing artifacts tailored to that
mode's purpose. This matches the connector's architecture where source and sink
entities live in distinct packages.

The tool performs the following steps:

1. Connects to the target database via JDBC.
2. Introspects the schema using JDBC `DatabaseMetaData`.
3. Resolves vendor-specific SQL types to the most appropriate Java types.
4. Detects primary keys, auto-increment columns, and foreign key relationships.
5. Generates annotated JPA entity classes with connector-compatible patterns.
6. Generates Spring Data JPA repository interfaces tailored to the selected
   connector mode and source strategy.
7. Generates DAO classes (SOURCE mode only) that wrap repository calls with
   strategy-specific `findAllByRange` methods.
8. Packages all generated sources into a JAR file.

## Features

- **Three database vendors**: PostgreSQL, MySQL, and Oracle with vendor-specific
  type mappings.
- **Tables and views**: Generates entities for both database tables and views.
  View entities are annotated with `@Immutable`. Views are only included in
  SOURCE mode.
- **Table selection**: Generate for all tables or specify a comma-separated list.
  Same for views.
- **Two connector modes**: SOURCE (read) and SINK (write). Run the tool once for
  each mode to generate separate source and sink entity packages.
- **Three source strategies**: SEQUENTIAL, TIMESTAMP, and READING_INDICATOR.
- **Connector-compatible relationships**: Automatically detects foreign keys and
  generates `@Transient List<Map>` fields for exported relationships, matching
  the connector's programmatic child-data pattern (SOURCE mode only).
- **Composite primary keys**: Generates `@EmbeddedId` with `@Embeddable` classes,
  `@AttributeOverrides`, and correct `equals()` / `hashCode()` implementations,
  matching the connector's expected access pattern.
- **Auto-increment detection**: Applies `@GeneratedValue(strategy = IDENTITY)`
  for auto-increment columns.
- **Entity equals/hashCode**: PK-based `equals()` and `hashCode()` on all
  entities (including views) for correct JPA identity behavior.
- **Generation headers**: Every generated file includes a comment header with
  tool name, source table, and timestamp.
- **Constructor injection**: Generated DAOs use idiomatic Spring constructor
  injection (`private final` + constructor) instead of field injection.
- **Interactive shell**: Spring Shell provides tab completion, command history,
  and inline help.
- **Dry-run mode**: Preview planned output (file list and count) without writing
  any files using `--dry-run`.
- **Clean output**: Remove stale files from previous runs before generating
  using `--clean`.
- **Strategy column validation**: Validates the `--strategy-column` exists in
  the schema and lists available columns on error.
- **JAR packaging**: Optionally packages generated sources into a ready-to-use
  JAR file.

## Prerequisites

| Requirement    | Version                |
| -------------- | ---------------------- |
| Java (JDK)     | 21 or later            |
| Apache Maven   | 3.9 or later           |
| Network access | To the target database |

## Building from Source

Clone or download the project, then build with Maven:

```bash
cd jpa-entity-generator
mvn clean package -DskipTests
```

The executable JAR is created at:

```text
target/jpa-entity-generator-1.0.0.jar
```

## Quick Start

**Step 1** -- Test the database connection:

```bash
java -jar jpa-entity-generator-1.0.0.jar \
  test-connection \
  --vendor POSTGRESQL \
  --url "jdbc:postgresql://localhost:5432/order_management" \
  --username postgres \
  --password postgres
```

Expected output:

```text
Connection successful!
  Product: PostgreSQL 18.1
  Driver: PostgreSQL JDBC Driver 42.7.5
```

**Step 2** -- List available tables and views:

```bash
java -jar jpa-entity-generator-1.0.0.jar \
  list-tables \
  --vendor POSTGRESQL \
  --url "jdbc:postgresql://localhost:5432/order_management" \
  --username postgres \
  --password postgres \
  --schema public
```

**Step 3** -- Generate SOURCE entities (with DAOs and strategy methods):

```bash
java -jar jpa-entity-generator-1.0.0.jar \
  generate \
  --vendor POSTGRESQL \
  --url "jdbc:postgresql://localhost:5432/order_management" \
  --username postgres \
  --password postgres \
  --schema public \
  --package com.solace.connectors.database.source \
  --mode SOURCE \
  --strategy SEQUENTIAL \
  --tables ALL \
  --include-views true \
  --views ALL \
  --output ./generated-source-entities \
  --jar ./generated-source-entities/entity.jar
```

**Step 4** -- Generate SINK entities (minimal repos, no DAOs):

```bash
java -jar jpa-entity-generator-1.0.0.jar \
  generate \
  --vendor POSTGRESQL \
  --url "jdbc:postgresql://localhost:5432/order_management" \
  --username postgres \
  --password postgres \
  --schema public \
  --package com.solace.connectors.database.sink \
  --mode SINK \
  --tables ALL \
  --output ./generated-sink-entities \
  --jar ./generated-sink-entities/entity.jar
```

## Commands Reference

### test-connection

Validates database connectivity and prints product and driver information.

| Parameter    | Required | Description                        |
| ------------ | -------- | ---------------------------------- |
| `--vendor`   | Yes      | `POSTGRESQL`, `MYSQL`, or `ORACLE` |
| `--url`      | Yes      | Full JDBC connection URL           |
| `--username` | Yes      | Database username                  |
| `--password` | Yes      | Database password                  |

### list-tables

Lists all tables and views in the specified schema with column and primary key
counts.

| Parameter    | Required | Description                        |
| ------------ | -------- | ---------------------------------- |
| `--vendor`   | Yes      | `POSTGRESQL`, `MYSQL`, or `ORACLE` |
| `--url`      | Yes      | Full JDBC connection URL           |
| `--username` | Yes      | Database username                  |
| `--password` | Yes      | Database password                  |
| `--schema`   | Yes      | Database schema name               |

### describe-table

Displays detailed metadata for a single table or view, including columns, data
types, nullability, primary keys, and foreign key relationships.

| Parameter    | Required | Description                           |
| ------------ | -------- | ------------------------------------- |
| `--vendor`   | Yes      | `POSTGRESQL`, `MYSQL`, or `ORACLE`    |
| `--url`      | Yes      | Full JDBC connection URL              |
| `--username` | Yes      | Database username                     |
| `--password` | Yes      | Database password                     |
| `--schema`   | Yes      | Database schema name                  |
| `--table`    | Yes      | Name of the table or view to describe |

### generate

Performs schema analysis, code generation, and optional JAR packaging.

<!-- markdownlint-disable MD013 -->

| Parameter           | Required    | Default                | Description                                                 |
| ------------------- | ----------- | ---------------------- | ----------------------------------------------------------- |
| `--vendor`          | Yes         | --                     | `POSTGRESQL`, `MYSQL`, or `ORACLE`.                         |
| `--url`             | Yes         | --                     | Full JDBC connection URL.                                   |
| `--username`        | Yes         | --                     | Database username.                                          |
| `--password`        | Yes         | --                     | Database password.                                          |
| `--schema`          | Yes         | --                     | Schema name (e.g., `public`).                               |
| `--package`         | Yes         | --                     | Base Java package (e.g., `com.solace.connectors.db.sink`).  |
| `--mode`            | Yes         | --                     | `SOURCE` or `SINK`.                                         |
| `--strategy`        | No          | `SEQUENTIAL`           | `SEQUENTIAL`, `TIMESTAMP`, or `READING_INDICATOR`.          |
| `--strategy-column` | Conditional | --                     | Required for `TIMESTAMP` and `READING_INDICATOR`.           |
| `--tables`          | No          | `ALL`                  | Comma-separated table names or `ALL`.                       |
| `--include-views`   | No          | `true`                 | Include database views (SOURCE mode only).                  |
| `--views`           | No          | `ALL`                  | Comma-separated view names or `ALL` (SOURCE mode only).     |
| `--output`          | No          | `./generated-entities` | Output directory.                                           |
| `--jar`             | No          | --                     | Path for the output JAR file.                               |
| `--relationships`   | No          | `true`                 | Generate @Transient relationship fields (SOURCE mode only). |
| `--dry-run`         | No          | `false`                | Preview planned output without writing files.               |
| `--clean`           | No          | `false`                | Delete existing output directory before generating.         |

<!-- markdownlint-enable MD013 -->

## Connector Modes

The connector mode determines which artifacts are generated. Source and sink
entities are generated **separately** by running the tool twice with different
`--mode` and `--package` values. This mirrors the connector architecture where
source and sink entities live in distinct packages (e.g.,
`com.solace.connectors.database.source.entity` and
`com.solace.connectors.database.sink.entity`).

### SOURCE Mode

Generates artifacts for **reading** data from the database:

- **Entity** — JPA entity class with all column mappings.
- **Repository** — Spring Data JPA interface with strategy-specific query methods.
- **DAO** — Data Access Object with `findAllByRange(...)` method that the source
  connector calls to fetch records.

Views are included in SOURCE mode (annotated with `@Immutable`).

**Supported operations**: `select`

**Generated files per table**: `Entity.java`, `EntityRepo.java`, `EntityDAO.java`

### SINK Mode

Generates artifacts for **writing** data to the database:

- **Entity** — JPA entity class with all column mappings.
- **Repository** — Minimal Spring Data JPA interface extending `JpaRepository`.
  All CRUD operations (`save`, `saveAll`, `findById`, `existsById`, `deleteById`,
  `delete`, `findAll`) are inherited from `JpaRepository`.

No DAOs are generated in SINK mode. Views are excluded (they are read-only).

**Supported operations**: `create`, `update`, `upsert`, `delete`

**Generated files per table**: `Entity.java`, `EntityRepo.java`

## Source Strategies

Source strategies control how the connector detects which records to read. They
only apply in SOURCE mode.

### SEQUENTIAL

Reads all records in order using Spring Data pagination. No change detection is
performed. The connector pages through the entire table.

- **Repository**: Uses the built-in `findAll(Pageable)` from `JpaRepository`.
- **DAO**: `findAllByRange(PageRequest, String[])` delegates to paginated
  `findAll`.
- **Use case**: Full table scans, initial loads, or small reference tables.
- **No `--strategy-column` required.**

### TIMESTAMP

Uses a timestamp column to detect records within a time window. The connector
provides a `[from, to)` range and retrieves only the records that fall within
that window.

- **Repository**:
  `findBy<Column>GreaterThanEqualAnd<Column>LessThan`
- **DAO**: `findAllByRange(Sort/Pageable, String[])` where `values[0]` and
  `values[1]` are ISO 8601 formatted strings (e.g., `2024-01-15T10:30:00`)
  parsed according to the strategy column's Java type.
- **Use case**: Tables with a `created_at`, `updated_at`, or `modified_date`
  column.
- **Requires `--strategy-column`** (e.g., `--strategy-column updated_at`).

### READING_INDICATOR

Tracks progress using a numeric indicator column (typically an auto-increment ID
or a sequence number). The connector stores the last processed value and requests
records greater than that value.

- **Repository**: `findBy<Column>GreaterThan(<Type>, Pageable)`
- **DAO**: `findAllByRange(PageRequest, String[])` where `values[0]` is the last
  processed value.
- **Use case**: Tables with a monotonically increasing ID or sequence column.
- **Requires `--strategy-column`** (e.g., `--strategy-column order_id`).

### Choosing a Strategy

| Scenario                            | Recommended       |
| ----------------------------------- | ----------------- |
| Has `updated_at` or `modified_date` | TIMESTAMP         |
| Has an auto-increment primary key   | READING_INDICATOR |
| Process the full table every time   | SEQUENTIAL        |
| No reliable change-tracking column  | SEQUENTIAL        |
| Receives only inserts (no updates)  | READING_INDICATOR |
| Receives inserts and updates        | TIMESTAMP         |

## Database Support

### PostgreSQL

**JDBC URL format**:

```text
jdbc:postgresql://<host>:<port>/<database>
```

**Example**:

```bash
--vendor POSTGRESQL \
--url "jdbc:postgresql://localhost:5432/order_management" \
--schema public
```

**Notes**:

- Schema is case-sensitive. Use `public` for the default schema.
- Supports `SERIAL`, `BIGSERIAL`, `UUID`, `JSONB`, `TIMESTAMP WITH TIME ZONE`,
  and all standard PostgreSQL types.

### MySQL

**JDBC URL format**:

```text
jdbc:mysql://<host>:<port>/<database>
```

**Example**:

```bash
--vendor MYSQL \
--url "jdbc:mysql://localhost:3306/mydb" \
--schema mydb
```

**Notes**:

- In MySQL, the schema name corresponds to the database name.
- `TINYINT(1)` is mapped to `Boolean`.
- Supports `JSON`, `ENUM`, `SET`, and spatial types.

### Oracle

**JDBC URL format**:

```text
jdbc:oracle:thin:@<host>:<port>:<SID>
jdbc:oracle:thin:@//<host>:<port>/<service>
```

**Example**:

```bash
--vendor ORACLE \
--url "jdbc:oracle:thin:@//localhost:1521/XEPDB1" \
--schema MY_SCHEMA
```

**Notes**:

- Schema names are automatically converted to uppercase.
- Oracle `DATE` includes time and is mapped to `LocalDateTime`.
- `NUMBER(1)` is mapped to `Boolean` (common Oracle pattern).
- Supports `TIMESTAMP WITH TIME ZONE`, `CLOB`, `BLOB`, and `XMLTYPE`.

## Type Mappings

The tool uses vendor-specific type mappers that follow best practices for each
database. Below are the most common mappings.

### PostgreSQL Type Mappings

<!-- markdownlint-disable MD060 -->

| SQL Type                        | Java Type      |
| ------------------------------- | -------------- |
| SERIAL, INT4, INTEGER           | Integer        |
| BIGSERIAL, INT8, BIGINT         | Long           |
| SMALLINT, INT2                  | Short          |
| NUMERIC(p,s) where s=0 and p<9 | Integer        |
| NUMERIC(p,s) where s>0         | BigDecimal     |
| FLOAT8, DOUBLE PRECISION        | Double         |
| FLOAT4, REAL                    | Float          |
| BOOLEAN                         | Boolean        |
| VARCHAR, TEXT, CHAR             | String         |
| TIMESTAMP                       | LocalDateTime  |
| TIMESTAMPTZ                     | OffsetDateTime |
| DATE                            | LocalDate      |
| TIME                            | LocalTime      |
| UUID                            | UUID           |
| JSONB, JSON                     | String         |
| BYTEA                           | byte[]         |

### MySQL Type Mappings

| SQL Type                | Java Type      |
| ----------------------- | -------------- |
| INT, INTEGER            | Integer        |
| BIGINT                  | Long           |
| SMALLINT                | Short          |
| TINYINT(1)              | Boolean        |
| DECIMAL(p,s)            | BigDecimal     |
| DOUBLE                  | Double         |
| FLOAT                   | Float          |
| VARCHAR, TEXT, CHAR     | String         |
| DATETIME, TIMESTAMP     | LocalDateTime  |
| DATE                    | LocalDate      |
| TIME                    | LocalTime      |
| JSON                    | String         |
| BLOB, BINARY            | byte[]         |

### Oracle Type Mappings

| SQL Type                    | Java Type      |
| --------------------------- | -------------- |
| NUMBER(1)                   | Boolean        |
| NUMBER(p,0) where p<=9     | Integer        |
| NUMBER(p,0) where p<=18    | Long           |
| NUMBER(p,s) where s>0      | BigDecimal     |
| NUMBER (no precision)       | BigDecimal     |
| VARCHAR2, NVARCHAR2, CHAR   | String         |
| CLOB, NCLOB                | String         |
| DATE                        | LocalDateTime  |
| TIMESTAMP                   | LocalDateTime  |
| TIMESTAMP WITH TIME ZONE    | OffsetDateTime |
| BLOB, RAW                  | byte[]         |

<!-- markdownlint-enable MD060 -->

## Generated Artifacts

The artifacts generated depend on the connector mode.

**SOURCE mode** generates per table/view: Entity + Repo + DAO

**SINK mode** generates per table: Entity + Repo

### Entity Classes

JPA entity classes with full Jakarta Persistence annotations. Entities are
identical in both modes.

```java
@Entity
@Table(name = "orders", schema = "public")
public class Orders implements Serializable {

    private static final long serialVersionUID = 1L;

    private Integer orderId;
    private Integer customerId;
    private LocalDateTime orderDate;
    private String status;
    private BigDecimal subtotal;
    private BigDecimal totalAmount;
    private List<Map> orderItemsList;  // @Transient child data (SOURCE mode)

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "order_id", unique = true)
    public Integer getOrderId() { ... }

    @Column(name = "customer_id", nullable = false)
    public Integer getCustomerId() { ... }

    @Column(name = "subtotal", nullable = false, precision = 10, scale = 2)
    public BigDecimal getSubtotal() { ... }

    @Transient
    public List<Map> getOrderItemsList() { ... }

    @Override
    public boolean equals(Object o) { /* based on orderId */ }

    @Override
    public int hashCode() { return Objects.hash(orderId); }
}
```

### Repository Interfaces

Repository structure differs by mode.

**SOURCE mode** — includes strategy-specific query methods:

```java
// SEQUENTIAL strategy
@Repository
public interface OrdersRepo extends JpaRepository<Orders, Integer> {
    // Uses built-in findAll(Pageable) for sequential reads.
}

// TIMESTAMP strategy
@Repository
public interface OrdersRepo extends JpaRepository<Orders, Integer> {

    List<Orders> findOrdersByUpdatedAtGreaterThanEqualAndUpdatedAtLessThan(
            LocalDateTime from, LocalDateTime to, Sort sort);

    List<Orders> findOrdersByUpdatedAtGreaterThanEqualAndUpdatedAtLessThan(
            LocalDateTime from, LocalDateTime to, Pageable pageable);
}

// READING_INDICATOR strategy
@Repository
public interface OrdersRepo extends JpaRepository<Orders, Integer> {

    List<Orders> findOrdersByOrderIdGreaterThan(
            Integer lastValue, Pageable pageable);
}
```

**SINK mode** — minimal interface, all CRUD inherited from JpaRepository:

```java
@Repository
public interface OrdersRepo extends JpaRepository<Orders, Integer> {
    // All operations inherited: save(), saveAll(), findById(),
    // existsById(), deleteById(), delete(), findAll()
}
```

### DAO Classes

DAOs are generated **only in SOURCE mode**. They provide the `findAllByRange`
contract that the source connector calls to fetch records.

```java
// Sequential
public List<Orders> findAllByRange(PageRequest pageable, String[] values) {
    return repo.findAll(pageable).getContent();
}

// Timestamp
public List<Orders> findAllByRange(Sort sort, String[] values) {
    return repo.findOrdersByUpdatedAtGreaterThanEqualAndUpdatedAtLessThan(
            LocalDateTime.parse(values[0]),
            LocalDateTime.parse(values[1]), sort);
}

// Reading Indicator
public List<Orders> findAllByRange(PageRequest pageable, String[] values) {
    return repo.findOrdersByOrderIdGreaterThan(
            Integer.parseInt(values[0]), pageable);
}
```

### Composite Key Classes

When a table has a composite primary key (multiple columns forming the PK), an
`@EmbeddedId` with a separate `@Embeddable` class is generated automatically.
This matches the connector's expected access pattern where the composite key
is a nested object accessed via `entity.getId()`.

**Entity with `@EmbeddedId`**:

```java
@Entity
@Table(name = "order_items", schema = "public")
public class OrderItems implements Serializable {

    private OrderItemsId id;
    private Integer quantity;
    private BigDecimal unitPrice;

    public OrderItems() {}
    public OrderItems(OrderItemsId id) { this.id = id; }

    @EmbeddedId
    @AttributeOverrides({
        @AttributeOverride(name = "orderId",
            column = @Column(name = "order_id", nullable = false)),
        @AttributeOverride(name = "productId",
            column = @Column(name = "product_id", nullable = false))
    })
    public OrderItemsId getId() { return this.id; }
    public void setId(OrderItemsId id) { this.id = id; }

    @Column(name = "quantity")
    public Integer getQuantity() { ... }
}
```

**`@Embeddable` key class**:

```java
@Embeddable
public class OrderItemsId implements Serializable {

    private Integer orderId;
    private Integer productId;

    @Column(name = "order_id", nullable = false)
    public Integer getOrderId() { ... }

    @Column(name = "product_id", nullable = false)
    public Integer getProductId() { ... }

    @Override
    public boolean equals(Object o) { /* all key fields */ }

    @Override
    public int hashCode() { return Objects.hash(orderId, productId); }
}
```

### View Entities

Database views are generated as read-only entities annotated with
`@Immutable`. Views are only included in SOURCE mode. Since JPA requires every
entity to have an `@Id`, the tool automatically designates a synthetic primary
key — preferring columns ending in `_id`, or falling back to the first column.

```java
@Entity
@Table(name = "order_summary", schema = "public")
@Immutable
public class OrderSummary implements Serializable {

    private Integer orderId;
    private LocalDateTime orderDate;
    private String customerName;
    private BigDecimal totalAmount;
    private Long itemCount;

    @Id
    @Column(name = "order_id")
    public Integer getOrderId() { ... }

    // Other getters, setters, equals(), hashCode()
}
```

## Relationships

The tool automatically detects foreign key constraints and generates
relationship fields that match the connector's expected pattern. Relationship
fields are generated in SOURCE mode when `--relationships true` (default).
In SINK mode, relationships are not generated.

| FK Direction      | Generated Output                           |
| ----------------- | ------------------------------------------ |
| Child has FK      | FK column kept as a regular field          |
| Parent referenced | `@Transient List<Map>` for child data      |

**How it works**:

- Foreign key columns remain as regular entity fields (e.g.,
  `private Integer customerId`). The connector uses these FK values directly.
- For parent entities with child relationships, a `@Transient List<Map>` field
  is added. The connector populates this list programmatically at runtime, not
  via JPA relationship mapping.

```java
// On the parent entity (e.g., Customers)
private List<Map> ordersList;

@Transient
public List<Map> getOrdersList() { return this.ordersList; }
public void setOrdersList(List<Map> ordersList) { ... }
```

**Disabling relationships**:

```bash
generate ... --relationships false
```

When disabled, no `@Transient` child collection fields are generated. Foreign
key columns are still kept as regular fields in all cases.

## Output Structure

**SOURCE mode** output (Entity + Repo + DAO):

```text
generated-source-entities/
  com/solace/connectors/database/source/entity/
    Orders.java
    OrdersRepo.java
    OrdersDAO.java
    Customers.java
    CustomersRepo.java
    CustomersDAO.java
    OrderSummary.java         (view)
    OrderSummaryRepo.java
    OrderSummaryDAO.java
  entity.jar        (if --jar was specified)
```

**SINK mode** output (Entity + Repo only):

```text
generated-sink-entities/
  com/solace/connectors/database/sink/entity/
    Orders.java
    OrdersRepo.java
    Customers.java
    CustomersRepo.java
  entity.jar        (if --jar was specified)
```

## Usage Examples

### Interactive Shell Mode

Start the tool without arguments to enter the interactive shell:

```bash
java -jar jpa-entity-generator-1.0.0.jar
```

The shell provides a prompt where commands can be entered one at a time:

```text
entity-gen> test-connection \
  --vendor POSTGRESQL \
  --url jdbc:postgresql://localhost:5432/mydb \
  --username postgres --password secret
Connection successful!

entity-gen> list-tables \
  --vendor POSTGRESQL \
  --url jdbc:postgresql://localhost:5432/mydb \
  --username postgres --password secret \
  --schema public
Found 6 table(s)...

entity-gen> generate \
  --vendor POSTGRESQL \
  --url jdbc:postgresql://localhost:5432/mydb \
  --username postgres --password secret \
  --schema public --package com.example.source \
  --mode SOURCE --strategy SEQUENTIAL \
  --output ./output --jar ./output/entities.jar
```

Use `help` to list all commands and `help <command>` for detailed usage.

### Non-Interactive Mode

Pass the command and all arguments directly:

```bash
java -jar jpa-entity-generator-1.0.0.jar \
  generate \
  --vendor POSTGRESQL \
  --url "jdbc:postgresql://localhost:5432/order_management" \
  --username postgres \
  --password postgres \
  --schema public \
  --package com.solace.connectors.database.source \
  --mode SOURCE \
  --strategy SEQUENTIAL \
  --output ./generated-source-entities \
  --jar ./generated-source-entities/entity.jar
```

### Selecting Specific Tables

Generate entities for only the `orders` and `customers` tables:

```bash
java -jar jpa-entity-generator-1.0.0.jar \
  generate \
  --vendor POSTGRESQL \
  --url "jdbc:postgresql://localhost:5432/order_management" \
  --username postgres \
  --password postgres \
  --schema public \
  --package com.solace.connectors.database.source \
  --mode SOURCE \
  --tables orders,customers \
  --include-views false \
  --output ./generated-source-entities
```

### Source with Timestamp Strategy

Generate read-only entities using the `updated_at` column for change detection:

```bash
java -jar jpa-entity-generator-1.0.0.jar \
  generate \
  --vendor POSTGRESQL \
  --url "jdbc:postgresql://localhost:5432/order_management" \
  --username postgres \
  --password postgres \
  --schema public \
  --package com.solace.connectors.database.source \
  --mode SOURCE \
  --strategy TIMESTAMP \
  --strategy-column updated_at \
  --output ./generated-source-entities \
  --jar ./generated-source-entities/entity.jar
```

### Sink Generation

Generate write-only entities for a MySQL database:

```bash
java -jar jpa-entity-generator-1.0.0.jar \
  generate \
  --vendor MYSQL \
  --url "jdbc:mysql://localhost:3306/inventory" \
  --username root \
  --password secret \
  --schema inventory \
  --package com.example.connectors.database.sink \
  --mode SINK \
  --output ./generated-sink-entities \
  --jar ./generated-sink-entities/entity.jar
```

## Integrating the Entity JAR

The generated JAR contains Java source files organized by package. To use it in
your connector project:

**Option 1 -- Install to local Maven repository**:

```bash
mvn install:install-file \
  -Dfile=entity.jar \
  -DgroupId=com.solace.connectors.db \
  -DartifactId=entity \
  -Dversion=1.0.0 \
  -Dpackaging=jar
```

Then add to your connector's `pom.xml`:

```xml
<dependency>
    <groupId>com.solace.connectors.db</groupId>
    <artifactId>entity</artifactId>
    <version>1.0.0</version>
</dependency>
```

**Option 2 -- Copy sources into your project**:

```bash
# Extract the JAR
jar xf entity.jar

# Copy the entity package into your project
cp -r com/ /path/to/your-connector/src/main/java/
```

**Option 3 -- Use as a system-scoped dependency**:

```xml
<dependency>
    <groupId>com.solace.connectors.db</groupId>
    <artifactId>entity</artifactId>
    <version>1.0.0</version>
    <scope>system</scope>
    <systemPath>${project.basedir}/lib/entity.jar</systemPath>
</dependency>
```

## Project Structure

```text
jpa-entity-generator/
  pom.xml
  README.md
  src/main/java/com/solace/jpa/entitygen/
    JpaEntityGeneratorApplication.java       Application entry point
    cli/
      GeneratorCommands.java                 Spring Shell command definitions
      CustomPromptProvider.java              Shell prompt customization
    model/
      DatabaseVendor.java                    PostgreSQL, MySQL, Oracle enum
      ConnectorMode.java                     SOURCE, SINK enum
      SourceStrategy.java                    SEQUENTIAL, TIMESTAMP, READING_INDICATOR
      GenerationConfig.java                  All generation parameters
      TableMetadata.java                     Table/view metadata container
      ColumnMetadata.java                    Column metadata container
      RelationshipMetadata.java              Foreign key relationship metadata
    schema/
      SchemaAnalyzer.java                    JDBC metadata introspection
    typemap/
      TypeMapper.java                        Abstract type mapper with factory
      PostgresTypeMapper.java                PostgreSQL SQL-to-Java mapping
      MySqlTypeMapper.java                   MySQL SQL-to-Java mapping
      OracleTypeMapper.java                  Oracle SQL-to-Java mapping
    generator/
      EntityGenerator.java                   JPA entity class generator
      RepositoryGenerator.java               Spring Data repository generator
      DaoGenerator.java                      DAO class generator (SOURCE mode only)
      JarPackager.java                       JAR file packager
  src/main/resources/
    application.yml                          Spring Boot configuration
    banner.txt                               CLI startup banner (disabled by default)
```

## Technology Stack

| Component         | Technology          | Version |
| ----------------- | ------------------- | ------- |
| Framework         | Spring Boot         | 3.4.3   |
| CLI               | Spring Shell        | 3.4.0   |
| Database access   | Spring JDBC         | 6.2.x   |
| Build             | Apache Maven        | 3.9+    |
| Runtime           | Java (JDK)          | 21      |
| PostgreSQL Driver | postgresql          | 42.7.5  |
| MySQL Driver      | mysql-connector-j   | 9.2.0   |
| Oracle Driver     | ojdbc11             | 23.6.0  |

## Troubleshooting

### Connection refused

Verify that the database is running and accessible from the machine where the
CLI is executed. Test with a direct JDBC client or use the `test-connection`
command to validate.

### No tables found

- Confirm the `--schema` value is correct. PostgreSQL uses lowercase schema
  names (e.g., `public`). Oracle uses uppercase (e.g., `MY_SCHEMA`). For MySQL,
  the schema is the database name.
- Verify that the database user has `SELECT` privileges on the
  `information_schema` or equivalent metadata tables.

### Strategy column not found

If the `--strategy-column` does not match any column in the selected tables,
the tool fails early with an error listing all available column names. Verify
the column name matches exactly (case-sensitive for PostgreSQL,
case-insensitive for others). Example error:

```text
ERROR: Strategy column 'nonexistent' not found in any table.
  Available columns: created_at, order_date, order_id, status, updated_at
```

### JAR contains source files instead of compiled classes

This is expected behavior when the required compilation dependencies (Jakarta
Persistence API, Spring Data JPA) are not available in the local Maven
repository. The source JAR is fully functional -- the consuming project compiles
the sources during its own build. To get compiled classes, run
`mvn dependency:resolve` on the generator project first.

### Oracle schema appears empty

Oracle requires the schema name to be in uppercase. The tool converts it
automatically, but ensure the user specified in `--username` has access to the
target schema. If the tables belong to a different schema, use `--schema` to
specify it explicitly.

### MySQL views not detected

Verify that the MySQL user has the `SHOW VIEW` privilege. Without it, the JDBC
driver cannot enumerate views from the `information_schema`.
