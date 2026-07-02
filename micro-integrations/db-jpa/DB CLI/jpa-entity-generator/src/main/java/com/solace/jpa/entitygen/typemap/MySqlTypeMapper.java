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

            // Exact numeric
            case "DECIMAL", "NUMERIC", "DEC", "FIXED" -> resolveDecimalType(column);

            // Character types
            case "CHAR", "VARCHAR", "TINYTEXT", "TEXT", "MEDIUMTEXT", "LONGTEXT",
                 "ENUM", "SET" -> "java.lang.String";

            // Binary types
            case "BINARY", "VARBINARY", "TINYBLOB", "BLOB", "MEDIUMBLOB", "LONGBLOB"
                    -> "byte[]";

            // Date and time
            case "DATE" -> "java.time.LocalDate";
            case "TIME" -> "java.time.LocalTime";
            case "DATETIME" -> "java.time.LocalDateTime";
            case "TIMESTAMP" -> "java.time.LocalDateTime";
            case "YEAR" -> "java.lang.Short";

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

    private String resolveDecimalType(ColumnMetadata column) {
        int precision = column.getColumnSize();
        int scale = column.getDecimalDigits();

        if (scale == 0 && precision > 0) {
            if (precision <= 4) return "java.lang.Short";
            if (precision <= 9) return "java.lang.Integer";
            if (precision <= 18) return "java.lang.Long";
        }
        return "java.math.BigDecimal";
    }
}
