/**
 * Patch Script: Monkey-patches the ConnectorsController to use DB CLI
 * for entity generation instead of Hibernate Tools.
 *
 * This script is loaded at startup via the additionals mechanism or
 * by requiring it in www.js. It intercepts the generateEntity() and
 * generateConnectorEntity() calls and redirects them to the DB CLI.
 *
 * How it works:
 * 1. Requires the original controller module
 * 2. Saves references to the original methods
 * 3. Replaces generateEntity() with a version that:
 *    a. Checks if DB CLI supports the database vendor
 *    b. If supported: uses DB CLI for generation
 *    c. If not supported: falls back to original Hibernate Tools method
 *
 * Installation:
 *   Add to the service startup by placing this in the additionals folder
 *   or modifying the Dockerfile CMD to require this before www.js
 */

const path = require('path');
const fs = require('fs');

// Resolve paths relative to the service working directory
const TOOLS_DIR = path.join(process.cwd(), 'artifacts', 'tools');
const { sanitizeEntityRelationships } = require(path.join(TOOLS_DIR, 'sanitize-entity-relationships'));

/**
 * Force a single, correct RUNTIME package on every entity .java in entityDir
 * (com.solace.connectors.database.{source|sink}.entity), just before Maven
 * compiles the connector entity jar.
 *
 * Why this is needed: the vendor copies the CLI-generated entities into the
 * connector Maven tree and rewrites their package to the runtime package --
 * but its rewrite assumes `package ...;` is the FIRST line. Our CLI emits a
 * `/** ... *\/` header first, so the vendor clobbers the comment opener and
 * leaves the ORIGINAL package line intact -> the file ends up with TWO package
 * declarations. Maven then compiles to an inconsistent package and the
 * connector's `Class.forName(tableClass)` throws
 * `EntityName ... ClassNotFound`. This runs on every download's jar build, so
 * the compiled classes always match the `tableClass` the vendor writes,
 * regardless of the (possibly stale/mangled) generateEntity sources.
 */
function normalizeEntityPackage(entityDir, splitConnectorType) {
    const runtimePkg = splitConnectorType && splitConnectorType.includes('SINK')
        ? 'com.solace.connectors.database.sink.entity'
        : 'com.solace.connectors.database.source.entity';
    let files;
    try {
        files = fs.readdirSync(entityDir).filter((f) => f.endsWith('.java'));
    } catch (e) {
        console.error(`[Sanitize Patch] normalizeEntityPackage: cannot read ${entityDir}: ${e.message}`);
        return;
    }
    let fixed = 0;
    for (const f of files) {
        const p = path.join(entityDir, f);
        let src;
        try { src = fs.readFileSync(p, 'utf8'); } catch (e) { continue; }
        let body = src;
        // Normalize stale package references (imports + nested `.entity.entity`).
        body = body.replace(/com\.solace\.connector\.db\.pull\.entity(?:\.entity)*/g, runtimePkg);
        // Strip EVERY existing package declaration.
        body = body.replace(/^[ \t]*package[ \t]+[^\n;]+;[ \t]*\r?\n/gm, '');
        // Repair a doc comment whose `/**` opener was eaten by the vendor rewrite.
        if (/^[ \t]*\*/.test(body)) {
            body = '/**\n' + body;
        }
        const out = `package ${runtimePkg};\n` + body;
        if (out !== src) {
            try { fs.writeFileSync(p, out); fixed++; } catch (e) { /* skip unwritable */ }
        }
    }
    if (fixed > 0) {
        console.log(`[Sanitize Patch] normalizeEntityPackage: single package -> ${runtimePkg} in ${fixed} file(s)`);
    }
}

/**
 * Wraps the original generateConnectorEntity to sanitize entity files
 * before Maven compilation. This fixes compilation errors caused by
 * dangling @OneToMany/@ManyToOne references to entity types that were
 * filtered out during updateEntityFiles().
 *
 * The original flow copies entity files from generateEntity_updated/ into
 * solace-connector-entity/src/main/java/.../entity/ and then runs
 * `mvn clean install`. If the kept entities reference removed entities
 * (e.g. Customers references Orders via @OneToMany), the build fails.
 *
 * This wrapper monkey-patches the copyFolderSync function to run
 * sanitization on the target entity directory after copying.
 */
