package com.solace.jpa.entitygen.typemap;

import com.solace.jpa.entitygen.model.ColumnMetadata;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * MariaDB-specific type mapping.
 * MariaDB is largely MySQL-compatible but has some unique types
 * (e.g., native UUID since 10.7, native JSON alias since 10.2).
 */
public class MariaDbTypeMapper extends TypeMapper {

    private static final Logger log = LoggerFactory.getLogger(MariaDbTypeMapper.class);

    /** Delegate to MySQL mapper for shared types. */
    private final MySqlTypeMapper mysqlDelegate = new MySqlTypeMapper();

    @Override
    public String resolveJavaType(ColumnMetadata column) {
        String typeName = normalize(column.getSqlTypeName());

        return switch (typeName) {
            // MariaDB-native UUID type (10.7+)
            case "UUID" -> "java.util.UUID";

            // MariaDB INET4 / INET6 (10.10+)
            case "INET4", "INET6" -> "java.lang.String";

            default -> {
                // Delegate all standard MySQL-compatible types
                String resolved = mysqlDelegate.resolveJavaType(column);
                yield resolved;
            }
        };
    }
}
