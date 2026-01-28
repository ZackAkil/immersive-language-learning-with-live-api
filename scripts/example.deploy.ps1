# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) "")
$ErrorActionPreference = "Stop"

# Configuration - replace these values with your own project configuration
$PROJECT_ID = "your-project-id"
$SERVICE_NAME = "immersive-language-learning"
$REGION = "us-central1"
$MODEL = "gemini-live-2.5-flash-native-audio"
$RECAPTCHA_SITE_KEY = "your-recaptcha-site-key"
$REDIS_URL = "redis://10.0.0.3:6379/0"
$SESSION_TIME_LIMIT = "180"
$GLOBAL_RATE_LIMIT = "100 per 5 minutes"
$PER_USER_RATE_LIMIT = "2 per minute"
$DATASET_ID = "your-dataset-id"
$TABLE_ID = "your-table-id"
$DEMO_NAME = "immersive-language-learning"
$DEV_MODE = "false"

Write-Host "Building frontend..." -ForegroundColor Cyan
npm run build

Write-Host "Deploying $SERVICE_NAME to Cloud Run..." -ForegroundColor Cyan
# NOTE: Ensure you have authenticated with gcloud:
# gcloud auth login
# gcloud config set project $PROJECT_ID

$envVarPairs = @(
    "PROJECT_ID=$PROJECT_ID",
    "LOCATION=$REGION",
    "MODEL=$MODEL",
    "SESSION_TIME_LIMIT=$SESSION_TIME_LIMIT",
    "APP_NAME=$SERVICE_NAME",
    "GLOBAL_RATE_LIMIT=$GLOBAL_RATE_LIMIT",
    "PER_USER_RATE_LIMIT=$PER_USER_RATE_LIMIT",
    "RECAPTCHA_SITE_KEY=$RECAPTCHA_SITE_KEY",
    "REDIS_URL=$REDIS_URL",
    "DEV_MODE=$DEV_MODE",
    "DATASET_ID=$DATASET_ID",
    "TABLE_ID=$TABLE_ID",
    "DEMO_NAME=$DEMO_NAME"
)
$envVarsStr = ($envVarPairs -join ",").ToString()

gcloud run deploy $SERVICE_NAME `
    --source . `
    --region $REGION `
    --allow-unauthenticated `
    --project $PROJECT_ID `
    --network default `
    --subnet default `
    --session-affinity `
    --clear-base-image `
    "--set-env-vars=$envVarsStr"

Write-Host "Deployment command finished." -ForegroundColor Green
