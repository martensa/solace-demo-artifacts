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

            // Exact numeric -> BigDecimal always (getObject returns BigDecimal;
            // narrowing would mismatch the connector's reflective setter).
            case "DECIMAL", "NUMERIC", "MONEY", "SMALLMONEY" -> "java.math.BigDecimal";

            // Character types
            case "CHAR", "VARCHAR", "TEXT", "NCHAR", "NVARCHAR", "NTEXT" -> "java.lang.String";

            // Binary types
            case "BINARY", "VARBINARY", "IMAGE" -> "byte[]";

            // Date and time -> java.util.Date (connector sets raw JDBC values;
            // java.time.* would throw argument type mismatch). Untested for MSSQL.
            case "DATE" -> "java.util.Date";
            case "TIME" -> "java.util.Date";
            case "DATETIME", "DATETIME2", "SMALLDATETIME" -> "java.util.Date";
            case "DATETIMEOFFSET" -> "java.util.Date";

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
}
