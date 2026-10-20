{{- define "opsmind.name" -}}opsmind{{- end }}
{{- define "opsmind.fullname" -}}{{ .Release.Name }}-opsmind{{- end }}
{{- define "opsmind.labels" -}}
app.kubernetes.io/name: opsmind
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: Helm
{{- end }}
