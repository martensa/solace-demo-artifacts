{{/* Standard name + label helpers (helm create skeleton). */}}
{{- define "solace-eventportal-connector.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "solace-eventportal-connector.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "solace-eventportal-connector.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "solace-eventportal-connector.labels" -}}
helm.sh/chart: {{ include "solace-eventportal-connector.chart" . }}
{{ include "solace-eventportal-connector.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: solace-event-portal
{{- end -}}

{{- define "solace-eventportal-connector.selectorLabels" -}}
app.kubernetes.io/name: {{ include "solace-eventportal-connector.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Secret name: the user's existingSecret, else the chart-created one. */}}
{{- define "solace-eventportal-connector.secretName" -}}
{{- if .Values.secret.existingSecret -}}
{{- .Values.secret.existingSecret -}}
{{- else -}}
{{- include "solace-eventportal-connector.fullname" . -}}
{{- end -}}
{{- end -}}

{{/* The bridge image reference (tag defaults to chart appVersion). */}}
{{- define "solace-eventportal-connector.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end -}}

{{/*
The ingestion image reference -- the OM ingestion image with the connector
baked in. Used by the bootstrap Job and the ingestion CronJob (both need the
OM SDK + the connector package, which the slim bridge image does not carry).
Tag defaults to chart appVersion.
*/}}
{{- define "solace-eventportal-connector.ingestionImage" -}}
{{- $tag := .Values.ingestion.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" .Values.ingestion.image.repository $tag -}}
{{- end -}}

{{/*
OM + EP secret env shared by the bootstrap Job and the ingestion CronJob. The
ingestion image reads these via the workflow YAML's ${ENV} interpolation; the
bootstrap entrypoint takes them as CLI flags wired in its own template.
*/}}
{{- define "solace-eventportal-connector.omIngestEnv" -}}
{{- $secret := include "solace-eventportal-connector.secretName" . -}}
- name: OM_INGESTION_BOT_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ .Values.secret.omJwtTokenKey }}
- name: SOLACE_EVENTPORTAL_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ .Values.secret.epApiTokenKey }}
{{- if .Values.ingestion.sampleData.enabled }}
- name: SOLACE_BROKER_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ .Values.secret.solacePasswordKey }}
      optional: true
{{- end }}
{{- end -}}

{{/*
Full env block for the bridge container + CronJobs (kept DRY here so the
Deployment and both CronJobs render byte-identical settings). Mirrors
bridge/config.py prefixes: EP_ / OM_ / BRIDGE_ / BRIDGE_OBS_.
*/}}
{{- define "solace-eventportal-connector.env" -}}
{{- $secret := include "solace-eventportal-connector.secretName" . -}}
{{- $otelEndpoint := ternary "http://localhost:4318" .Values.observability.otel.endpoint .Values.otelCollector.enabled -}}
# Event Portal
- name: EP_API_URL
  value: {{ .Values.eventPortal.apiUrl | quote }}
- name: EP_API_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ .Values.secret.epApiTokenKey }}
- name: EP_WEBHOOK_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ .Values.secret.epWebhookSecretKey }}
      optional: true
# OpenMetadata
- name: OM_HOST_PORT
  value: {{ .Values.openMetadata.hostPort | quote }}
- name: OM_SERVICE_NAME
  value: {{ .Values.openMetadata.serviceName | quote }}
{{- if .Values.openMetadata.tenantPrefix }}
- name: OM_TENANT_PREFIX
  value: {{ .Values.openMetadata.tenantPrefix | quote }}
{{- end }}
- name: OM_JWT_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ .Values.secret.omJwtTokenKey }}
# Transport
- name: BRIDGE_MODE
  value: {{ .Values.mode | quote }}
- name: BRIDGE_POLLING_INTERVAL_SECONDS
  value: {{ .Values.bridge.pollingIntervalSeconds | quote }}
{{- if .Values.bridge.pollingDomainIds }}
- name: BRIDGE_POLLING_DOMAIN_IDS
  value: {{ .Values.bridge.pollingDomainIds | toJson | quote }}
{{- end }}
- name: BRIDGE_DEDUPE_TTL_SECONDS
  value: {{ .Values.bridge.dedupe.ttlSeconds | quote }}
- name: BRIDGE_DEDUPE_MAX_ENTRIES
  value: {{ .Values.bridge.dedupe.maxEntries | quote }}
{{- if .Values.bridge.acceptEventTypes }}
- name: BRIDGE_ACCEPT_EVENT_TYPES
  value: {{ .Values.bridge.acceptEventTypes | toJson | quote }}
{{- end }}
- name: BRIDGE_BIND_PORT
  value: {{ .Values.bridge.bindPort | quote }}
- name: BRIDGE_FORWARDER_TOPIC_PREFIX
  value: {{ .Values.bridge.forwarderTopicPrefix | quote }}
{{- if eq .Values.mode "solace" }}
- name: BRIDGE_SOLACE_HOST
  value: {{ .Values.solace.host | quote }}
- name: BRIDGE_SOLACE_VPN
  value: {{ .Values.solace.vpn | quote }}
- name: BRIDGE_SOLACE_USERNAME
  value: {{ .Values.solace.username | quote }}
- name: BRIDGE_SOLACE_QUEUE
  value: {{ .Values.solace.queue | quote }}
- name: BRIDGE_SOLACE_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ .Values.secret.solacePasswordKey }}
      optional: true
{{- end }}
# Observability (Wave 5)
- name: BRIDGE_OBS_LOG_FORMAT
  value: {{ .Values.observability.logFormat | quote }}
- name: BRIDGE_OBS_LOG_LEVEL
  value: {{ .Values.observability.logLevel | quote }}
- name: BRIDGE_OBS_SHUTDOWN_GRACE_SECONDS
  value: {{ .Values.observability.shutdownGraceSeconds | quote }}
- name: BRIDGE_OBS_METRICS_ENABLED
  value: {{ .Values.observability.metrics.enabled | quote }}
- name: BRIDGE_OBS_METRICS_PORT
  value: {{ .Values.observability.metrics.port | quote }}
- name: BRIDGE_OBS_OTEL_ENABLED
  value: {{ or .Values.observability.otel.enabled .Values.otelCollector.enabled | quote }}
- name: BRIDGE_OBS_OTEL_ENDPOINT
  value: {{ $otelEndpoint | quote }}
- name: BRIDGE_OBS_OTEL_PROTOCOL
  value: {{ .Values.observability.otel.protocol | quote }}
- name: BRIDGE_OBS_OTEL_SERVICE_NAME
  value: {{ .Values.observability.otel.serviceName | quote }}
{{- if .Values.labCaTrust.enabled }}
# On-prem OM TLS: point the requests/urllib3 stack at the lab CA bundle.
- name: REQUESTS_CA_BUNDLE
  value: {{ .Values.labCaTrust.mountPath | quote }}
- name: SSL_CERT_FILE
  value: {{ .Values.labCaTrust.mountPath | quote }}
{{- end }}
{{- end -}}
