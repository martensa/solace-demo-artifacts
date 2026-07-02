package com.solace.jpa.entitygen.generator;

import com.solace.jpa.entitygen.model.*;
import com.solace.jpa.entitygen.schema.SchemaAnalyzer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;

/**
 * Generates JPA Entity classes from table/view metadata.
 * Produces properly annotated entity classes with:
 * - Jakarta Persistence annotations
 * - Proper type mappings
 * - @EmbeddedId / @Embeddable composite key classes when needed
 * - @Transient List&lt;Map&gt; for exported relationships (connector pattern)
 * - Serializable implementation
 * - equals/hashCode based on primary key
 */
public class EntityGenerator {

    private static final Logger log = LoggerFactory.getLogger(EntityGenerator.class);

    private final GenerationConfig config;

    /**
     * Holds pre-resolved, collision-free field names for exported relationship fields.
     * Computed once and passed to every method that emits relationship code, ensuring
     * fields and getters/setters always use the same names.
     */
    private record RelationshipFieldNames(
            /** exportedRelationship index → resolved field name (@Transient List) */
            Map<Integer, String> exportedNames
    ) {}

    /**
     * Computes collision-free field names for all relationship fields of a table.
     * This is the single source of truth — every method that needs a relationship
     * field name must use the map returned here.
     */
    private RelationshipFieldNames resolveRelationshipFieldNames(TableMetadata table) {
        Set<String> usedFieldNames = new HashSet<>();
        // Reserve all column field names (FK columns are kept as regular fields)
        for (ColumnMetadata col : table.getColumns()) {
            usedFieldNames.add(col.getJavaFieldName());
        }

        Map<Integer, String> exportedNames = new LinkedHashMap<>();
        for (int i = 0; i < table.getExportedRelationships().size(); i++) {
            RelationshipMetadata rel = table.getExportedRelationships().get(i);
            String fieldName = resolveUniqueFieldName(
                    SchemaAnalyzer.toFieldName(rel.getSourceTable()) + "List", usedFieldNames);
            exportedNames.put(i, fieldName);
        }

        return new RelationshipFieldNames(exportedNames);
    }

    public EntityGenerator(GenerationConfig config) {
        this.config = config;
    }

    /**
     * Generates entity Java source files for all provided tables/views.
     */
    public void generate(List<TableMetadata> tables, Path outputDir) throws IOException {
        String entityPackage = config.getBasePackage() + ".entity";
        Path packageDir = outputDir.resolve(entityPackage.replace('.', '/'));
        Files.createDirectories(packageDir);

        for (TableMetadata table : tables) {
            String source = generateEntitySource(table, entityPackage);
            Path file = packageDir.resolve(table.getJavaClassName() + ".java");
            Files.writeString(file, source);
            log.info("Generated entity: {}", file.getFileName());

            // Generate composite key class if needed
            if (table.hasCompositePrimaryKey()) {
                String keySource = generateCompositeKeySource(table, entityPackage);
                Path keyFile = packageDir.resolve(table.getJavaClassName() + "Id.java");
                Files.writeString(keyFile, keySource);
                log.info("Generated composite key: {}", keyFile.getFileName());
            }
        }
    }

