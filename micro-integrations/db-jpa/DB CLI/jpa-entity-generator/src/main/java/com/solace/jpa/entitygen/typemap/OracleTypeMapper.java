package com.solace.jpa.entitygen.typemap;

import com.solace.jpa.entitygen.model.ColumnMetadata;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Oracle-specific type mapping following best practices.
 */
public class OracleTypeMapper extends TypeMapper {

    private static final Logger log = LoggerFactory.getLogger(OracleTypeMapper.class);

    @Override
    public String resolveJavaType(ColumnMetadata column) {
        String typeName = normalize(column.getSqlTypeName());

        return switch (typeName) {
            // Numeric types
            case "NUMBER" -> resolveNumberType(column);
            case "BINARY_FLOAT" -> "java.lang.Float";
            case "BINARY_DOUBLE" -> "java.lang.Double";
            case "FLOAT" -> "java.lang.Double";
            case "INTEGER", "INT", "SMALLINT" -> "java.lang.Integer";

            // Character types
            case "VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR" -> "java.lang.String";
            case "CLOB", "NCLOB", "LONG" -> "java.lang.String";

            // Binary types
            case "RAW", "LONG RAW" -> "byte[]";
            case "BLOB" -> "byte[]";
            case "BFILE" -> "java.lang.String";  // BFILE is an external file pointer, not inline binary

            // Date and time
            case "DATE" -> "java.time.LocalDateTime";  // Oracle DATE includes time
            case "TIMESTAMP" -> "java.time.LocalDateTime";
            case "TIMESTAMP(6)" -> "java.time.LocalDateTime";
            case "TIMESTAMP WITH TIME ZONE", "TIMESTAMP(6) WITH TIME ZONE" -> "java.time.OffsetDateTime";
            case "TIMESTAMP WITH LOCAL TIME ZONE", "TIMESTAMP(6) WITH LOCAL TIME ZONE" -> "java.time.LocalDateTime";
            case "INTERVAL YEAR TO MONTH" -> "java.lang.String";
            case "INTERVAL DAY TO SECOND" -> "java.lang.String";  // No standard JPA converter for Duration

            // Boolean (Oracle 23c)
            case "BOOLEAN" -> "java.lang.Boolean";

            // JSON (Oracle 21c+)
            case "JSON" -> "java.lang.String";

            // XML
            case "XMLTYPE", "SYS.XMLTYPE" -> "java.lang.String";

            // ROWID
            case "ROWID", "UROWID" -> "java.lang.String";

            default -> {
                // Handle TIMESTAMP with varying precision: TIMESTAMP(0) through TIMESTAMP(9)
                if (typeName.startsWith("TIMESTAMP")) {
                    if (typeName.contains("WITH TIME ZONE")) {
                        yield "java.time.OffsetDateTime";
                    }
                    yield "java.time.LocalDateTime";
                }
                log.warn("Unmapped Oracle type '{}' for column '{}' — defaulting to String",
                        column.getSqlTypeName(), column.getColumnName());
                yield "java.lang.String";
            }
        };
    }

    /**
     * Oracle NUMBER(p,s) mapping:
     * - NUMBER without precision -> BigDecimal
     * - NUMBER(1) -> Boolean (common pattern for boolean flags)
     * - NUMBER(p,0) with small precision -> Integer/Long
     * - NUMBER(p,s) with scale -> BigDecimal
     */
    private String resolveNumberType(ColumnMetadata column) {
        int precision = column.getColumnSize();
        int scale = column.getDecimalDigits();

        // NUMBER without precision (precision=0 in metadata means unspecified in Oracle)
        if (precision == 0 && scale == -127) {
            return "java.math.BigDecimal";
        }

        // Common Oracle pattern: NUMBER(1) for booleans
        if (precision == 1 && scale == 0) {
            return "java.lang.Boolean";
        }

        if (scale == 0) {
            if (precision <= 4) return "java.lang.Short";
            if (precision <= 9) return "java.lang.Integer";
            if (precision <= 18) return "java.lang.Long";
            return "java.math.BigInteger";
        }

        return "java.math.BigDecimal";
    }
}
