package com.solace.jpa.entitygen.typemap;

import com.solace.jpa.entitygen.model.ColumnMetadata;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * PostgreSQL-specific type mapping following best practices.
 * Maps PostgreSQL native types (including aliases) to appropriate Java types.
 */
public class PostgresTypeMapper extends TypeMapper {

    private static final Logger log = LoggerFactory.getLogger(PostgresTypeMapper.class);

    @Override
    public String resolveJavaType(ColumnMetadata column) {
        String typeName = normalize(column.getSqlTypeName());

        return switch (typeName) {
            // Boolean
            case "BOOL", "BOOLEAN" -> "java.lang.Boolean";

            // Integer types. NOTE: the connector runtime (JpaBeanUtil) sets raw
            // JDBC getObject() values on the entity, and pgjdbc getObject returns
            // Integer for smallint -- so map INT2/SMALLINT to Integer, not Short.
            case "INT2", "SMALLINT", "SMALLSERIAL" -> "java.lang.Integer";
            case "INT4", "INTEGER", "INT", "SERIAL" -> "java.lang.Integer";
            case "INT8", "BIGINT", "BIGSERIAL" -> "java.lang.Long";

            // Floating point
            case "FLOAT4", "REAL" -> "java.lang.Float";
            case "FLOAT8", "DOUBLE PRECISION" -> "java.lang.Double";

            // Exact numeric. getObject always returns BigDecimal for numeric/decimal,
            // so map unconditionally to BigDecimal (no scale-0 narrowing) to match
            // what the connector's reflective setter receives at runtime.
            case "NUMERIC", "DECIMAL" -> "java.math.BigDecimal";

            // Character types
            case "VARCHAR", "CHARACTER VARYING", "TEXT", "CHAR", "CHARACTER",
                 "BPCHAR", "NAME", "CITEXT" -> "java.lang.String";

            // Date and time. The connector sets raw JDBC getObject() values, which
            // for temporal columns are java.sql.Date/Time/Timestamp (all subclasses
            // of java.util.Date) -- NOT java.time.* -- so map every temporal type to
            // java.util.Date (EntityGenerator adds @Temporal(TIMESTAMP)). Mapping to
            // java.time.LocalDateTime here would throw "argument type mismatch".
            case "DATE" -> "java.util.Date";
            case "TIME", "TIMETZ", "TIME WITH TIME ZONE", "TIME WITHOUT TIME ZONE"
                    -> "java.util.Date";
            case "TIMESTAMP", "TIMESTAMP WITHOUT TIME ZONE" -> "java.util.Date";
            // timestamptz: java.util.Date carries no zone offset (acceptable for the
            // connector's epoch-millis contract).
            case "TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE" -> "java.util.Date";
            case "INTERVAL" -> "java.lang.String";  // PostgreSQL INTERVAL has no standard JPA converter

            // Binary
            case "BYTEA" -> "byte[]";

            // UUID
            case "UUID" -> "java.util.UUID";

            // JSON
            case "JSON", "JSONB" -> "java.lang.String";

            // XML
            case "XML" -> "java.lang.String";

            // Arrays - represented as String for JPA compatibility
            case "_INT4", "_INT8", "_TEXT", "_VARCHAR", "_FLOAT8", "_BOOL"
                    -> "java.lang.String";

            // Network types
            case "INET", "CIDR", "MACADDR", "MACADDR8" -> "java.lang.String";

            // Geometric types
            case "POINT", "LINE", "LSEG", "BOX", "PATH", "POLYGON", "CIRCLE"
                    -> "java.lang.String";

            // Monetary
            case "MONEY" -> "java.math.BigDecimal";

            // Bit strings
            case "BIT", "VARBIT", "BIT VARYING" -> "java.lang.String";

            // OID / Large Objects
            case "OID" -> "java.lang.Long";

            default -> {
                log.warn("Unmapped PostgreSQL type '{}' for column '{}' — defaulting to String",
                        column.getSqlTypeName(), column.getColumnName());
                yield "java.lang.String";
            }
        };
    }
}
