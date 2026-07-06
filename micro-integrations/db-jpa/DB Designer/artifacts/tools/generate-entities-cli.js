/**
 * DB CLI Entity Generator Wrapper
 *
 * Replaces the Hibernate Tools (hbm2java) approach for generating JPA entities.
 * Invokes the jpa-entity-generator CLI JAR as a subprocess and returns
 * the path to the generated entity files.
 *
 * This module is designed to be called from the existing backend service
 * (controller-cd-connectors.js) as a drop-in replacement for the Maven/Hibernate
 * entity generation pipeline.
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// Directory holding the DB CLI JAR (inside the container).
const CLI_TOOLS_DIR = path.join(process.cwd(), 'artifacts', 'tools');

/**
 * Resolve the DB CLI jar path LAZILY (at call time, not module load).
 * This module is required via `node --require` BEFORE dotenv populates
 * process.env, so reading DB_CLI_JAR_PATH at load time silently falls
 * back to a hardcoded default. Resolution order:
 *   1. DB_CLI_JAR_PATH (if set and the file exists)
 *   2. the versionless artifacts/tools/jpa-entity-generator.jar
 *   3. any jpa-entity-generator*.jar in artifacts/tools (newest name last)
 */
function resolveCliJarPath() {
    const envPath = process.env.DB_CLI_JAR_PATH;
    if (envPath && fs.existsSync(envPath)) {
        return envPath;
    }
    const versionless = path.join(CLI_TOOLS_DIR, 'jpa-entity-generator.jar');
    if (fs.existsSync(versionless)) {
        return versionless;
    }
    try {
        const candidate = fs.readdirSync(CLI_TOOLS_DIR)
            .filter((f) => /^jpa-entity-generator.*\.jar$/.test(f))
            .sort()
            .pop();
        if (candidate) {
            return path.join(CLI_TOOLS_DIR, candidate);
        }
    } catch (e) {
        // fall through to the versionless default for a clear error message
    }
    return versionless;
}

// Timeout for CLI generation process
const GENERATION_TIMEOUT_MS = parseInt(process.env.DB_CLI_TIMEOUT_MS || '120000', 10);

/**
 * Redacts password from a string (e.g., CLI args or URLs).
 * Masks passwords in JDBC URLs and bare password values.
 */
function redactPassword(str) {
    if (!str) return '';
    // Redact password in JDBC URLs: //user:password@ -> //user:***@
    let redacted = str.replace(/\/\/([^:]+):([^@]+)@/g, '//$1:***@');
    // Redact --password argument values
    redacted = redacted.replace(/(--password\s+)\S+/g, '$1***');
    return redacted;
}

/**
 * Maps JDBC driver class names to DB CLI vendor identifiers.
 * The DB CLI currently supports POSTGRESQL, MYSQL, ORACLE.
 */
const DRIVER_TO_VENDOR = {
    'org.postgresql.Driver': 'POSTGRESQL',
    'com.mysql.cj.jdbc.Driver': 'MYSQL',
    'com.mysql.jdbc.Driver': 'MYSQL',
    'org.mariadb.jdbc.Driver': 'MARIADB',
    'oracle.jdbc.OracleDriver': 'ORACLE',
    'oracle.jdbc.driver.OracleDriver': 'ORACLE',
    'com.microsoft.sqlserver.jdbc.SQLServerDriver': 'MSSQL',
    'com.vertica.jdbc.Driver': null,                       // Not yet supported
    'com.sap.db.jdbc.Driver': null,                        // Not yet supported
};

/**
 * Resolves the DB CLI vendor from a JDBC driver class name.
 * @param {string} driverClassName - The JDBC driver class name
 * @returns {string|null} The vendor identifier or null if unsupported
 */
function resolveVendor(driverClassName) {
    if (!driverClassName) return null;

    // Direct match
    if (DRIVER_TO_VENDOR[driverClassName] !== undefined) {
        return DRIVER_TO_VENDOR[driverClassName];
    }

    // Keyword-based fallback
    const lower = driverClassName.toLowerCase();
    if (lower.includes('postgresql') || lower.includes('postgres')) return 'POSTGRESQL';
    if (lower.includes('mariadb')) return 'MARIADB';
    if (lower.includes('mysql')) return 'MYSQL';
    if (lower.includes('oracle')) return 'ORACLE';
    if (lower.includes('sqlserver') || lower.includes('mssql')) return 'MSSQL';

    return null;
}

