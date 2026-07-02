package com.solace.jpa.entitygen.generator;

import com.solace.jpa.entitygen.model.*;
import com.solace.jpa.entitygen.schema.SchemaAnalyzer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

/**
 * Generates Spring Data JPA Repository interfaces for each entity.
 *
 * <ul>
 *   <li><b>SOURCE</b> — Includes strategy-specific query methods (READING_INDICATOR, TIMESTAMP, SEQUENTIAL).</li>
 *   <li><b>SINK</b> — Minimal repository, only extends JpaRepository with no custom methods.
 *       All CRUD operations are inherited from JpaRepository.</li>
 * </ul>
 */
public class RepositoryGenerator {

    private static final Logger log = LoggerFactory.getLogger(RepositoryGenerator.class);

    private final GenerationConfig config;

    public RepositoryGenerator(GenerationConfig config) {
        this.config = config;
    }

    public void generate(List<TableMetadata> tables, Path outputDir) throws IOException {
        String entityPackage = config.getBasePackage() + ".entity";
        Path packageDir = outputDir.resolve(entityPackage.replace('.', '/'));
        Files.createDirectories(packageDir);

        for (TableMetadata table : tables) {
            String source = generateRepoSource(table, entityPackage);
            Path file = packageDir.resolve(table.getJavaClassName() + "Repo.java");
            Files.writeString(file, source);
            log.info("Generated repository: {}", file.getFileName());
        }
    }

    private String generateRepoSource(TableMetadata table, String entityPackage) {
        StringBuilder sb = new StringBuilder();
        String className = table.getJavaClassName();
        String repoName = className + "Repo";
        String idType = resolveIdType(table);

        // File header
        sb.append(EntityGenerator.fileHeader(table.getTableName(), table.getSchemaName()));

        // Package
        sb.append("package ").append(entityPackage).append(";\n\n");

        // Imports
        Set<String> imports = new TreeSet<>();
        imports.add("org.springframework.data.jpa.repository.JpaRepository");
        imports.add("org.springframework.stereotype.Repository");

        if (config.isSourceMode()) {
            imports.add("org.springframework.data.domain.Pageable");
            imports.add("org.springframework.data.domain.Sort");
            imports.add("java.util.List");
            addStrategyImports(imports, table);
        }

        addIdTypeImport(imports, idType);

        imports.stream().sorted().forEach(imp -> sb.append("import ").append(imp).append(";\n"));
        sb.append("\n");

        // Interface
        sb.append("@Repository\n");
        sb.append("public interface ").append(repoName)
          .append(" extends JpaRepository<").append(className).append(", ").append(simpleIdType(idType)).append("> {\n");

        // SOURCE mode: add strategy-specific query methods
        if (config.isSourceMode()) {
            generateSourceMethods(sb, table, className);
        }

        // SINK mode: no custom methods — uses inherited JpaRepository methods:
        // save(), saveAll(), findById(), existsById(), deleteById(), delete(), findAll()

        sb.append("}\n");
        return sb.toString();
    }