    private String generateEntitySource(TableMetadata table, String entityPackage) {
        StringBuilder sb = new StringBuilder();
        String className = table.getJavaClassName();

        // File header
        sb.append(fileHeader(table.getTableName(), table.getSchemaName()));

        // Package declaration
        sb.append("package ").append(entityPackage).append(";\n\n");

        // Collect imports
        Set<String> imports = collectImports(table);
        imports.stream().sorted().forEach(imp -> sb.append("import ").append(imp).append(";\n"));
        sb.append("\n");

        // Class-level annotations
        sb.append("@Entity\n");
        sb.append("@Table(name = \"").append(table.getTableName()).append("\"");
        if (table.getSchemaName() != null && !table.getSchemaName().isEmpty()) {
            sb.append(", schema = \"").append(table.getSchemaName()).append("\"");
        }
        sb.append(")\n");

        // Immutable view annotation
        if (table.isView()) {
            sb.append("@Immutable\n");
        }

        // Class declaration
        sb.append("public class ").append(className).append(" implements Serializable {\n\n");
        sb.append("    private static final long serialVersionUID = 1L;\n\n");

        // Compute collision-free relationship field names once
        RelationshipFieldNames relNames = config.isGenerateRelationships()
                ? resolveRelationshipFieldNames(table) : null;

        // Fields
        generateFields(sb, table, relNames);

        // Default constructor
        sb.append("    public ").append(className).append("() {\n    }\n\n");

        // All-args constructor
        generateAllArgsConstructor(sb, table, className);

        // Getters and setters with JPA annotations
        generateGettersSetters(sb, table);

        // Relationship getters/setters
        if (config.isGenerateRelationships()) {
            generateRelationshipFields(sb, table, relNames);
        }

        // toString
        generateToString(sb, table, className);

        // equals and hashCode based on primary key fields
        generateEqualsHashCode(sb, table, className);

        sb.append("}\n");
        return sb.toString();
    }

    private Set<String> collectImports(TableMetadata table) {
        Set<String> imports = new TreeSet<>();
        imports.add("jakarta.persistence.*");
        imports.add("java.io.Serializable");
        imports.add("java.util.Objects");

        for (ColumnMetadata col : table.getColumns()) {
            String type = col.getJavaTypeName();
            if (type != null && type.contains(".") && !type.startsWith("java.lang.")) {
                imports.add(type);
            }
        }

        if (table.isView()) {
            imports.add("org.hibernate.annotations.Immutable");
        }

        if (config.isGenerateRelationships()) {
            if (!table.getExportedRelationships().isEmpty()) {
                imports.add("java.util.List");
                imports.add("java.util.Map");
                imports.add("com.fasterxml.jackson.annotation.JsonIgnore");
            }
        }

        return imports;
    }

    private void generateFields(StringBuilder sb, TableMetadata table, RelationshipFieldNames relNames) {
        // Embedded composite key field
        if (table.hasCompositePrimaryKey()) {
            sb.append("    private ").append(table.getJavaClassName()).append("Id id;\n");
        }

        // Column fields
        for (ColumnMetadata col : table.getColumns()) {
            // Skip PK columns for composite key entities (they live in the @Embeddable ID class)
            if (table.hasCompositePrimaryKey() && col.isPrimaryKey()) {
                continue;
            }
            sb.append("    private ").append(simpleType(col.getJavaTypeName()))
              .append(" ").append(col.getJavaFieldName()).append(";\n");
        }

        // @Transient relationship fields for exported relationships (child collections)
        if (config.isGenerateRelationships() && relNames != null) {
            for (int i = 0; i < table.getExportedRelationships().size(); i++) {
                String fieldName = relNames.exportedNames().get(i);
                sb.append("    private List<Map> ").append(fieldName).append(";\n");
            }
        }

        sb.append("\n");
    }

    private void generateAllArgsConstructor(StringBuilder sb, TableMetadata table, String className) {
        if (table.hasCompositePrimaryKey()) {
            // ID-only constructor matching reference connector pattern
            String idType = className + "Id";
            sb.append("    public ").append(className).append("(").append(idType).append(" id) {\n");
            sb.append("        this.id = id;\n");
            sb.append("    }\n\n");

            // All-args: ID + non-PK columns (if any non-PK columns exist)
            List<ColumnMetadata> nonPkCols = table.getColumns().stream()
                    .filter(c -> !c.isPrimaryKey())
                    .toList();
            if (!nonPkCols.isEmpty()) {
                sb.append("    public ").append(className).append("(").append(idType).append(" id, ");
                StringJoiner params = new StringJoiner(", ");
                for (ColumnMetadata col : nonPkCols) {
                    params.add(simpleType(col.getJavaTypeName()) + " " + col.getJavaFieldName());
                }
                sb.append(params).append(") {\n");
                sb.append("        this.id = id;\n");
                for (ColumnMetadata col : nonPkCols) {
                    sb.append("        this.").append(col.getJavaFieldName()).append(" = ")
                      .append(col.getJavaFieldName()).append(";\n");
                }
                sb.append("    }\n\n");
            }
            return;
        }

        List<ColumnMetadata> cols = table.getColumns().stream().toList();

        if (cols.size() <= 1) return;

        sb.append("    public ").append(className).append("(");
        StringJoiner params = new StringJoiner(", ");
        for (ColumnMetadata col : cols) {
            params.add(simpleType(col.getJavaTypeName()) + " " + col.getJavaFieldName());
        }
        sb.append(params).append(") {\n");
        for (ColumnMetadata col : cols) {
            sb.append("        this.").append(col.getJavaFieldName()).append(" = ")
              .append(col.getJavaFieldName()).append(";\n");
        }
        sb.append("    }\n\n");
    }