/**
 * Maps the designer's strategy names to DB CLI strategy values.
 * Designer uses: 'sequential', 'timestamp', 'readingIndicator'
 * DB CLI uses: 'SEQUENTIAL', 'TIMESTAMP', 'READING_INDICATOR'
 */
function resolveStrategy(designerStrategy) {
    if (!designerStrategy) return 'SEQUENTIAL';

    const strategyMap = {
        'sequential': 'SEQUENTIAL',
        'timestamp': 'TIMESTAMP',
        'readingindicator': 'READING_INDICATOR',
        'reading_indicator': 'READING_INDICATOR',
    };

    return strategyMap[designerStrategy.toLowerCase()] || 'SEQUENTIAL';
}

/**
 * Generates JPA entities using the DB CLI tool.
 *
 * @param {Object} options
 * @param {string} options.jdbcUrl        - Full JDBC connection URL
 * @param {string} options.driverName     - JDBC driver class name
 * @param {string} options.username       - Database username
 * @param {string} options.password       - Database password
 * @param {string} options.schema         - Database schema name
 * @param {string} options.tableName      - Comma-separated table names (e.g., "orders,customers")
 * @param {string} options.childTables    - Comma-separated child table names (optional)
 * @param {string} options.strategy       - Source strategy: sequential, timestamp, readingIndicator
 * @param {string} options.strategyColumn - Column name for timestamp/readingIndicator strategy
 * @param {string} options.connectorMode  - 'SOURCE' or 'SINK'
 * @param {string} options.outputDir      - Directory where entity files will be generated
 * @param {string} options.jarOutput      - Path for the output entity JAR file (optional)
 * @param {string} options.packageName    - Java package name (default: com.solace.connector.db.pull.entity)
 * @param {string} options.schemaId       - Schema identifier for folder organization
 *
 * @returns {Promise<Object>} Result with generated file paths
 */
