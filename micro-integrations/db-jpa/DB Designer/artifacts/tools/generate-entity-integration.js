/**
 * Integration module: Bridges the existing Connector Designer backend
 * with the DB CLI entity generation.
 *
 * This module provides a drop-in replacement for the generateEntity() method
 * in controller-cd-connectors.js. It:
 *
 * 1. Takes the same args the existing generateEntity() receives from the frontend
 * 2. Invokes the DB CLI tool to generate entities (instead of Hibernate Tools)
 * 3. Places the output in the same folder structure the rest of the pipeline expects
 * 4. Returns a compatible result object
 *
 * Usage in controller-cd-connectors.js:
 *   const { generateEntityWithDbCli } = require('../../artifacts/tools/generate-entity-integration');
 *
 *   // In generateEntity() method, replace the Hibernate Tools block with:
 *   let result = await generateEntityWithDbCli(args, destinationPath, schemaId);
 */

const path = require('path');
const fs = require('fs');
const { generateEntitiesWithCli, isCliSupported } = require('./generate-entities-cli');

/**
 * Redacts credentials from a URL string.
 * Masks user:password in JDBC URLs.
 */
function redactUrl(url) {
    if (!url) return '';
    return url.replace(/\/\/[^:]+:[^@]+@/, '//***:***@');
}

/**
 * Drop-in replacement for the generateEntity() Hibernate Tools pipeline.
 *
 * @param {Object} dbInfo - The database info object from the frontend, containing:
 *   - DB_CONNECTION_URL: JDBC URL
 *   - DB_DRIVER_NAME: JDBC driver class name
 *   - DB_USER_NAME: username
 *   - DB_USER_PASSWORD: password
 *   - SCHEMA_NAME: schema name
 *   - TABLE_NAME: table name (comma-separated or single)
 *   - SCHEMA_ID: unique schema identifier
 *   - DB_CHILD_TABLE: comma-separated child tables (optional)
 *   - STRATEGY: sequential, timestamp, or readingIndicator
 *   - DB_READ_RECORD_*_INDICATOR: strategy column name
 * @param {string} destinationPath - Base destination path for entity files
 * @param {string} schemaId - Schema identifier
 * @returns {Promise<Object>} Compatible result object
 */
async function generateEntityWithDbCli(dbInfo, destinationPath, schemaId) {
    if (process.env.DB_CLI_ENABLED === 'false') {
        throw new Error('DB CLI entity generation is disabled');
    }

    const result = {
        entityCreated: false,
        status: '',
        entityPath: '',
    };

    try {
        // Resolve paths matching the existing folder structure
        const generateEntityCommonPath = path.join(
            'src', 'main', 'java', 'com', 'solace', 'connector', 'db', 'pull', 'entity'
        );

        // The existing pipeline stores entities in:
        //   <destinationPath>/generateEntity/src/main/java/com/solace/connector/db/pull/entity/
        // We replicate this so the rest of the pipeline (updateEntityFiles, generateConnectorEntity)
        // can find the files in the same location.
        const generateEntityZipName = 'generateEntity';
        const generateEntityTemplatePath = path.join(destinationPath, generateEntityZipName);
        const entityFilesPath = path.join(generateEntityTemplatePath, generateEntityCommonPath);

        // Clean and recreate the output directory to prevent stale files
        if (fs.existsSync(entityFilesPath)) {
            fs.rmSync(entityFilesPath, { recursive: true, force: true });
        }
        fs.mkdirSync(entityFilesPath, { recursive: true });

        // Resolve the strategy and strategy column
        const strategy = dbInfo.STRATEGY || 'sequential';
        let strategyColumn = '';
        if (strategy) {
            const stratUpper = strategy.toUpperCase();
            strategyColumn = dbInfo[`DB_READ_RECORD_${stratUpper}_INDICATOR`] || '';
        }

        // Resolve child tables
        const childTables = dbInfo.DB_CHILD_TABLE || '';

        console.log(`[Integration] Generating entities via DB CLI`);
        console.log(`[Integration] Driver: ${dbInfo.DB_DRIVER_NAME}`);
        console.log(`[Integration] URL: ${redactUrl(dbInfo.DB_CONNECTION_URL)}`);
        console.log(`[Integration] Schema: ${dbInfo.SCHEMA_NAME}`);
        console.log(`[Integration] Table: ${dbInfo.TABLE_NAME}`);
        console.log(`[Integration] Strategy: ${strategy}`);
        console.log(`[Integration] Strategy Column: ${strategyColumn}`);
        console.log(`[Integration] Child Tables: ${childTables}`);

        const cliResult = await generateEntitiesWithCli({
            jdbcUrl: dbInfo.DB_CONNECTION_URL,
            driverName: dbInfo.DB_DRIVER_NAME,
            username: dbInfo.DB_USER_NAME,
            password: dbInfo.DB_USER_PASSWORD,
            schema: dbInfo.SCHEMA_NAME,
            tableName: dbInfo.TABLE_NAME,
            childTables: childTables,
            strategy: strategy,
            strategyColumn: strategyColumn,
            connectorMode: 'SOURCE',
            outputDir: entityFilesPath,
            packageName: 'com.solace.connector.db.pull.entity',
            schemaId: schemaId,
        });

        // Validate that entity files were actually generated
        const generatedFiles = cliResult.generatedFiles || [];
        if (generatedFiles.length === 0) {
            throw new Error('DB CLI completed but produced no entity files');
        }

        // Spot-check: verify at least one file contains @Entity annotation
        let hasEntityAnnotation = false;
        for (const filePath of generatedFiles) {
            if (filePath.endsWith('.java')) {
                try {
                    const content = fs.readFileSync(filePath, 'utf-8');
                    if (content.includes('@Entity')) {
                        hasEntityAnnotation = true;
                        break;
                    }
                } catch (_) { /* skip unreadable files */ }
            }
        }
        if (!hasEntityAnnotation) {
            console.warn(`[Integration] Warning: No generated file contains @Entity annotation`);
        }

        result.entityCreated = true;
        result.status = 'Process initiated for generating entities';
        result.entityPath = entityFilesPath;
        result.cliResult = cliResult;

        console.log(`[Integration] Entity generation successful. Files at: ${entityFilesPath}`);
        console.log(`[Integration] Generated ${generatedFiles.length} files:`);
        generatedFiles.forEach(f => console.log(`  - ${path.basename(f)}`));

        return result;

    } catch (error) {
        console.error(`[Integration] Entity generation failed: ${error.message}`);
        result.status = error.message;
        throw error;
    }
}

