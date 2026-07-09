package com.solace.jpa.entitygen;

import com.solace.jpa.entitygen.model.ColumnMetadata;
import com.solace.jpa.entitygen.model.DatabaseVendor;
import com.solace.jpa.entitygen.typemap.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for vendor-specific type mappers.
 */
class TypeMapperTest {

    // ========================
    // Factory method
    // ========================

    @Test
    void forVendorReturnsCorrectMapperTypes() {
        assertInstanceOf(PostgresTypeMapper.class, TypeMapper.forVendor(DatabaseVendor.POSTGRESQL));
        assertInstanceOf(MySqlTypeMapper.class, TypeMapper.forVendor(DatabaseVendor.MYSQL));
        assertInstanceOf(MariaDbTypeMapper.class, TypeMapper.forVendor(DatabaseVendor.MARIADB));
        assertInstanceOf(OracleTypeMapper.class, TypeMapper.forVendor(DatabaseVendor.ORACLE));
        assertInstanceOf(MsSqlTypeMapper.class, TypeMapper.forVendor(DatabaseVendor.MSSQL));
    }

    // ========================
    // PostgreSQL
    // ========================

    @ParameterizedTest
    @CsvSource({
            "bool,       java.lang.Boolean",
            "int4,       java.lang.Integer",
            "int8,       java.lang.Long",
            "float8,     java.lang.Double",
            "varchar,    java.lang.String",
            "text,       java.lang.String",
            "timestamp,  java.util.Date",
            "timestamptz,java.util.Date",
            "bytea,      byte[]",
            "uuid,       java.util.UUID",
            "jsonb,      java.lang.String",
            "money,      java.math.BigDecimal",
    })
    void postgresTypeMappings(String sqlType, String expectedJava) {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.POSTGRESQL);
        ColumnMetadata col = column(sqlType, 0, 0);
        assertEquals(expectedJava, mapper.resolveJavaType(col));
    }

    @Test
    void postgresNumericScaleZeroMapsToBigDecimal() {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.POSTGRESQL);
        ColumnMetadata col = column("numeric", 9, 0);
        // getObject returns BigDecimal for numeric regardless of scale; the
        // connector's reflective setter needs the field type to match.
        assertEquals("java.math.BigDecimal", mapper.resolveJavaType(col));
    }

    @Test
    void postgresNumericWithScaleMapsToDecimal() {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.POSTGRESQL);
        ColumnMetadata col = column("numeric", 10, 2);
        assertEquals("java.math.BigDecimal", mapper.resolveJavaType(col));
    }

    @Test
    void postgresUnknownTypeDefaultsToString() {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.POSTGRESQL);
        ColumnMetadata col = column("SOMECUSTOMTYPE", 0, 0);
        assertEquals("java.lang.String", mapper.resolveJavaType(col));
    }

    // ========================
    // MySQL
    // ========================

    @ParameterizedTest
    @CsvSource({
            "BIT,        java.lang.Boolean",
            "INT,        java.lang.Integer",
            "BIGINT,     java.lang.Long",
            "FLOAT,      java.lang.Float",
            "DOUBLE,     java.lang.Double",
            "VARCHAR,    java.lang.String",
            "TEXT,       java.lang.String",
            "DATE,       java.util.Date",
            "DATETIME,   java.util.Date",
            "JSON,       java.lang.String",
    })
    void mysqlTypeMappings(String sqlType, String expectedJava) {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.MYSQL);
        ColumnMetadata col = column(sqlType, 0, 0);
        assertEquals(expectedJava, mapper.resolveJavaType(col));
    }

    @Test
    void mysqlTinyint1MapsToBoolean() {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.MYSQL);
        ColumnMetadata col = column("TINYINT", 1, 0);
        assertEquals("java.lang.Boolean", mapper.resolveJavaType(col));
    }

    @Test
    void mysqlTinyint3MapsToByte() {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.MYSQL);
        ColumnMetadata col = column("TINYINT", 3, 0);
        assertEquals("java.lang.Byte", mapper.resolveJavaType(col));
    }

    // ========================
    // MariaDB
    // ========================

    @Test
    void mariadbUuidType() {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.MARIADB);
        ColumnMetadata col = column("UUID", 0, 0);
        assertEquals("java.util.UUID", mapper.resolveJavaType(col));
    }

    @Test
    void mariadbDelegatesToMysqlForStandardTypes() {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.MARIADB);
        ColumnMetadata col = column("INT", 0, 0);
        assertEquals("java.lang.Integer", mapper.resolveJavaType(col));
    }

    // ========================
    // Oracle
    // ========================

    @Test
    void oracleNumberMapsToBigDecimal() {
        // Oracle getObject on NUMBER always returns BigDecimal, so every NUMBER
        // (incl. NUMBER(1) and scale-0) maps to BigDecimal for connector runtime
        // compatibility -- no Boolean/Integer narrowing.
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.ORACLE);
        assertEquals("java.math.BigDecimal", mapper.resolveJavaType(column("NUMBER", 1, 0)));
        assertEquals("java.math.BigDecimal", mapper.resolveJavaType(column("NUMBER", 0, -127)));
        assertEquals("java.math.BigDecimal", mapper.resolveJavaType(column("NUMBER", 9, 0)));
    }

    @Test
    void oracleDateMapsToUtilDate() {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.ORACLE);
        ColumnMetadata col = column("DATE", 0, 0);
        assertEquals("java.util.Date", mapper.resolveJavaType(col));
    }

    @Test
    void oracleTimestampWithTimeZoneMapsToUtilDate() {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.ORACLE);
        ColumnMetadata col = column("TIMESTAMP(6) WITH TIME ZONE", 0, 0);
        assertEquals("java.util.Date", mapper.resolveJavaType(col));
    }

    // ========================
    // MSSQL
    // ========================

    @ParameterizedTest
    @CsvSource({
            "BIT,                java.lang.Boolean",
            "INT,                java.lang.Integer",
            "BIGINT,             java.lang.Long",
            "FLOAT,              java.lang.Double",
            "NVARCHAR,           java.lang.String",
            "DATE,               java.util.Date",
            "DATETIME2,          java.util.Date",
            "DATETIMEOFFSET,     java.util.Date",
            "UNIQUEIDENTIFIER,   java.util.UUID",
            "VARBINARY,          byte[]",
    })
    void mssqlTypeMappings(String sqlType, String expectedJava) {
        TypeMapper mapper = TypeMapper.forVendor(DatabaseVendor.MSSQL);
        ColumnMetadata col = column(sqlType, 0, 0);
        assertEquals(expectedJava, mapper.resolveJavaType(col));
    }

    // ========================
    // Helper
    // ========================

    private static ColumnMetadata column(String typeName, int size, int decimals) {
        ColumnMetadata col = new ColumnMetadata();
        col.setSqlTypeName(typeName);
        col.setColumnName("test_col");
        col.setColumnSize(size);
        col.setDecimalDigits(decimals);
        return col;
    }
}
