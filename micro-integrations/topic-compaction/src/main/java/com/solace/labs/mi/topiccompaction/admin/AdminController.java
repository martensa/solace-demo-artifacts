package com.solace.labs.mi.topiccompaction.admin;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.io.OutputStream;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Administrative REST surface. All endpoints under
 * {@code /api/v1/admin} are intended to be secured separately - in
 * V1.0 they share the application-level Basic auth (Phase 4) once
 * that is wired in. Until then, network-policy isolation is the only
 * gatekeeper.
 *
 * <p>Endpoints:
 * <ul>
 *   <li>{@code POST /api/v1/admin/backup} - stream a snapshot of
 *       the KV store as line-delimited JSON</li>
 *   <li>{@code POST /api/v1/admin/restore} - upload a previously
 *       generated backup; wipes the store and re-loads</li>
 * </ul>
 */
@RestController
@RequestMapping("/api/v1/admin")
public class AdminController {

    private static final Logger log =
            LoggerFactory.getLogger(AdminController.class);

    private final BackupService backupService;

    public AdminController(BackupService backupService) {
        this.backupService = backupService;
    }

    /**
     * Stream a backup of the entire KV store directly into the
     * HTTP response body. POST instead of GET because operationally
     * a backup is a side-effecting administrative action (it walks
     * the store and may consume IO bandwidth).
     */
    @PostMapping(value = "/backup",
            produces = "application/x-ndjson")
    public void backup(HttpServletResponse response)
            throws IOException {
        response.setContentType("application/x-ndjson");
        response.setHeader("Content-Disposition",
                "attachment; filename=\"topic-compaction-backup.ndjson\"");
        try (OutputStream out = response.getOutputStream()) {
            BackupService.BackupStats stats = backupService.backup(out);
            response.setHeader("X-Backup-Records",
                    String.valueOf(stats.records()));
            response.setHeader("X-Backup-Duration-Ms",
                    String.valueOf(stats.durationMs()));
        }
    }

    /**
     * Restore the KV store from a previously generated backup. The
     * request body is the raw line-delimited JSON stream produced
     * by {@link #backup(HttpServletResponse)}.
     */
    @PostMapping(value = "/restore",
            consumes = "application/x-ndjson",
            produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<Map<String, Object>> restore(
            HttpServletRequest request) throws IOException {
        BackupService.RestoreStats stats =
                backupService.restore(request.getInputStream());
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("status", "completed");
        body.put("wiped", stats.wiped());
        body.put("restored", stats.restored());
        body.put("skipped", stats.skipped());
        body.put("durationMs", stats.durationMs());
        log.info("AdminController: restore completed {}", stats);
        return ResponseEntity.ok(body);
    }
}
