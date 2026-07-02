package com.solace.jpa.entitygen.typemap;

import com.solace.jpa.entitygen.model.ColumnMetadata;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Microsoft SQL Server type mapping.
 * Maps T-SQL data types to Java types following JPA best practices.
 */
public class MsSqlTypeMapper extends TypeMapper {

    private static final Logger log = LoggerFactory.getLogger(MsSqlTypeMapper.class);

    @Override
    public String resolveJavaType(ColumnMetadata column) {
        String typeName = normalize(column.getSqlTypeName());

        return switch (typeName) {
            // Boolean
            case "BIT" -> "java.lang.Boolean";

            // Integer types
            case "TINYINT" -> "java.lang.Short";
            case "SMALLINT" -> "java.lang.Short";
            case "INT", "INTEGER" -> "java.lang.Integer";
            case "BIGINT" -> "java.lang.Long";

            // Floating point
            case "REAL" -> "java.lang.Float";
            case "FLOAT" -> "java.lang.Double";

            // Exact numeric
            case "DECIMAL", "NUMERIC", "MONEY", "SMALLMONEY" -> resolveDecimalType(column);

            // Character types
            case "CHAR", "VARCHAR", "TEXT", "NCHAR", "NVARCHAR", "NTEXT" -> "java.lang.String";

            // Binary types
            case "BINARY", "VARBINARY", "IMAGE" -> "byte[]";

            // Date and time
            case "DATE" -> "java.time.LocalDate";
            case "TIME" -> "java.time.LocalTime";
            case "DATETIME", "DATETIME2", "SMALLDATETIME" -> "java.time.LocalDateTime";
            case "DATETIMEOFFSET" -> "java.time.OffsetDateTime";

            // Unique identifier
            case "UNIQUEIDENTIFIER" -> "java.util.UUID";

            // XML
            case "XML" -> "java.lang.String";

            // SQL Variant / hierarchyid / geography / geometry
            case "SQL_VARIANT", "HIERARCHYID", "GEOGRAPHY", "GEOMETRY" -> "java.lang.String";

            // Timestamp / rowversion (auto-generated binary)
            case "TIMESTAMP", "ROWVERSION" -> "byte[]";

            default -> {
                log.warn("Unmapped MSSQL type '{}' for column '{}' — defaulting to String",
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
