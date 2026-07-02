package com.solace.jpa.entitygen.schema;

import com.solace.jpa.entitygen.model.*;
import com.solace.jpa.entitygen.typemap.TypeMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.sql.*;
import java.util.*;
import java.util.stream.Collectors;

/**
 * Analyzes a database schema via JDBC metadata to extract table/view structures,
 * columns, primary keys, and foreign key relationships.
 */
public class SchemaAnalyzer {

    private static final Logger log = LoggerFactory.getLogger(SchemaAnalyzer.class);

    private final GenerationConfig config;
    private final TypeMapper typeMapper;

    public SchemaAnalyzer(GenerationConfig config) {
        this.config = config;
        this.typeMapper = TypeMapper.forVendor(config.getVendor());
    }

    /** Connection timeout in seconds for database connections. */
    private static final int CONNECTION_TIMEOUT_SECONDS = 15;

    public List<TableMetadata> analyze() throws SQLException {
        List<TableMetadata> result = new ArrayList<>();

        DriverManager.setLoginTimeout(CONNECTION_TIMEOUT_SECONDS);
        try (Connection conn = DriverManager.getConnection(
                config.getJdbcUrl(), config.getUsername(), config.getPassword())) {

            DatabaseMetaData dbMeta = conn.getMetaData();
            String catalog = conn.getCatalog();
            String schema = resolveSchema(dbMeta);

            log.info("Connected to {} ({})", config.getVendor(), conn.getMetaData().getDatabaseProductVersion());
            log.info("Analyzing schema: {}", schema);

            // Collect tables
            List<TableMetadata> tables = extractTablesOrViews(dbMeta, catalog, schema, "TABLE");
            tables = filterByNames(tables, config.getTableNames());
            log.info("Found {} table(s) to process", tables.size());
            result.addAll(tables);

            // Collect views if requested
            if (config.isIncludeViews()) {
                List<TableMetadata> views = extractTablesOrViews(dbMeta, catalog, schema, "VIEW");
                views = filterByNames(views, config.getViewNames());
                log.info("Found {} view(s) to process", views.size());
                result.addAll(views);
            }

            // Enrich each table/view with columns
            for (TableMetadata table : result) {
                extractColumns(dbMeta, catalog, schema, table);
                if (!table.isView()) {
                    extractPrimaryKeys(dbMeta, catalog, schema, table);
                }
            }

            // Extract relationships between tables (not for views)
            if (config.isGenerateRelationships()) {
                extractRelationships(dbMeta, catalog, schema, result);
            }

            log.info("Schema analysis complete: {} objects processed", result.size());
        }
        return result;
    }

    /**
     * Resolve schema name, handling vendor-specific conventions.
     */
    private String resolveSchema(DatabaseMetaData dbMeta) throws SQLException {
        String schema = config.getSchema();
        if (schema == null || schema.isBlank()) {
            log.warn("No schema specified; using connection default");
            return null;
        }
        if (config.getVendor() == DatabaseVendor.ORACLE) {
            // Oracle uses uppercase schema names
            return schema.toUpperCase();
        }
        if (config.getVendor() == DatabaseVendor.MYSQL || config.getVendor() == DatabaseVendor.MARIADB) {
            // MySQL/MariaDB uses catalog, not schema. Return null for schema.
            return null;
        }
        if (config.getVendor() == DatabaseVendor.MSSQL) {
            // SQL Server defaults to "dbo" schema
            return schema != null ? schema : "dbo";
        }
        return schema;
    }

    /**
     * For MySQL, schema maps to catalog.
     */
    private String resolveCatalog(String catalog) {
        if (config.getVendor() == DatabaseVendor.MYSQL || config.getVendor() == DatabaseVendor.MARIADB) {
            return config.getSchema();
        }
        return catalog;
    }

    private List<TableMetadata> extractTablesOrViews(DatabaseMetaData dbMeta, String catalog,
                                                      String schema, String type) throws SQLException {
        List<TableMetadata> result = new ArrayList<>();
        String effectiveCatalog = resolveCatalog(catalog);

        try (ResultSet rs = dbMeta.getTables(effectiveCatalog, schema, "%", new String[]{type})) {
            while (rs.next()) {
                TableMetadata table = new TableMetadata();
                table.setTableName(rs.getString("TABLE_NAME"));
                table.setSchemaName(config.getSchema());
                table.setJavaClassName(toClassName(rs.getString("TABLE_NAME")));
                table.setTableType(type.equals("VIEW") ? TableMetadata.TableType.VIEW : TableMetadata.TableType.TABLE);
                table.setRemarks(rs.getString("REMARKS"));
                result.add(table);
            }
        }
        return result;
    }

