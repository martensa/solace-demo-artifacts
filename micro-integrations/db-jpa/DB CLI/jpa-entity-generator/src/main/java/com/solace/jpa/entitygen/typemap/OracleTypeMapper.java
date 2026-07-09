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

            // Date and time -> java.util.Date (connector sets raw JDBC values;
            // java.time.* would throw argument type mismatch). Untested for Oracle;
            // WITH TIME ZONE variants lose the offset under java.util.Date.
            case "DATE" -> "java.util.Date";  // Oracle DATE includes time
            case "TIMESTAMP" -> "java.util.Date";
            case "TIMESTAMP(6)" -> "java.util.Date";
            case "TIMESTAMP WITH TIME ZONE", "TIMESTAMP(6) WITH TIME ZONE" -> "java.util.Date";
            case "TIMESTAMP WITH LOCAL TIME ZONE", "TIMESTAMP(6) WITH LOCAL TIME ZONE" -> "java.util.Date";
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
                    yield "java.util.Date";
                }
                log.warn("Unmapped Oracle type '{}' for column '{}' — defaulting to String",
                        column.getSqlTypeName(), column.getColumnName());
                yield "java.lang.String";
            }
        };
    }

    /**
     * Oracle NUMBER mapping. Oracle JDBC getObject() on NUMBER always returns a
     * BigDecimal, and the connector runtime sets that raw value reflectively, so
     * NUMBER maps unconditionally to BigDecimal (no scale-0 narrowing, no
     * NUMBER(1)->Boolean shortcut) to avoid an argument-type mismatch.
     */
    private String resolveNumberType(ColumnMetadata column) {
        return "java.math.BigDecimal";
    }
}
