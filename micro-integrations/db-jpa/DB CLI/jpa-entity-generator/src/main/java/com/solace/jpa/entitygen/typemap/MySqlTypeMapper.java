package com.solace.jpa.entitygen.typemap;

import com.solace.jpa.entitygen.model.ColumnMetadata;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * MySQL-specific type mapping following best practices.
 */
public class MySqlTypeMapper extends TypeMapper {

    private static final Logger log = LoggerFactory.getLogger(MySqlTypeMapper.class);

    @Override
    public String resolveJavaType(ColumnMetadata column) {
        String typeName = normalize(column.getSqlTypeName());

        return switch (typeName) {
            // Boolean (MySQL TINYINT(1) is used as boolean)
            case "BIT", "BOOL", "BOOLEAN" -> "java.lang.Boolean";
            case "TINYINT" -> column.getColumnSize() == 1 ? "java.lang.Boolean" : "java.lang.Byte";

            // Integer types
            case "TINYINT UNSIGNED" -> "java.lang.Short";
            case "SMALLINT" -> "java.lang.Short";
            case "SMALLINT UNSIGNED", "MEDIUMINT" -> "java.lang.Integer";
            case "INT", "INTEGER", "MEDIUMINT UNSIGNED" -> "java.lang.Integer";
            case "INT UNSIGNED", "BIGINT" -> "java.lang.Long";
            case "BIGINT UNSIGNED" -> "java.math.BigInteger";

            // Floating point
            case "FLOAT" -> "java.lang.Float";
            case "DOUBLE", "DOUBLE PRECISION" -> "java.lang.Double";

            // Exact numeric -> BigDecimal always (getObject returns BigDecimal;
            // narrowing would mismatch the connector's reflective setter).
            case "DECIMAL", "NUMERIC", "DEC", "FIXED" -> "java.math.BigDecimal";

            // Character types
            case "CHAR", "VARCHAR", "TINYTEXT", "TEXT", "MEDIUMTEXT", "LONGTEXT",
                 "ENUM", "SET" -> "java.lang.String";

            // Binary types
            case "BINARY", "VARBINARY", "TINYBLOB", "BLOB", "MEDIUMBLOB", "LONGBLOB"
                    -> "byte[]";

            // Date and time -> java.util.Date (connector sets raw JDBC values;
            // java.time.* would throw argument type mismatch). Untested for MySQL.
            case "DATE" -> "java.util.Date";
            case "TIME" -> "java.util.Date";
            case "DATETIME" -> "java.util.Date";
            case "TIMESTAMP" -> "java.util.Date";
            case "YEAR" -> "java.lang.Integer";

            // JSON
            case "JSON" -> "java.lang.String";

            // Spatial types - stored as String for JPA compatibility
            case "GEOMETRY", "POINT", "LINESTRING", "POLYGON",
                 "MULTIPOINT", "MULTILINESTRING", "MULTIPOLYGON",
                 "GEOMETRYCOLLECTION" -> "java.lang.String";

            default -> {
                log.warn("Unmapped MySQL type '{}' for column '{}' — defaulting to String",
                        column.getSqlTypeName(), column.getColumnName());
                yield "java.lang.String";
            }
        };
    }
}