async function sanitizedMavenBuild(originalFn, schemaId, splitConnectorType) {
    // Determine the target entity directory that generateConnectorEntity will populate
    const solaceConnectorEntityPath = process.env.CD_CONNECTOR_ENTITY_PATH || '';
    const connectorEntityUnzipPath = solaceConnectorEntityPath
        .split('/').slice(-1)[0].split('.')[0];

    const connectorEntitySourcePath = path.join('src', 'main', 'java', 'com', 'solace', 'connectors', 'database', 'source');
    const connectorEntitySinkPath = path.join('src', 'main', 'java', 'com', 'solace', 'connectors', 'database', 'sink');

    let destinationPath = process.env.CCC_DOWNLOAD_GENERATE_ENTITY_PATH || '';
    destinationPath = path.join(destinationPath, schemaId);

    const entityDir = path.join(
        destinationPath,
        connectorEntityUnzipPath,
        splitConnectorType.includes('SINK') ? connectorEntitySinkPath : connectorEntitySourcePath,
        'entity'
    );

    // Hook into the Maven execution: patch the generateJarFile module to
    // sanitize entities right before Maven runs
    const generateJarFilePath = path.join(
        process.cwd(), '..', 'src', 'helpers', 'entityOperations', 'generateJarFile'
    );
    const generateJarModule = require(generateJarFilePath);
    const originalExecuteMaven = generateJarModule.executeMavenCommand;

    // Temporarily wrap executeMavenCommand to sanitize before Maven runs
    generateJarModule.executeMavenCommand = async function (command, workingDirectory, newJarName, currentJarFileNaming) {
        // Sanitize the entity files in the target directory before Maven compiles them
        console.log(`[Sanitize Patch] Sanitizing entity files in: ${entityDir}`);
        try {
            const result = sanitizeEntityRelationships(entityDir);
            if (result.sanitizedFiles.length > 0) {
                console.log(`[Sanitize Patch] Sanitized ${result.sanitizedFiles.length} file(s): ${result.sanitizedFiles.join(', ')}`);
                for (const [file, types] of Object.entries(result.removedReferences)) {
                    console.log(`[Sanitize Patch]   ${file}: removed references to ${types.join(', ')}`);
                }
            } else {
                console.log(`[Sanitize Patch] No dangling references found — all entity files are clean`);
            }
        } catch (sanitizeError) {
            console.error(`[Sanitize Patch] Warning: sanitization failed: ${sanitizeError.message}`);
            console.error(`[Sanitize Patch] Proceeding with Maven build anyway...`);
        }

        // Force a single correct runtime package so the compiled classes match
        // the tableClass the connector loads (avoids ClassNotFound at launch).
        try {
            normalizeEntityPackage(entityDir, splitConnectorType);
        } catch (npErr) {
            console.error(`[Sanitize Patch] Warning: package normalize failed: ${npErr.message}`);
        }

        // Restore original and call it
        generateJarModule.executeMavenCommand = originalExecuteMaven;
        return originalExecuteMaven(command, workingDirectory, newJarName, currentJarFileNaming);
    };

    try {
        return await originalFn(schemaId, splitConnectorType);
    } catch (error) {
        // Restore original in case of error
        generateJarModule.executeMavenCommand = originalExecuteMaven;
        throw error;
    }
}

/**
 * Apply the entity generation patch.
 * Call this from the service startup (e.g., www.js or additionals).
 */