    private void generateSourceMethods(StringBuilder sb, TableMetadata table, String className) {
        SourceStrategy strategy = config.getSourceStrategy();
        if (strategy == null) strategy = SourceStrategy.SEQUENTIAL;

        String strategyCol = config.getStrategyColumn();

        switch (strategy) {
            case READING_INDICATOR -> {
                if (strategyCol != null && !strategyCol.isEmpty()) {
                    String colField = SchemaAnalyzer.capitalize(SchemaAnalyzer.toFieldName(strategyCol));
                    // For @EmbeddedId, PK columns are accessed via id.field path
                    if (table.hasCompositePrimaryKey() && isPrimaryKeyColumn(table, strategyCol)) {
                        colField = "Id" + colField;
                    }
                    String colType = resolveStrategyColumnType(table, strategyCol);

                    sb.append("\n    /**\n");
                    sb.append("     * Reading Indicator strategy: fetch records where ").append(strategyCol)
                      .append(" > lastValue.\n");
                    sb.append("     */\n");
                    sb.append("    List<").append(className).append("> find").append(className)
                      .append("By").append(colField).append("GreaterThan(")
                      .append(colType).append(" lastValue, Pageable pageable);\n");
                }
            }
            case TIMESTAMP -> {
                if (strategyCol != null && !strategyCol.isEmpty()) {
                    String colField = SchemaAnalyzer.capitalize(SchemaAnalyzer.toFieldName(strategyCol));
                    // For @EmbeddedId, PK columns are accessed via id.field path
                    if (table.hasCompositePrimaryKey() && isPrimaryKeyColumn(table, strategyCol)) {
                        colField = "Id" + colField;
                    }
                    // Connector runtime always uses java.util.Date for timestamp strategy
                    String simpleColType = "Date";

                    sb.append("\n    /**\n");
                    sb.append("     * Timestamp strategy: fetch records where ").append(strategyCol)
                      .append(" is within a time window.\n");
                    sb.append("     */\n");
                    sb.append("    List<").append(className).append("> find").append(className)
                      .append("By").append(colField).append("GreaterThanEqualAnd")
                      .append(colField).append("LessThan(").append(simpleColType).append(" from, ")
                      .append(simpleColType).append(" to, Sort sort);\n\n");

                    sb.append("    List<").append(className).append("> find").append(className)
                      .append("By").append(colField).append("GreaterThanEqualAnd")
                      .append(colField).append("LessThan(").append(simpleColType).append(" from, ")
                      .append(simpleColType).append(" to, Pageable pageable);\n");
                }
            }
            case SEQUENTIAL -> {
                if (strategyCol != null && !strategyCol.isEmpty()) {
                    String colField = SchemaAnalyzer.capitalize(SchemaAnalyzer.toFieldName(strategyCol));
                    if (table.hasCompositePrimaryKey() && isPrimaryKeyColumn(table, strategyCol)) {
                        colField = "Id" + colField;
                    }
                    sb.append("\n    /**\n");
                    sb.append("     * Sequential strategy: fetch records where ").append(strategyCol)
                      .append(" > lastValue.\n");
                    sb.append("     */\n");
                    sb.append("    List<").append(className).append("> find").append(className)
                      .append("By").append(colField).append("GreaterThan(BigDecimal arg1, Pageable pageable);\n");
                } else {
                    sb.append("\n    // Sequential strategy: uses JpaRepository's built-in findAll(Pageable) method.\n");
                }
            }
        }
    }

    private boolean isPrimaryKeyColumn(TableMetadata table, String columnName) {
        return table.getPrimaryKeys().stream()
                .anyMatch(pk -> pk.getColumnName().equalsIgnoreCase(columnName));
    }

    private void addStrategyImports(Set<String> imports, TableMetadata table) {
        SourceStrategy strategy = config.getSourceStrategy();
        if (strategy == SourceStrategy.READING_INDICATOR && config.getStrategyColumn() != null) {
            String colType = resolveStrategyColumnType(table, config.getStrategyColumn());
            addTypeImport(imports, colType);
        }
        if (strategy == SourceStrategy.TIMESTAMP && config.getStrategyColumn() != null) {
            imports.add("java.util.Date");
        }
        if (strategy == SourceStrategy.SEQUENTIAL && config.getStrategyColumn() != null) {
            imports.add("java.math.BigDecimal");
        }
    }

    private void addIdTypeImport(Set<String> imports, String idType) {
        addTypeImport(imports, idType);
    }

    private void addTypeImport(Set<String> imports, String type) {
        if (type != null && type.contains(".") && !type.startsWith("java.lang.")) {
            imports.add(type);
        }
    }

    private String resolveIdType(TableMetadata table) {
        if (table.hasCompositePrimaryKey()) {
            return config.getBasePackage() + ".entity." + table.getJavaClassName() + "Id";
        }
        if (table.getPrimaryKeys().isEmpty()) {
            // For views, resolve the type of the synthetic @Id column
            String syntheticIdCol = EntityGenerator.resolveSyntheticIdColumn(table);
            if (syntheticIdCol != null) {
                return table.getColumns().stream()
                        .filter(c -> c.getColumnName().equals(syntheticIdCol))
                        .findFirst()
                        .map(ColumnMetadata::getJavaTypeName)
                        .orElse("java.lang.Long");
            }
            return "java.lang.Long";
        }
        return table.getPrimaryKeys().get(0).getJavaTypeName();
    }

    private String simpleIdType(String fqn) {
        return EntityGenerator.simpleType(fqn);
    }

    private String resolveStrategyColumnType(TableMetadata table, String columnName) {
        return table.getColumns().stream()
                .filter(c -> c.getColumnName().equalsIgnoreCase(columnName))
                .findFirst()
                .map(c -> EntityGenerator.simpleType(c.getJavaTypeName()))
                .orElse("Object");
    }

    /**
     * Returns the fully-qualified Java type of a strategy column (needed for imports).
     */
    private String resolveStrategyColumnFqn(TableMetadata table, String columnName) {
        return table.getColumns().stream()
                .filter(c -> c.getColumnName().equalsIgnoreCase(columnName))
                .findFirst()
                .map(ColumnMetadata::getJavaTypeName)
                .orElse("java.lang.Object");
    }
}
