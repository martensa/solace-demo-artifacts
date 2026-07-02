package com.solace.jpa.entitygen.model;

/**
 * Supported database vendors with their JDBC driver details.
 */
public enum DatabaseVendor {

    POSTGRESQL("org.postgresql.Driver", "jdbc:postgresql://"),
    MYSQL("com.mysql.cj.jdbc.Driver", "jdbc:mysql://"),
    MARIADB("org.mariadb.jdbc.Driver", "jdbc:mariadb://"),
    ORACLE("oracle.jdbc.OracleDriver", "jdbc:oracle:thin:@"),
    MSSQL("com.microsoft.sqlserver.jdbc.SQLServerDriver", "jdbc:sqlserver://");

    private final String driverClass;
    private final String jdbcPrefix;

    DatabaseVendor(String driverClass, String jdbcPrefix) {
        this.driverClass = driverClass;
        this.jdbcPrefix = jdbcPrefix;
    }

    public String getDriverClass() {
        return driverClass;
    }

    public String getJdbcPrefix() {
        return jdbcPrefix;
    }
}