    private List<TableMetadata> filterByNames(List<TableMetadata> tables, List<String> requestedNames) {
        if (requestedNames == null || requestedNames.isEmpty()) {
            return tables; // ALL
        }
        Set<String> lowerNames = requestedNames.stream()
                .map(String::toLowerCase)
                .collect(Collectors.toSet());
        return tables.stream()
                .filter(t -> lowerNames.contains(t.getTableName().toLowerCase()))
                .collect(Collectors.toList());
    }

    private void extractColumns(DatabaseMetaData dbMeta, String catalog, String schema,
                                TableMetadata table) throws SQLException {
        String effectiveCatalog = resolveCatalog(catalog);

        try (ResultSet rs = dbMeta.getColumns(effectiveCatalog, schema, table.getTableName(), "%")) {
            while (rs.next()) {
                ColumnMetadata col = new ColumnMetadata();
                col.setColumnName(rs.getString("COLUMN_NAME"));
                col.setJavaFieldName(toFieldName(rs.getString("COLUMN_NAME")));
                col.setSqlType(rs.getInt("DATA_TYPE"));
                col.setSqlTypeName(rs.getString("TYPE_NAME"));
                col.setColumnSize(rs.getInt("COLUMN_SIZE"));
                col.setDecimalDigits(rs.getInt("DECIMAL_DIGITS"));
                col.setNullable("YES".equals(rs.getString("IS_NULLABLE")));
                col.setAutoIncrement("YES".equals(rs.getString("IS_AUTOINCREMENT")));
                col.setDefaultValue(rs.getString("COLUMN_DEF"));
                col.setOrdinalPosition(rs.getInt("ORDINAL_POSITION"));
                col.setRemarks(rs.getString("REMARKS"));

                // Resolve Java type using vendor-specific mapper
                col.setJavaTypeName(typeMapper.resolveJavaType(col));

                table.getColumns().add(col);
            }
        }
    }

    private void extractPrimaryKeys(DatabaseMetaData dbMeta, String catalog, String schema,
                                    TableMetadata table) throws SQLException {
        String effectiveCatalog = resolveCatalog(catalog);
        Set<String> pkColumns = new LinkedHashSet<>();

        try (ResultSet rs = dbMeta.getPrimaryKeys(effectiveCatalog, schema, table.getTableName())) {
            while (rs.next()) {
                pkColumns.add(rs.getString("COLUMN_NAME"));
            }
        }

        for (ColumnMetadata col : table.getColumns()) {
            if (pkColumns.contains(col.getColumnName())) {
                col.setPrimaryKey(true);
                table.getPrimaryKeys().add(col);
            }
        }

        // If no PK found (common with views or some tables), log warning
        if (table.getPrimaryKeys().isEmpty() && !table.isView()) {
            log.warn("No primary key found for table: {}", table.getTableName());
        }
    }