    private void generateGettersSetters(StringBuilder sb, TableMetadata table) {
        // @EmbeddedId getter/setter for composite key entities
        if (table.hasCompositePrimaryKey()) {
            String idType = table.getJavaClassName() + "Id";
            sb.append("    @EmbeddedId\n");
            sb.append("    @AttributeOverrides({\n");
            List<ColumnMetadata> pks = table.getPrimaryKeys();
            for (int i = 0; i < pks.size(); i++) {
                ColumnMetadata pk = pks.get(i);
                sb.append("        @AttributeOverride(name = \"").append(pk.getJavaFieldName())
                  .append("\", column = @Column(name = \"").append(pk.getColumnName()).append("\"");
                if (!pk.isNullable()) {
                    sb.append(", nullable = false");
                }
                if (isDecimalType(pk) && pk.getColumnSize() > 0) {
                    sb.append(", precision = ").append(pk.getColumnSize());
                    if (pk.getDecimalDigits() > 0) {
                        sb.append(", scale = ").append(pk.getDecimalDigits());
                    }
                }
                if (isStringType(pk) && pk.getColumnSize() > 0 && pk.getColumnSize() < 2147483647) {
                    sb.append(", length = ").append(pk.getColumnSize());
                }
                sb.append("))");
                if (i < pks.size() - 1) sb.append(",");
                sb.append("\n");
            }
            sb.append("    })\n");
            sb.append("    public ").append(idType).append(" getId() {\n");
            sb.append("        return this.id;\n");
            sb.append("    }\n\n");
            sb.append("    public void setId(").append(idType).append(" id) {\n");
            sb.append("        this.id = id;\n");
            sb.append("    }\n\n");
        }

        // For views without explicit PKs, designate a synthetic @Id on the first column
        // JPA requires every @Entity to have at least one @Id field
        String syntheticIdColumn = null;
        if (table.isView() && table.getPrimaryKeys().isEmpty()) {
            syntheticIdColumn = resolveSyntheticIdColumn(table);
        }

        for (ColumnMetadata col : table.getColumns()) {
            // Skip PK columns for composite key entities (accessed via @EmbeddedId)
            if (table.hasCompositePrimaryKey() && col.isPrimaryKey()) {
                continue;
            }

            String fieldName = col.getJavaFieldName();
            String simpleType = simpleType(col.getJavaTypeName());
            String capitalized = SchemaAnalyzer.capitalize(fieldName);

            // JPA annotations on getter
            boolean isSyntheticId = col.getColumnName().equals(syntheticIdColumn);
            if (!table.hasCompositePrimaryKey() && (col.isPrimaryKey() || isSyntheticId)) {
                sb.append("    @Id\n");
                if (col.isAutoIncrement()) {
                    sb.append("    @GeneratedValue(strategy = GenerationType.IDENTITY)\n");
                }
            }

            sb.append("    @Column(name = \"").append(col.getColumnName()).append("\"");
            if (col.isPrimaryKey()) {
                sb.append(", unique = true");
            }
            if (!col.isNullable() && !col.isPrimaryKey()) {
                sb.append(", nullable = false");
            }
            if (isStringType(col) && col.getColumnSize() > 0 && col.getColumnSize() < 2147483647) {
                sb.append(", length = ").append(col.getColumnSize());
            }
            if (isDecimalType(col) && col.getColumnSize() > 0) {
                sb.append(", precision = ").append(col.getColumnSize());
                if (col.getDecimalDigits() > 0) {
                    sb.append(", scale = ").append(col.getDecimalDigits());
                }
            }
            sb.append(")\n");

            // Temporal annotation for date types
            if (col.getJavaTypeName().equals("java.util.Date")) {
                sb.append("    @Temporal(TemporalType.TIMESTAMP)\n");
            }

            // Getter
            sb.append("    public ").append(simpleType).append(" get").append(capitalized).append("() {\n");
            sb.append("        return this.").append(fieldName).append(";\n");
            sb.append("    }\n\n");

            // Setter
            sb.append("    public void set").append(capitalized).append("(")
              .append(simpleType).append(" ").append(fieldName).append(") {\n");
            sb.append("        this.").append(fieldName).append(" = ").append(fieldName).append(";\n");
            sb.append("    }\n\n");
        }
    }