function generateEntitiesWithCli(options) {
    return new Promise((resolve, reject) => {
        // Input validation
        if (!options.jdbcUrl) return reject(new Error('jdbcUrl is required'));
        if (!options.driverName) return reject(new Error('driverName is required'));
        if (!options.schema) return reject(new Error('schema is required'));

        const {
            jdbcUrl,
            driverName,
            username,
            password,
            schema,
            tableName,
            childTables,
            strategy,
            strategyColumn,
            connectorMode = 'SOURCE',
            outputDir,
            jarOutput,
            packageName = 'com.solace.connector.db.pull.entity',
            schemaId,
        } = options;

        // Resolve vendor from driver name
        const vendor = resolveVendor(driverName);
        if (!vendor) {
            return reject(new Error(
                `Unsupported database vendor for DB CLI entity generation. ` +
                `Driver: ${driverName}. ` +
                `Currently supported: PostgreSQL, MySQL/MariaDB, Oracle. ` +
                `Falling back to legacy Hibernate Tools generation may be required.`
            ));
        }

        // Build table list: combine main table + child tables.
        // The Designer sends regex-style "all tables" placeholders (".*",
        // "*") and may separate names with "|". The CLI expects literal
        // table names or ALL, so normalize: placeholders drop out (empty
        // list => --tables ALL) and "|" is treated like ",".
        const isAllTables = (t) => {
            const v = (t || '').trim();
            return v === '' || v === '.*' || v === '*' || v.toUpperCase() === 'ALL';
        };
        const splitTables = (s) => s.split(/[,|]/).map(t => t.trim()).filter(t => t && !isAllTables(t));
        let allTables = [];
        if (tableName && !isAllTables(tableName)) {
            allTables.push(...splitTables(tableName));
        }
        if (childTables) {
            splitTables(childTables).forEach(child => {
                if (!allTables.includes(child)) {
                    allTables.push(child);
                }
            });
        }

        // Resolve the mode
        const mode = (connectorMode || 'SOURCE').toUpperCase().includes('SINK') ? 'SINK' : 'SOURCE';

        // Build CLI arguments (jar resolved lazily -- see resolveCliJarPath)
        const cliJarPath = resolveCliJarPath();
        const cliArgs = [
            '-jar', cliJarPath,
            'generate',
            '--vendor', vendor,
            '--url', jdbcUrl,
            '--username', username,
            '--password', password || '',
            '--schema', schema,
            '--package', packageName,
            '--mode', mode,
            '--output', outputDir,
            '--clean',
        ];

        // Add tables (if specific tables, use comma-separated; otherwise ALL)
        if (allTables.length > 0) {
            cliArgs.push('--tables', allTables.join(','));
        } else {
            cliArgs.push('--tables', 'ALL');
        }

        // Add strategy for SOURCE mode
        if (mode === 'SOURCE') {
            const cliStrategy = resolveStrategy(strategy);
            cliArgs.push('--strategy', cliStrategy);

            if (strategyColumn && (cliStrategy === 'TIMESTAMP' || cliStrategy === 'READING_INDICATOR')) {
                cliArgs.push('--strategy-column', strategyColumn);
            }

            cliArgs.push('--relationships', 'true');
            cliArgs.push('--include-views', 'false');
        }

        // Add JAR output if specified
        if (jarOutput) {
            cliArgs.push('--jar', jarOutput);
        }

        console.log(`[DB CLI] Generating entities with command: java ${redactPassword(cliArgs.join(' '))}`);
        console.log(`[DB CLI] Vendor: ${vendor}, Mode: ${mode}, Tables: ${allTables.join(',') || 'ALL'}`);

        let stdout = '';
        let stderr = '';

        const child = spawn('java', cliArgs, {
            cwd: process.cwd(),
            env: { ...process.env },
            stdio: ['pipe', 'pipe', 'pipe'],
        });

        // Set a timeout to kill the process if it takes too long
        const timeout = setTimeout(() => {
            child.kill('SIGTERM');
            reject(new Error(`DB CLI generation timed out after ${GENERATION_TIMEOUT_MS / 1000}s`));
        }, GENERATION_TIMEOUT_MS);

        child.stdout.on('data', (data) => {
            const text = data.toString();
            stdout += text;
            console.log(`[DB CLI stdout] ${text}`);
        });

        child.stderr.on('data', (data) => {
            const text = data.toString();
            stderr += text;
            // Spring Boot logs go to stderr, not necessarily errors
            console.log(`[DB CLI stderr] ${text}`);
        });

        child.on('error', (err) => {
            clearTimeout(timeout);
            reject(new Error(`Failed to launch DB CLI: ${err.message}`));
        });

        child.on('close', (code) => {
            clearTimeout(timeout);
            if (code === 0) {
                console.log(`[DB CLI] Entity generation completed successfully`);

                // List generated files
                let generatedFiles = [];
                if (fs.existsSync(outputDir)) {
                    generatedFiles = listJavaFiles(outputDir);
                }

                resolve({
                    success: true,
                    entityCreated: true,
                    status: 'Successfully generated entities using DB CLI',
                    outputDir: outputDir,
                    jarPath: jarOutput || null,
                    generatedFiles: generatedFiles,
                    vendor: vendor,
                    mode: mode,
                    tables: allTables,
                    stdout: stdout,
                });
            } else if (stdout.includes('ERROR:')) {
                // DB CLI returned an error message
                const errorMatch = stdout.match(/ERROR:\s*(.+)/);
                const errorMsg = errorMatch ? errorMatch[1] : 'Unknown generation error';
                reject(new Error(`DB CLI generation failed: ${errorMsg}`));
            } else {
                reject(new Error(
                    `DB CLI process exited with code ${code}. ` +
                    `stdout: ${stdout.slice(-500)}. stderr: ${stderr.slice(-500)}`
                ));
            }
        });
    });
}

/**
 * Recursively lists all .java files in a directory.
 */
function listJavaFiles(dir) {
    let results = [];
    if (!fs.existsSync(dir)) return results;

    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            results.push(...listJavaFiles(fullPath));
        } else if (entry.name.endsWith('.java')) {
            results.push(fullPath);
        }
    }
    return results;
}

/**
 * Checks whether DB CLI supports the given driver.
 * Returns true if the driver maps to a supported vendor.
 */
function isCliSupported(driverName) {
    return resolveVendor(driverName) !== null;
}

module.exports = {
    generateEntitiesWithCli,
    resolveVendor,
    resolveStrategy,
    isCliSupported,
    resolveCliJarPath,
};