    private void extractRelationships(DatabaseMetaData dbMeta, String catalog, String schema,
                                       List<TableMetadata> tables) throws SQLException {
        String effectiveCatalog = resolveCatalog(catalog);
        Set<String> tableNames = tables.stream()
                .map(TableMetadata::getTableName)
                .collect(Collectors.toSet());

        for (TableMetadata table : tables) {
            if (table.isView()) continue;

            // Imported keys (FKs in this table pointing to other tables)
            // Group by FK_NAME to handle composite foreign keys — only create one
            // RelationshipMetadata per constraint (using the first column)
            Set<String> seenImportedFks = new LinkedHashSet<>();
            try (ResultSet rs = dbMeta.getImportedKeys(effectiveCatalog, schema, table.getTableName())) {
                while (rs.next()) {
                    String pkTable = rs.getString("PKTABLE_NAME");
                    if (!tableNames.contains(pkTable)) continue;

                    String fkName = rs.getString("FK_NAME");
                    if (fkName != null && !seenImportedFks.add(fkName)) {
                        // Additional column of a composite FK — skip (already represented)
                        continue;
                    }

                    RelationshipMetadata rel = new RelationshipMetadata();
                    rel.setConstraintName(fkName);
                    rel.setSourceTable(table.getTableName());
                    rel.setSourceColumn(rs.getString("FKCOLUMN_NAME"));
                    rel.setTargetTable(pkTable);
                    rel.setTargetColumn(rs.getString("PKCOLUMN_NAME"));
                    rel.setRelationType(RelationshipMetadata.RelationType.MANY_TO_ONE);
                    rel.setCascadeDelete(rs.getInt("DELETE_RULE") == DatabaseMetaData.importedKeyCascade);
                    table.getImportedRelationships().add(rel);
                }
            }

            // Exported keys (other tables referencing this table)
            Set<String> seenExportedFks = new LinkedHashSet<>();
            try (ResultSet rs = dbMeta.getExportedKeys(effectiveCatalog, schema, table.getTableName())) {
                while (rs.next()) {
                    String fkTable = rs.getString("FKTABLE_NAME");
                    if (!tableNames.contains(fkTable)) continue;

                    String fkName = rs.getString("FK_NAME");
                    if (fkName != null && !seenExportedFks.add(fkName)) {
                        continue;
                    }

                    RelationshipMetadata rel = new RelationshipMetadata();
                    rel.setConstraintName(fkName);
                    rel.setSourceTable(fkTable);
                    rel.setSourceColumn(rs.getString("FKCOLUMN_NAME"));
                    rel.setTargetTable(table.getTableName());
                    rel.setTargetColumn(rs.getString("PKCOLUMN_NAME"));
                    rel.setRelationType(RelationshipMetadata.RelationType.ONE_TO_MANY);
                    rel.setCascadeDelete(rs.getInt("DELETE_RULE") == DatabaseMetaData.importedKeyCascade);
                    table.getExportedRelationships().add(rel);
                }
            }
        }
    }

    // ========================
    // Naming Utilities
    // ========================

    /** Java reserved keywords that cannot be used as identifiers. */
    private static final Set<String> JAVA_RESERVED = Set.of(
            "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
            "class", "const", "continue", "default", "do", "double", "else", "enum",
            "extends", "final", "finally", "float", "for", "goto", "if", "implements",
            "import", "instanceof", "int", "interface", "long", "native", "new",
            "package", "private", "protected", "public", "return", "short", "static",
            "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
            "transient", "try", "void", "volatile", "while"
    );

    /**
     * Converts snake_case table name to PascalCase Java class name.
     * Example: "order_items" -> "OrderItems"
     */
    public static String toClassName(String tableName) {
        if (tableName == null || tableName.isBlank()) return "UnnamedTable";
        StringBuilder sb = new StringBuilder();
        boolean capitalizeNext = true;
        for (char c : tableName.toCharArray()) {
            if (c == '_' || c == ' ' || c == '-') {
                capitalizeNext = true;
            } else if (capitalizeNext) {
                sb.append(Character.toUpperCase(c));
                capitalizeNext = false;
            } else {
                sb.append(Character.toLowerCase(c));
            }
        }
        String result = sb.toString();
        // Ensure class name starts with a letter
        if (!result.isEmpty() && !Character.isLetter(result.charAt(0))) {
            result = "T" + result;
        }
        return result;
    }

    /**
     * Converts snake_case column name to camelCase Java field name.
     * Escapes Java reserved keywords by appending an underscore suffix.
     * Example: "order_date" -> "orderDate", "class" -> "class_"
     */
    public static String toFieldName(String columnName) {
        if (columnName == null || columnName.isBlank()) return "unnamed";
        String className = toClassName(columnName);
        if (className.isEmpty()) return "unnamed";
        String fieldName = Character.toLowerCase(className.charAt(0)) + className.substring(1);
        if (JAVA_RESERVED.contains(fieldName)) {
            fieldName = fieldName + "_";
        }
        return fieldName;
    }

    /**
     * Converts a camelCase field name to PascalCase (for getter/setter method names).
     */
    public static String capitalize(String fieldName) {
        if (fieldName == null || fieldName.isEmpty()) return fieldName;
        return Character.toUpperCase(fieldName.charAt(0)) + fieldName.substring(1);
    }
}