    private void generateRelationshipFields(StringBuilder sb, TableMetadata table,
                                               RelationshipFieldNames relNames) {
        // @Transient getters/setters for exported relationships (child collections).
        // This matches the connector's pattern: child data is populated programmatically,
        // not via JPA relationship mapping, and serialized as List<Map> in JSON.
        for (int i = 0; i < table.getExportedRelationships().size(); i++) {
            String fieldName = relNames.exportedNames().get(i);
            String capitalized = SchemaAnalyzer.capitalize(fieldName);

            sb.append("    @JsonIgnore\n");
            sb.append("    @Transient\n");
            sb.append("    public List<Map> get").append(capitalized).append("() {\n");
            sb.append("        return this.").append(fieldName).append(";\n");
            sb.append("    }\n\n");

            sb.append("    public void set").append(capitalized).append("(List<Map> ")
              .append(fieldName).append(") {\n");
            sb.append("        this.").append(fieldName).append(" = ").append(fieldName).append(";\n");
            sb.append("    }\n\n");
        }
    }

    private void generateToString(StringBuilder sb, TableMetadata table, String className) {
        sb.append("    @Override\n");
        sb.append("    public String toString() {\n");
        sb.append("        return \"").append(className).append("{\" +\n");

        List<String> fieldNames = new ArrayList<>();
        if (table.hasCompositePrimaryKey()) {
            fieldNames.add("id");
        }
        for (ColumnMetadata col : table.getColumns()) {
            if (table.hasCompositePrimaryKey() && col.isPrimaryKey()) continue;
            fieldNames.add(col.getJavaFieldName());
        }

        for (int i = 0; i < fieldNames.size(); i++) {
            String fieldName = fieldNames.get(i);
            if (i == 0) {
                sb.append("                \"").append(fieldName).append("=\" + ").append(fieldName);
            } else {
                sb.append("                \", ").append(fieldName).append("=\" + ").append(fieldName);
            }
            if (i < fieldNames.size() - 1) {
                sb.append(" +\n");
            } else {
                sb.append(" +\n                \"}\";\n");
            }
        }
        sb.append("    }\n\n");
    }

    private void generateEqualsHashCode(StringBuilder sb, TableMetadata table, String className) {
        // Determine the key fields for equals/hashCode
        List<String> keyFields = new ArrayList<>();
        if (table.hasCompositePrimaryKey()) {
            // Use the embedded id field for composite keys
            keyFields.add("id");
        } else if (!table.getPrimaryKeys().isEmpty()) {
            // Use PK fields for single-column PK
            for (ColumnMetadata pk : table.getPrimaryKeys()) {
                keyFields.add(pk.getJavaFieldName());
            }
        } else if (table.isView()) {
            // Use the synthetic @Id column for views
            String syntheticIdCol = resolveSyntheticIdColumn(table);
            if (syntheticIdCol != null) {
                keyFields.add(SchemaAnalyzer.toFieldName(syntheticIdCol));
            }
        }

        if (keyFields.isEmpty()) return;

        // equals
        sb.append("    @Override\n");
        sb.append("    public boolean equals(Object o) {\n");
        sb.append("        if (this == o) return true;\n");
        sb.append("        if (o == null || getClass() != o.getClass()) return false;\n");
        sb.append("        ").append(className).append(" that = (").append(className).append(") o;\n");
        sb.append("        return ");
        StringJoiner equalsJoiner = new StringJoiner(" &&\n                ");
        for (String field : keyFields) {
            equalsJoiner.add("Objects.equals(" + field + ", that." + field + ")");
        }
        sb.append(equalsJoiner).append(";\n");
        sb.append("    }\n\n");

        // hashCode
        sb.append("    @Override\n");
        sb.append("    public int hashCode() {\n");
        sb.append("        return Objects.hash(");
        sb.append(String.join(", ", keyFields));
        sb.append(");\n");
        sb.append("    }\n\n");
    }

