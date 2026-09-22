#!/usr/bin/env bash
# Explicit operator control for the isolated staging deployment; no data deletion.
set -euo pipefail
: "${ARCAGENT_STAGING_PROJECT:?Set the isolated ArcAgent staging project ID}"
region="${ARCAGENT_STAGING_REGION:-us-central1}"
service="${ARCAGENT_STAGING_SERVICE:-arcagent-staging}"
database="${ARCAGENT_STAGING_DATABASE:-arcagent-staging-db}"
case "${1:-status}" in
  status)
    gcloud run services describe "$service" --project="$ARCAGENT_STAGING_PROJECT" --region="$region" --format='value(status.url,status.conditions[0].status)'
    gcloud sql instances describe "$database" --project="$ARCAGENT_STAGING_PROJECT" --format='value(state,settings.activationPolicy)'
    ;;
  pause)
    # Stop public requests before stopping the database. Internal IAM callers remain authorized.
    gcloud run services remove-iam-policy-binding "$service" --member=allUsers --role=roles/run.invoker --project="$ARCAGENT_STAGING_PROJECT" --region="$region" --quiet >/dev/null
    gcloud sql instances patch "$database" --activation-policy=NEVER --project="$ARCAGENT_STAGING_PROJECT" --quiet
    printf '%s\n' 'Public staging access paused. Persistent storage, retained addresses, backups, and secrets can still incur charges.'
    ;;
  resume)
    gcloud sql instances patch "$database" --activation-policy=ALWAYS --project="$ARCAGENT_STAGING_PROJECT" --quiet
    gcloud run services add-iam-policy-binding "$service" --member=allUsers --role=roles/run.invoker --project="$ARCAGENT_STAGING_PROJECT" --region="$region" --quiet >/dev/null
    printf '%s\n' 'Public staging access resumed. Application bearer authentication and voice checks still apply.'
    ;;
  *)
    printf '%s\n' 'Usage: staging-control.sh [status|pause|resume]' >&2
    exit 2
    ;;
esac
