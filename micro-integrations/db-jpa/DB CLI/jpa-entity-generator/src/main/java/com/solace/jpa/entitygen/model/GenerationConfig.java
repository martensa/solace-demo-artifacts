package com.solace.jpa.entitygen.model;

import java.util.List;

/**
 * Holds all configuration parameters for a single generation run.
 */
public class GenerationConfig {

    private DatabaseVendor vendor;
    private String jdbcUrl;
    private String username;
    private String password;
    private String schema;
    private String basePackage;
    private ConnectorMode connectorMode;
    private SourceStrategy sourceStrategy;
    private String strategyColumn;          // Column used for reading-indicator or timestamp strategy
    private List<String> tableNames;        // null or empty = ALL
    private boolean includeViews;
    private List<String> viewNames;         // null or empty = ALL views (if includeViews)
    private String outputDirectory;
    private boolean generateRelationships;

    public DatabaseVendor getVendor() {
        return vendor;
    }

    public void setVendor(DatabaseVendor vendor) {
        this.vendor = vendor;
    }

    public String getJdbcUrl() {
        return jdbcUrl;
    }

    public void setJdbcUrl(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    public String getSchema() {
        return schema;
    }

    public void setSchema(String schema) {
        this.schema = schema;
    }

    public String getBasePackage() {
        return basePackage;
    }

    public void setBasePackage(String basePackage) {
        this.basePackage = basePackage;
    }

    public ConnectorMode getConnectorMode() {
        return connectorMode;
    }

    public void setConnectorMode(ConnectorMode connectorMode) {
        this.connectorMode = connectorMode;
    }

    public SourceStrategy getSourceStrategy() {
        return sourceStrategy;
    }

    public void setSourceStrategy(SourceStrategy sourceStrategy) {
        this.sourceStrategy = sourceStrategy;
    }

    public String getStrategyColumn() {
        return strategyColumn;
    }

    public void setStrategyColumn(String strategyColumn) {
        this.strategyColumn = strategyColumn;
    }

    public List<String> getTableNames() {
        return tableNames;
    }

    public void setTableNames(List<String> tableNames) {
        this.tableNames = tableNames;
    }

    public boolean isIncludeViews() {
        return includeViews;
    }

    public void setIncludeViews(boolean includeViews) {
        this.includeViews = includeViews;
    }

    public List<String> getViewNames() {
        return viewNames;
    }

    public void setViewNames(List<String> viewNames) {
        this.viewNames = viewNames;
    }

    public String getOutputDirectory() {
        return outputDirectory;
    }

    public void setOutputDirectory(String outputDirectory) {
        this.outputDirectory = outputDirectory;
    }

    public boolean isGenerateRelationships() {
        return generateRelationships;
    }

    public void setGenerateRelationships(boolean generateRelationships) {
        this.generateRelationships = generateRelationships;
    }

    public boolean isSourceMode() {
        return connectorMode == ConnectorMode.SOURCE;
    }

    public boolean isSinkMode() {
        return connectorMode == ConnectorMode.SINK;
    }

    public boolean requiresStrategyColumn() {
        return isSourceMode() && sourceStrategy != null &&
                sourceStrategy != SourceStrategy.SEQUENTIAL;
    }
}
