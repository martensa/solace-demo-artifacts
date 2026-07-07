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

// Cache of the /generate/connector/binary JSON response, keyed by the full
// request URL (flow + version + env + download options). The vendor builds
// the package synchronously inside the request; under QEMU emulation that
// exceeds the UI's ~20s axios timeout (HTTP 499) even though the package is
// built correctly. Caching the response lets a repeat click return instantly
// (well under the timeout). Cleared whenever entities are regenerated.
const downloadRespCache = new Map();
const DOWNLOAD_CACHE_TTL_MS = 10 * 60 * 1000;

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
                    // Entities changed -> any cached download is stale.
                    downloadRespCache.clear();

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
            if (fs.existsSync(cachePath)) {
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

        // Wrap the connector-binary download route with a response cache so a
        // repeat click returns instantly (beating the UI's ~20s timeout).
        try {
            const routePath = path.join(process.cwd(), '..', 'src', 'routes', 'route-cd-connectors');
            const routeModule = require(routePath);
            const router = routeModule.default || routeModule;
            let wrapped = 0;
            (router.stack || []).forEach((layer) => {
                const r = layer && layer.route;
                if (!r || r.path !== '/generate/connector/binary' || !(r.methods && r.methods.get)) return;
                r.stack.forEach((h) => {
                    const orig = h.handle;
                    h.handle = function (req, res, next) {
                        const key = req.originalUrl || req.url;
                        const hit = downloadRespCache.get(key);
                        if (hit && (Date.now() - hit.ts) < DOWNLOAD_CACHE_TTL_MS) {
                            console.log('[DB CLI Patch] download response cache HIT');
                            if (hit.headers) Object.keys(hit.headers).forEach((k) => res.set(k, hit.headers[k]));
                            return res.send(hit.body);
                        }
                        const origSend = res.send.bind(res);
                        res.send = function (body) {
                            try {
                                if (res.statusCode < 400 && body && (typeof body === 'object' ? body.zip : true)) {
                                    downloadRespCache.set(key, {
                                        body: body, ts: Date.now(),
                                        headers: {
                                            'Content-Type': res.get('Content-Type'),
                                            'Content-Disposition': res.get('Content-Disposition'),
                                        },
                                    });
                                    console.log('[DB CLI Patch] download response cached');
                                }
                            } catch (e) { /* non-fatal */ }
                            return origSend(body);
                        };
                        return orig.call(this, req, res, next);
                    };
                    wrapped += 1;
                });
            });
            console.log(`[DB CLI Patch] download route response cache installed (handlers wrapped: ${wrapped})`);
        } catch (routeErr) {
            console.error(`[DB CLI Patch] could not install download response cache: ${routeErr.message}`);
        }

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