function applyPatch() {
    try {
        // Import the integration module from the tools directory
        const {
            generateEntityWithDbCli,
            generateConnectorEntityWithDbCli,
            isCliSupported,
        } = require(path.join(TOOLS_DIR, 'generate-entity-integration'));

        // Locate the ConnectorsController module
        // In the Docker container, the compiled JS is at:
        //   /app/dist/src/controllers/controller-cd-connectors.js
        // process.cwd() is /app/dist/bin, so we go up one level to /app/dist
        const controllerPath = path.join(process.cwd(), '..', 'src', 'controllers', 'controller-cd-connectors');
        const controllerModule = require(controllerPath);
        const ConnectorsController = controllerModule.ConnectorsController;

        if (!ConnectorsController) {
            console.error('[DB CLI Patch] ConnectorsController not found. Patch not applied.');
            return false;
        }

        // Save reference to original generateEntity
        const originalGenerateEntity = ConnectorsController.prototype.generateEntity;

        // Patch generateEntity()
        ConnectorsController.prototype.generateEntity = async function (args) {
            const data = args['data'] || args;
            const driverName = data.DB_DRIVER_NAME || '';

            console.log(`[DB CLI Patch] generateEntity called. Driver: ${driverName}`);

            // Check if DB CLI supports this vendor
            if (isCliSupported(driverName)) {
                console.log(`[DB CLI Patch] Using DB CLI for entity generation`);

                try {
                    const destinationPath = process.env.CCC_DOWNLOAD_GENERATE_ENTITY_PATH || '';
                    const schemaId = data.SCHEMA_ID || '';
                    const schemaDestPath = path.join(destinationPath, schemaId);

                    // Ensure schema directory exists
                    if (!fs.existsSync(schemaDestPath)) {
                        fs.mkdirSync(schemaDestPath, { recursive: true });
                    }

                    // DB CLI generates the entity SOURCES here. The compiled
                    // entity.jar is built later by generateConnectorEntity via
                    // Maven (the connector loads compiled .class at runtime, so
                    // the CLI source-jar packager is intentionally NOT used for
                    // the jar build).
                    const result = await generateEntityWithDbCli(data, schemaDestPath, schemaId);

                    // Invalidate the compiled entity.jar cache: entities just
                    // changed, so the next download must rebuild via Maven.
                    try {
                        fs.unlinkSync(path.join(schemaDestPath, '.entity-compiled.cache.jar'));
                        console.log(`[DB CLI Patch] Invalidated compiled entity.jar cache for ${schemaId}`);
                    } catch (e) { /* no cache yet */ }

                    // Update entity info in DB (same as original does)
                    if (this.updateEntityInfoInDb && schemaId) {
                        try {
                            await this.updateEntityInfoInDb(schemaId, 'true');
                        } catch (dbError) {
                            console.error(`[DB CLI Patch] Failed to update entity status in DB: ${dbError.message}`);
                        }
                    }

                    return result;

                } catch (cliError) {
                    console.error(`[DB CLI Patch] DB CLI generation failed: ${cliError.message}`);
                    console.log(`[DB CLI Patch] Falling back to Hibernate Tools...`);
                    return originalGenerateEntity.call(this, args);
                }
            } else {
                console.log(`[DB CLI Patch] Vendor not supported by DB CLI. Using Hibernate Tools.`);
                return originalGenerateEntity.call(this, args);
            }
        };

        // Patch the generateConnectorEntity helper
        const generateConnectorEntityPath = path.join(
            process.cwd(), '..', 'src', 'helpers', 'entityOperations', 'generateConnectorEntity'
        );
        const originalModule = require(generateConnectorEntityPath);
        const originalGenerateConnectorEntity = originalModule.generateConnectorEntity;

        // We wrap the export - but since it's already been required,
        // we need to patch it in place
        originalModule.generateConnectorEntity = async function (schemaId, splitConnectorType) {
            console.log(`[DB CLI Patch] generateConnectorEntity called for schema: ${schemaId}`);

            const destinationPath = process.env.CCC_DOWNLOAD_GENERATE_ENTITY_PATH || '';

            // Cache the COMPILED entity.jar. `mvn clean install` is slow under
            // emulation and the vendor runs it on EVERY download, exceeding the
            // client (axios) timeout -> 499. Reuse a cached jar until the
            // entities are regenerated (the generateEntity patch deletes the
            // cache). The controller renames the returned jar into the
            // package's dependencies/, so hand back a throwaway copy and keep
            // the cache intact.
            const cachePath = path.join(destinationPath, schemaId, '.entity-compiled.cache.jar');
            // Invalidate the cache when the DB CLI jar is newer than it: a reseed
            // with an updated CLI (e.g. changed type mapping: integer->Integer,
            // timestamp->java.util.Date) MUST NOT serve a stale compiled entity.jar
            // built by the old CLI. Otherwise reuse it (fast repeat downloads).
            let cacheFresh = fs.existsSync(cachePath);
            if (cacheFresh) {
                try {
                    const cliJar = path.join(TOOLS_DIR, 'jpa-entity-generator.jar');
                    if (fs.existsSync(cliJar) &&
                        fs.statSync(cliJar).mtimeMs > fs.statSync(cachePath).mtimeMs) {
                        cacheFresh = false;
                        console.log('[DB CLI Patch] entity.jar cache older than the CLI jar -> rebuilding fresh');
                    }
                } catch (e) { /* stat failed -> keep using the cache */ }
            }
            if (cacheFresh) {
                const handoff = path.join(destinationPath, schemaId, 'entity.jar');
                try {
                    fs.copyFileSync(cachePath, handoff);
                    console.log(`[DB CLI Patch] Reusing cached compiled entity.jar (skipping Maven)`);
                    return handoff;
                } catch (e) {
                    console.error(`[DB CLI Patch] cache copy failed, rebuilding: ${e.message}`);
                }
            }

            // Build the entity.jar via Maven so it contains COMPILED classes
            // (the connector loads it on loader.path at runtime -- a
            // source-only jar would not resolve). Maven compiles the DB CLI
            // generated entities; the sanitize step first strips dangling
            // relationship references so the build does not fail.
            console.log(`[DB CLI Patch] Building compiled entity.jar via Maven`);
            const jarPath = await sanitizedMavenBuild(originalGenerateConnectorEntity, schemaId, splitConnectorType);
            try {
                if (jarPath && fs.existsSync(jarPath)) {
                    fs.copyFileSync(jarPath, cachePath);
                    console.log(`[DB CLI Patch] Cached compiled entity.jar for fast subsequent downloads`);
                }
            } catch (e) { /* non-fatal caching failure */ }
            return jarPath;
        };

        // Fix the vendor getEntityColumns(): its resolve()/reject() fire ONLY
        // from inside a forEach over the entity directory, so when no file in
        // that directory directly matches the table name the Promise NEVER
        // settles -- the package download then hangs forever for any flow that
        // has a data-transformation mapper (the mapper build calls this per
        // table). The DB CLI writes entities package-nested under
        // .../pull/entity (e.g. .../pull/entity/com/.../entity/Customers.java),
        // so the vendor's flat readdir finds only a `com` dir, never matches,
        // and hangs. Replace it with a version that reads the flattened
        // _updated tree first, searches recursively as a fallback, mirrors the
        // vendor's column parsing exactly, and ALWAYS resolves.
        try {
            const parseColumns = (data) => {
                const columns = [];
                if (!data || data.length === 0) return columns;
                data.split('\n').forEach((line) => {
                    if (line && line.includes('private ')) {
                        let columnSplit;
                        if (line.includes('HashSet') || line.includes('ArrayList')) {
                            const lineString = line.split('=').map((v) => v.trim())[0];
                            columnSplit = lineString.split(' ').filter((v) => v !== '');
                        } else {
                            columnSplit = line.split(' ').filter((v) => v !== '');
                        }
                        const columnName = (columnSplit[columnSplit.length - 1] || '').replace(/;/g, '');
                        if (columnName) columns.push({ value: columnName, label: columnName });
                    }
                });
                return columns;
            };
            const findEntityFile = (root, tableName) => {
                const norm = (s) => (s || '').toLowerCase();
                const want = norm(tableName).replace(/_/g, '');
                let idMatch = null;
                let exactMatch = null;
                const stack = [root];
                while (stack.length) {
                    const dir = stack.pop();
                    let entries;
                    try {
                        entries = fs.readdirSync(dir, { withFileTypes: true });
                    } catch (e) { continue; }
                    for (const ent of entries) {
                        const full = path.join(dir, ent.name);
                        if (ent.isDirectory()) { stack.push(full); continue; }
                        if (!ent.name.endsWith('.java')) continue;
                        const tName = ent.name.split('.')[0];
                        if (tName.includes('Id') && norm(tName.replace(/Id/g, '')) === want) {
                            idMatch = idMatch || full;
                        } else if (norm(tName) === want) {
                            exactMatch = exactMatch || full;
                        }
                    }
                }
                // Vendor prefers the Id file, then the plain entity class.
                return idMatch || exactMatch;
            };
            const OrigGetEntityColumns = ConnectorsController.prototype.getEntityColumns;
            ConnectorsController.prototype.getEntityColumns = function (schemaId, tableName, entityPath) {
                return new Promise((resolve) => {
                    try {
                        const entityStorePath = process.env.CCC_DOWNLOAD_GENERATE_ENTITY_PATH || '';
                        const tmplZip = process.env.CCC_GENERATE_ENTITY_TEMPLATE_PATH || '';
                        const zipName = (tmplZip.split('/').pop() || 'generateEntity').split('.')[0] || 'generateEntity';
                        const rel = path.join('src', 'main', 'java', 'com', 'solace', 'connector', 'db', 'pull', 'entity');
                        const baseDir = path.join(entityStorePath, schemaId, zipName);
                        const updatedRoot = path.join(baseDir + '_updated', rel);
                        const plainRoot = path.join(baseDir, rel);
                        const root = fs.existsSync(updatedRoot) ? updatedRoot : plainRoot;
                        const file = fs.existsSync(root) ? findEntityFile(root, tableName) : null;
                        if (file) {
                            const columns = parseColumns(fs.readFileSync(file, 'utf8'));
                            console.log(`[DB CLI Patch] getEntityColumns(${tableName}) -> ${columns.length} columns from ${path.basename(file)}`);
                            return resolve({ table: path.basename(file).split('.')[0], columns: columns });
                        }
                        console.log(`[DB CLI Patch] getEntityColumns(${tableName}): no entity file under ${root} -> resolving empty (prevents the vendor hang)`);
                        return resolve({ table: tableName, columns: [] });
                    } catch (err) {
                        console.error(`[DB CLI Patch] getEntityColumns(${tableName}) error, resolving empty: ${err.message}`);
                        return resolve({ table: tableName, columns: [] });
                    }
                });
            };
            void OrigGetEntityColumns;
            console.log('[DB CLI Patch] getEntityColumns hang-fix installed');
        } catch (gecErr) {
            console.error(`[DB CLI Patch] could not install getEntityColumns hang-fix: ${gecErr.message}`);
        }

        // Fix tableClass/tableKey at their SOURCE. The config generator does:
        //   sourceTableName = getEntityTableNameBasedonDbName(allEntityFiles, flow.tableName)
        //   tableClass = `${pkg}.${sourceTableName}`;  tableKey = sourceTableName
        // where allEntityFiles = readdirSync(<generateEntity>/.../pull/entity).
        // The DB CLI writes entities package-nested (.../pull/entity/com/.../
        // entity/entity/Customers.java), so that readdir yields only ['com'] and
        // the lookup for the flow's real table ('customers') matches nothing ->
        // sourceTableName='' -> `tableClass: <pkg>.` (truncated) + `tableKey: ''`.
        // A plain package download never re-runs generateEntity, so the nested
        // tree persists on every download. Recover by AUGMENTING allEntityFiles
        // with the real entity CLASS names collected recursively from the nested
        // source tree: the vendor's own resolver, keyed on flow.tableName, then
        // returns the correctly-cased class (e.g. 'Customers'). This is
        // schema-accurate -- the match is driven by the selected table, never by
        // entity.jar byte order (which would pick whichever class sorts first).
        try {
            const ENTITY_STORE = process.env.CCC_DOWNLOAD_GENERATE_ENTITY_PATH || '/app/tmp/entityFolders';
            const collectEntityClassNames = (schemaId) => {
                const roots = [];
                const addRoot = (r) => { try { if (r && fs.existsSync(r)) roots.push(r); } catch (e) { /* skip */ } };
                if (schemaId) addRoot(path.join(ENTITY_STORE, schemaId));
                if (!roots.length) {
                    // Sink config-gen passes no schemaId -> scan every schema dir.
                    try {
                        fs.readdirSync(ENTITY_STORE, { withFileTypes: true })
                            .filter((d) => d.isDirectory())
                            .forEach((d) => addRoot(path.join(ENTITY_STORE, d.name)));
                    } catch (e) { /* store missing */ }
                }
                const names = new Set();
                const stack = [...roots];
                while (stack.length) {
                    const dir = stack.pop();
                    let entries;
                    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { continue; }
                    for (const ent of entries) {
                        const full = path.join(dir, ent.name);
                        if (ent.isDirectory()) { stack.push(full); continue; }
                        if (ent.name.endsWith('.java')) names.add(ent.name.replace(/\.java$/, ''));
                    }
                }
                return Array.from(names);
            };
            const augment = (allEntityFiles, schemaId, label) => {
                try {
                    const recovered = collectEntityClassNames(schemaId);
                    if (!recovered.length) return allEntityFiles;
                    const base = Array.isArray(allEntityFiles) ? allEntityFiles : [];
                    const merged = Array.from(new Set([...base, ...recovered]));
                    if (merged.length !== base.length) {
                        console.log(`[DB CLI Patch] allEntityFiles augmented (+${merged.length - base.length}) for ${label} from nested entity tree`);
                    }
                    return merged;
                } catch (e) {
                    console.error(`[DB CLI Patch] allEntityFiles augment failed (${label}): ${e.message}`);
                    return allEntityFiles;
                }
            };
            [
                ['generateConnectorConfigSourceJPA', true],
                ['generateConnectorConfigSourceSQL', true],
                ['generateConnectorConfigSinkJPA', false],
                ['generateConnectorConfigSinkSQL', false],
            ].forEach(([method, hasSchemaId]) => {
                const orig = ConnectorsController.prototype[method];
                if (typeof orig !== 'function') return;
                ConnectorsController.prototype[method] = function (connectorConfigData, allEntityFiles, schemaId) {
                    const fixed = augment(allEntityFiles, hasSchemaId ? schemaId : undefined, method);
                    return orig.call(this, connectorConfigData, fixed, schemaId);
                };
            });
            console.log('[DB CLI Patch] allEntityFiles augmentation installed (tableClass/tableKey root-fix)');
        } catch (augErr) {
            console.error(`[DB CLI Patch] could not install allEntityFiles augmentation: ${augErr.message}`);
        }

        // Fix the JPA dialect. The Designer writes application-operator.yml
        // wholesale from the stored PROJECT_CONFIGURATION blob and NEVER derives
        // solace-persistence.jpa.database from the chosen JDBC driver -- so the
        // connector-binary template default surfaces (sqlserver for source, oracle
        // for sink) even when the user picked Postgres, producing e.g. `select top`
        // (T-SQL) against Postgres. Wrap the config writer to set jpa.database from
        // the driver (via the controller's own driverKeyword) after it writes the
        // operator.yml. The value the connector expects matches the driverKeyword
        // key exactly (org.postgresql.Driver -> "postgresql").
        try {
            const OrigUpdateConfigFiles = ConnectorsController.prototype.updateConfigFilesFromDesginerScreen;
            if (typeof OrigUpdateConfigFiles === 'function') {
                ConnectorsController.prototype.updateConfigFilesFromDesginerScreen = function (projConfigpath) {
                    const args = arguments;
                    const self = this;
                    return Promise.resolve(OrigUpdateConfigFiles.apply(self, args)).then((result) => {
                        try {
                            if (projConfigpath && fs.existsSync(projConfigpath) && typeof self.driverKeyword === 'function') {
                                const content = fs.readFileSync(projConfigpath, 'utf8');
                                const m = content.match(/driver-class-name:\s*['"]?([^'"\n]+)/);
                                const dialect = m ? self.driverKeyword(m[1].trim()) : null;
                                if (dialect) {
                                    const fixed = content.replace(
                                        /(\n[ \t]+database:[ \t]*)(['"]?)(sqlserver|oracle|mysql|mariadb|postgresql|postgres)(['"]?)/gi,
                                        `$1${dialect}`
                                    );
                                    if (fixed !== content) {
                                        fs.writeFileSync(projConfigpath, fixed);
                                        console.log(`[DB CLI Patch] jpa.database derived from driver -> '${dialect}' (${m[1].trim()})`);
                                    }
                                }
                            }
                        } catch (e) { console.error(`[DB CLI Patch] dialect post-process failed: ${e.message}`); }

                        // Fix application-db-processor.yml (connectorPropsConfigPath =
                        // args[2]). The Designer derives tableClass/tableKey from a
                        // single-level scan of the entity dir, which fails when the CLI
                        // wrote entities package-nested -> `tableClass: <pkg>.` (no class)
                        // and `tableKey: ""`. And a CDC feature disabled via
                        // propertiesEnabled but still carrying a value fails the
                        // connector's DbTableIndicatorConfig validation ("must be
                        // configured and empty"). Post-process the written file as a
                        // SAFETY NET (the allEntityFiles augmentation above normally
                        // makes the vendor write these correctly): if tableClass/
                        // tableKey are still empty, fill them from the MAPPER file the
                        // Designer just created (<Table>_trgt_schema_mapper.yml) -- it
                        // is keyed on the flow's real table, so it is authoritative.
                        // NEVER guess from the multi-table entity.jar (byte order is
                        // not the selected table). Then drop every disabled CDC line.
                        try {
                            const dbpPath = args && args[2];
                            if (dbpPath && fs.existsSync(dbpPath)) {
                                let dbp = fs.readFileSync(dbpPath, 'utf8');
                                const before = dbp;
                                if (/^\s*tableClass:\s*\S*\.\s*$/m.test(dbp) || /^\s*tableKey:\s*(""|'')\s*$/m.test(dbp)) {
                                    let entity = null;
                                    const mapperDirs = [
                                        path.join(path.dirname(dbpPath), 'mapper'),
                                        path.join(path.dirname(dbpPath), '..', 'mapper'),
                                        path.join(path.dirname(dbpPath), 'Config', 'mapper'),
                                    ];
                                    for (const md of mapperDirs) {
                                        try {
                                            const mf = fs.readdirSync(md).find((f) => /_trgt_schema_mapper\.yml$/.test(f) && !/^_trgt/.test(f));
                                            if (mf) { entity = mf.replace(/_trgt_schema_mapper\.yml$/, ''); break; }
                                        } catch (e) { /* try next dir */ }
                                    }
                                    if (entity) {
                                        dbp = dbp.replace(/^(\s*tableClass:\s*)(\S*\.)\s*$/m, `$1$2${entity}`);
                                        dbp = dbp.replace(/^(\s*tableKey:\s*)(""|'')\s*$/m, `$1${entity}`);
                                    }
                                }
                                ['dbReadTime', 'dbTrackingId', 'dbReadIndicatorBridgeInProgressValue', 'dbReadIndicatorBridgeFailedValue'].forEach((feat) => {
                                    if (new RegExp(`\\n[ \\t]+${feat}:[ \\t]*false(?=\\r?\\n)`).test(dbp)) {
                                        dbp = dbp.replace(new RegExp(`\\n[ \\t]+${feat}:[^\\n]*`, 'g'), '');
                                    }
                                });
                                if (dbp !== before) {
                                    fs.writeFileSync(dbpPath, dbp);
                                    console.log('[DB CLI Patch] application-db-processor.yml fixed (tableClass/tableKey + disabled-CDC cleanup)');
                                }
                            }
                        } catch (e) { console.error(`[DB CLI Patch] db-processor post-process failed: ${e.message}`); }
                        return result;
                    });
                };
                console.log('[DB CLI Patch] dialect + db-processor post-process installed');
            }
        } catch (dialErr) {
            console.error(`[DB CLI Patch] could not install dialect post-process: ${dialErr.message}`);
        }

        // Note: the browser package download is left fully open -- the user's
        // UI selection (any combination of core connector binary / configs /
        // entity jar) is honoured as-is. Once the getEntityColumns hang above
        // is fixed, every combination completes within the UI client timeout,
        // including the full package with the ~108MB core jar (measured in the
        // emulated lab: HTTP 200, ~150MB, ~15s; faster on native amd64). No
        // server-side override of the download selection is needed.

        console.log('[DB CLI Patch] Entity generation patch applied successfully!');
        console.log('[DB CLI Patch] Supported vendors: PostgreSQL, MySQL/MariaDB, Oracle');
        console.log('[DB CLI Patch] Unsupported vendors will fall back to Hibernate Tools');

        return true;

    } catch (error) {
        console.error(`[DB CLI Patch] Failed to apply patch: ${error.message}`);
        console.error(`[DB CLI Patch] Entity generation will use original Hibernate Tools method.`);
        return false;
    }
}

module.exports = { applyPatch };