    // ========================
    // Composite Key Generator
    // ========================

    private String generateCompositeKeySource(TableMetadata table, String entityPackage) {
        StringBuilder sb = new StringBuilder();
        String className = table.getJavaClassName() + "Id";

        sb.append(fileHeader(table.getTableName(), table.getSchemaName()));
        sb.append("package ").append(entityPackage).append(";\n\n");

        Set<String> imports = new TreeSet<>();
        imports.add("jakarta.persistence.*");
        imports.add("java.io.Serializable");
        imports.add("java.util.Objects");
        for (ColumnMetadata pk : table.getPrimaryKeys()) {
            String type = pk.getJavaTypeName();
            if (type.contains(".") && !type.startsWith("java.lang.")) {
                imports.add(type);
            }
        }
        imports.stream().sorted().forEach(imp -> sb.append("import ").append(imp).append(";\n"));
        sb.append("\n");

        sb.append("/**\n");
        sb.append(" * Composite primary key class for ").append(table.getJavaClassName()).append(".\n");
        sb.append(" */\n");
        sb.append("@Embeddable\n");
        sb.append("public class ").append(className).append(" implements Serializable {\n\n");
        sb.append("    private static final long serialVersionUID = 1L;\n\n");

        // Fields
        for (ColumnMetadata pk : table.getPrimaryKeys()) {
            sb.append("    private ").append(simpleType(pk.getJavaTypeName()))
              .append(" ").append(pk.getJavaFieldName()).append(";\n");
        }
        sb.append("\n");

        // Default constructor
        sb.append("    public ").append(className).append("() {\n    }\n\n");

        // All-args constructor
        sb.append("    public ").append(className).append("(");
        StringJoiner params = new StringJoiner(", ");
        for (ColumnMetadata pk : table.getPrimaryKeys()) {
            params.add(simpleType(pk.getJavaTypeName()) + " " + pk.getJavaFieldName());
        }
        sb.append(params).append(") {\n");
        for (ColumnMetadata pk : table.getPrimaryKeys()) {
            sb.append("        this.").append(pk.getJavaFieldName()).append(" = ")
              .append(pk.getJavaFieldName()).append(";\n");
        }
        sb.append("    }\n\n");

        // Getters and setters with @Column annotations
        for (ColumnMetadata pk : table.getPrimaryKeys()) {
            String fieldName = pk.getJavaFieldName();
            String simpleType = simpleType(pk.getJavaTypeName());
            String cap = SchemaAnalyzer.capitalize(fieldName);

            // @Column annotation on getter (matches connector's @Embeddable pattern)
            sb.append("    @Column(name = \"").append(pk.getColumnName()).append("\"");
            if (!pk.isNullable()) {
                sb.append(", nullable = false");
            }
            if (isDecimalType(pk) && pk.getColumnSize() > 0) {
                sb.append(", precision = ").append(pk.getColumnSize());
                if (pk.getDecimalDigits() > 0) {
                    sb.append(", scale = ").append(pk.getDecimalDigits());
                }
            }
            if (isStringType(pk) && pk.getColumnSize() > 0 && pk.getColumnSize() < 2147483647) {
                sb.append(", length = ").append(pk.getColumnSize());
            }
            sb.append(")\n");

            sb.append("    public ").append(simpleType).append(" get").append(cap).append("() {\n");
            sb.append("        return this.").append(fieldName).append(";\n");
            sb.append("    }\n\n");

            sb.append("    public void set").append(cap).append("(")
              .append(simpleType).append(" ").append(fieldName).append(") {\n");
            sb.append("        this.").append(fieldName).append(" = ").append(fieldName).append(";\n");
            sb.append("    }\n\n");
        }

        // equals
        sb.append("    @Override\n");
        sb.append("    public boolean equals(Object o) {\n");
        sb.append("        if (this == o) return true;\n");
        sb.append("        if (o == null || getClass() != o.getClass()) return false;\n");
        sb.append("        ").append(className).append(" that = (").append(className).append(") o;\n");
        sb.append("        return ");
        StringJoiner equalsJoiner = new StringJoiner(" &&\n                ");
        for (ColumnMetadata pk : table.getPrimaryKeys()) {
            equalsJoiner.add("Objects.equals(" + pk.getJavaFieldName() + ", that." + pk.getJavaFieldName() + ")");
        }
        sb.append(equalsJoiner).append(";\n");
        sb.append("    }\n\n");

        // hashCode
        sb.append("    @Override\n");
        sb.append("    public int hashCode() {\n");
        sb.append("        return Objects.hash(");
        StringJoiner hashJoiner = new StringJoiner(", ");
        for (ColumnMetadata pk : table.getPrimaryKeys()) {
            hashJoiner.add(pk.getJavaFieldName());
        }
        sb.append(hashJoiner).append(");\n");
        sb.append("    }\n");

        sb.append("}\n");
        return sb.toString();
    }