/**
 * Drop-in replacement for generateConnectorEntity().
 * Generates the entity JAR for the final connector deployment package.
 *
 * @param {string} schemaId - Schema identifier
 * @param {string} splitConnectorType - Connector type (e.g., 'SOURCE_DATABASE_JPA')
 * @param {Object} dbInfo - Database connection info
 * @param {string} tableName - Table name(s)
 * @param {string} childTables - Child table name(s)
 * @param {string} strategy - Source strategy
 * @param {string} strategyColumn - Strategy column name
 * @returns {Promise<string>} Path to the generated entity JAR
 */
async function generateConnectorEntityWithDbCli(schemaId, splitConnectorType, dbInfo, tableName, childTables, strategy, strategyColumn) {
    const destinationPath = process.env.CCC_DOWNLOAD_GENERATE_ENTITY_PATH || '';
    const schemaPath = path.join(destinationPath, schemaId);

    // Determine package based on connector type
    const isSource = !splitConnectorType.includes('SINK');
    const connectorMode = isSource ? 'SOURCE' : 'SINK';
    const packageName = isSource
        ? 'com.solace.connectors.database.source.entity'
        : 'com.solace.connectors.database.sink.entity';

    // Create output paths
    const entityOutputDir = path.join(schemaPath, 'cli-generated-entities');
    const jarOutputPath = path.join(schemaPath, 'entity.jar');

    if (!fs.existsSync(entityOutputDir)) {
        fs.mkdirSync(entityOutputDir, { recursive: true });
    }

    console.log(`[Integration] Generating connector entity JAR via DB CLI`);
    console.log(`[Integration] Mode: ${connectorMode}, Package: ${packageName}`);

    const cliResult = await generateEntitiesWithCli({
        jdbcUrl: dbInfo.DB_CONNECTION_URL,
        driverName: dbInfo.DB_DRIVER_NAME,
        username: dbInfo.DB_USER_NAME,
        password: dbInfo.DB_USER_PASSWORD,
        schema: dbInfo.SCHEMA_NAME,
        tableName: tableName,
        childTables: childTables,
        strategy: strategy,
        strategyColumn: strategyColumn,
        connectorMode: connectorMode,
        outputDir: entityOutputDir,
        jarOutput: jarOutputPath,
        packageName: packageName,
        schemaId: schemaId,
    });

    console.log(`[Integration] Entity JAR generated at: ${jarOutputPath}`);
    return jarOutputPath;
}

module.exports = {
    generateEntityWithDbCli,
    generateConnectorEntityWithDbCli,
    isCliSupported,
};
