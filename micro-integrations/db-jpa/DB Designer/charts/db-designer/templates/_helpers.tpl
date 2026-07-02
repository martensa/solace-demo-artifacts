{{/* Chart name (overridable). */}}
{{- define "db-designer.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully qualified app name. */}}
{{- define "db-designer.fullname" -}}
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

{{- define "db-designer.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Common labels. */}}
{{- define "db-designer.labels" -}}
helm.sh/chart: {{ include "db-designer.chart" . }}
{{ include "db-designer.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: db-jpa
{{- end -}}

{{/* Selector labels (component is added per-workload). */}}
{{- define "db-designer.selectorLabels" -}}
app.kubernetes.io/name: {{ include "db-designer.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "db-designer.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "db-designer.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "db-designer.secretName" -}}
{{- if .Values.secret.existingSecret -}}
{{- .Values.secret.existingSecret -}}
{{- else -}}
{{- printf "%s-env" (include "db-designer.fullname" .) -}}
{{- end -}}
{{- end -}}

{{- define "db-designer.postgresServiceName" -}}
{{- printf "%s-postgres" (include "db-designer.fullname" .) -}}
{{- end -}}

{{/* Effective Postgres host: bundled service or external. */}}
{{- define "db-designer.postgresHost" -}}
{{- if .Values.postgres.embedded -}}
{{- include "db-designer.postgresServiceName" . -}}
{{- else -}}
{{- required "postgres.external.host is required when postgres.embedded=false" .Values.postgres.external.host -}}
{{- end -}}
{{- end -}}

{{- define "db-designer.image.services" -}}
{{- $img := .Values.image.services -}}
{{- printf "%s:%s" $img.repository (default $.Chart.AppVersion $img.tag) -}}
{{- end -}}

{{- define "db-designer.image.ui" -}}
{{- $img := .Values.image.ui -}}
{{- printf "%s:%s" $img.repository (default $.Chart.AppVersion $img.tag) -}}
{{- end -}}

{{/* External UI/API hosts and URLs (browser-reachable). Route wins on
     OpenShift, otherwise Ingress. Hosts are required for a working deploy
     because the React app calls the backend from the browser. */}}
{{- define "db-designer.uiHost" -}}
{{- if and (eq .Values.platform "openshift") .Values.route.enabled -}}
{{- required "route.uiHost is required on OpenShift" .Values.route.uiHost -}}
{{- else -}}
{{- required "ingress.uiHost is required" .Values.ingress.uiHost -}}
{{- end -}}
{{- end -}}

{{- define "db-designer.apiHost" -}}
{{- if and (eq .Values.platform "openshift") .Values.route.enabled -}}
{{- required "route.apiHost is required on OpenShift" .Values.route.apiHost -}}
{{- else -}}
{{- required "ingress.apiHost is required" .Values.ingress.apiHost -}}
{{- end -}}
{{- end -}}

{{- define "db-designer.uiUrl" -}}
{{- printf "https://%s" (include "db-designer.uiHost" .) -}}
{{- end -}}

{{- define "db-designer.apiUrl" -}}
{{- printf "https://%s" (include "db-designer.apiHost" .) -}}
{{- end -}}

{{/* Effective Postgres port. */}}
{{- define "db-designer.postgresPort" -}}
{{- if .Values.postgres.embedded -}}
{{- .Values.service.postgres.port -}}
{{- else -}}
{{- .Values.postgres.external.port -}}
{{- end -}}
{{- end -}}