    // ========================
    // Helpers
    // ========================

    /**
     * Resolves the synthetic @Id column name for a view, or null if not applicable.
     * Heuristic: prefer a column ending in "_id", otherwise fall back to the first column.
     * JPA requires every @Entity to have at least one @Id.
     * Exposed so that RepositoryGenerator can determine the correct ID type for views.
     */
    public static String resolveSyntheticIdColumn(TableMetadata table) {
        if (!table.isView() || !table.getPrimaryKeys().isEmpty()) {
            return null;
        }
        for (ColumnMetadata col : table.getColumns()) {
            if (col.getColumnName().toLowerCase().endsWith("_id")) {
                return col.getColumnName();
            }
        }
        if (!table.getColumns().isEmpty()) {
            return table.getColumns().get(0).getColumnName();
        }
        return null;
    }

    /**
     * Ensures a field name is unique by appending "Ref" if it collides with existing names.
     * Tracks the resolved name in the usedFieldNames set.
     */
    private String resolveUniqueFieldName(String desiredName, Set<String> usedFieldNames) {
        String name = desiredName;
        while (usedFieldNames.contains(name)) {
            name = name + "Ref";
        }
        usedFieldNames.add(name);
        return name;
    }

    private boolean isStringType(ColumnMetadata col) {
        String type = col.getJavaTypeName();
        return "java.lang.String".equals(type);
    }

    private boolean isDecimalType(ColumnMetadata col) {
        String type = col.getJavaTypeName();
        return "java.math.BigDecimal".equals(type);
    }

    /**
     * Converts fully-qualified type to simple type name.
     * "java.math.BigDecimal" -> "BigDecimal"
     * "byte[]" stays "byte[]"
     */
    public static String simpleType(String fqn) {
        if (fqn == null) return "Object";
        if (fqn.equals("byte[]")) return "byte[]";
        if (fqn.startsWith("java.lang.")) return fqn.substring("java.lang.".length());
        int lastDot = fqn.lastIndexOf('.');
        return lastDot >= 0 ? fqn.substring(lastDot + 1) : fqn;
    }

    /**
     * Generates a standard file header comment for all generated source files.
     * Includes tool name, timestamp, and source table/view reference.
     */
    public static String fileHeader(String tableName, String schemaName) {
        String timestamp = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss"));
        return "/**\n" +
                " * Auto-generated by JPA Entity Generator CLI\n" +
                " * Source: " + (schemaName != null ? schemaName + "." : "") + tableName + "\n" +
                " * Generated: " + timestamp + "\n" +
                " * DO NOT EDIT — regenerate using the CLI tool.\n" +
                " */\n";
    }
}
