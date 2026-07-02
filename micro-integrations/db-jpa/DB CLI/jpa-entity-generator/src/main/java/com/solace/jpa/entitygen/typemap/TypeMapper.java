package com.solace.jpa.entitygen.typemap;

import com.solace.jpa.entitygen.model.ColumnMetadata;
import com.solace.jpa.entitygen.model.DatabaseVendor;

/**
 * Maps database SQL types to Java types following vendor-specific best practices.
 * Factory method selects the correct mapper based on the database vendor.
 */
public abstract class TypeMapper {

    /**
     * Factory method to create the vendor-specific type mapper.
     */
    public static TypeMapper forVendor(DatabaseVendor vendor) {
        return switch (vendor) {
            case POSTGRESQL -> new PostgresTypeMapper();
            case MYSQL -> new MySqlTypeMapper();
            case MARIADB -> new MariaDbTypeMapper();
            case ORACLE -> new OracleTypeMapper();
            case MSSQL -> new MsSqlTypeMapper();
        };
    }

    /**
     * Resolves the fully-qualified Java type for a given column.
     * Implementations should consider sqlType, sqlTypeName, columnSize, decimalDigits, and nullable.
     */
    public abstract String resolveJavaType(ColumnMetadata column);

    /**
     * Helper to convert SQL type name to upper case for consistent matching.
     */
    protected String normalize(String sqlTypeName) {
        return sqlTypeName == null ? "" : sqlTypeName.toUpperCase().trim();
    }
}
