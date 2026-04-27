# KSB Marker Target GCP Architecture

**Status:** Target architecture, not current deployed state  
**Scope:** KSB Marker platform on Google Cloud Platform  
**Purpose:** Explain the intended production-grade architecture for secure, asynchronous KSB assessment processing.

---

## 1. Important status note

This document describes the **target platform architecture** for KSB Marker.

The current deployed prototype is closer to:

```mermaid
flowchart LR
    F[Firebase-hosted frontend] --> A[Cloud Run FastAPI backend]
    A --> G[Gemini via API key]
    A --> R[Direct response to browser]
```

The target architecture moves the platform to:

- Firebase Authentication with backend token validation.
- Cloud Run API and separate Cloud Run Worker services.
- Cloud Tasks for asynchronous assessment processing.
- Cloud Storage for uploaded and converted documents.
- Firestore for assessment jobs, assessment records, progress, results, and audit events.
- Vertex AI Gemini for enterprise-governed multimodal model calls.
- Per-KSB checkpointing so failed retries do not rerun the whole assessment.
- Processing leases and heartbeats so jobs do not get stuck.
- Dynamic progress messaging rather than fixed completion-time promises.
- Separated audit metadata and raw model/provenance artefacts.

---

## 2. Target sequence diagram

```mermaid
sequenceDiagram
    autonumber

    actor U as DLC
    participant F as Frontend
    participant A as Cloud Run API<br/>(FastAPI)
    participant FB as Firebase Admin SDK
    participant GCS as Cloud Storage
    participant FS as Firestore
    participant T as Cloud Tasks
    participant W as Cloud Run Worker
    participant V as Vertex AI Gemini

    Note over U,W: Submission phase

    U->>F: Upload DOCX/PDF and select learner/module
    F->>A: POST /assessment-jobs<br/>Bearer token + file + learner_id + module_code

    A->>FB: verify_id_token()
    alt Token invalid
        FB-->>A: Invalid token
        A-->>F: 401 Unauthorized
        F-->>U: Authentication error
    else Token valid
        FB-->>A: caller uid, email, role
        A->>A: Validate role + learner/module scope
        A->>GCS: Upload source file<br/>gs://bucket/jobs/{job_id}/source
        A->>FS: Create AssessmentJob<br/>status=queued<br/>payload_version<br/>api_version<br/>queued_at
        A->>T: Create HTTP task with OIDC token<br/>{assessment_job_id, payload_version}
        A-->>F: 202 Accepted<br/>{assessment_job_id, status: queued}
        F-->>U: Assessment queued<br/>Safe to close tab and return later
    end

    Note over T,W: Async processing phase

    T->>W: POST /process-assessment-job<br/>OIDC token + job payload
    W->>W: Verify OIDC token and payload_version
    W->>FS: Read AssessmentJob

    alt Job already completed/failed/cancelled
        W-->>T: 200 OK no work
    else Job available or stale-processing
        W->>FS: Atomic transaction<br/>claim queued/stale-processing → processing<br/>set lease_until<br/>increment attempt_count
        W->>GCS: Download source file
        W->>W: Convert DOCX to PDF if required
        W->>FS: Load module rubric and prompt version

        loop For each incomplete KSB
            W->>V: grade_ksb(PDF, KSB criteria)
            alt Transient Vertex error
                W->>W: Internal retry with exponential backoff
            else Success
                V-->>W: Structured KSBResult
                W->>W: Apply borderline safety checks
                W->>FS: Checkpoint KSBResult<br/>update progress<br/>completed_ksbs / total_ksbs
            end
        end

        W->>V: check_referencing(PDF)
        V-->>W: ReferencingResult
        W->>FS: Save referencing result

        W->>V: synthesise_overall_evaluation(...)
        alt Synthesis unavailable
            W->>W: Create fallback OverallEvaluation<br/>synthesis_failed=true
        else Success
            V-->>W: OverallEvaluation
        end

        W->>FS: Write AssessmentRecord<br/>id = assessment_{job_id}<br/>full result + provenance
        W->>FS: Atomic transaction<br/>result_write_committed=true<br/>status=completed<br/>terminal_outcome=completed
        W->>FS: Write audit event<br/>action=assessment.created
        W-->>T: 200 OK
    end

    Note over F,A: Polling phase

    loop Poll every 5s, then back off
        F->>A: GET /assessment-jobs/{id}
        A->>FB: verify_id_token()
        A->>FS: Read job status
        FS-->>A: status, progress, assessment_id
        A-->>F: status payload
    end

    Note over F,U: Completion

    F->>F: status=completed → navigate
    F->>A: GET /assessments/{assessment_id}
    A->>FB: verify_id_token()
    A->>FS: Read AssessmentRecord
    FS-->>A: Full assessment record
    A-->>F: KSB results + overall evaluation + feedback data
    F->>U: Render assessment detail page
```

---

## 3. Target platform services

```mermaid
flowchart TB

subgraph USERS[Users]
    DLC[DLC / Tutor]
    Manager[Delivery Lead / Manager]
    Quality[Quality / Governance Team]
    Admin[Platform Admin]
end

subgraph FRONTEND[Frontend]
    Hosting[Firebase Hosting<br/>React platform]
    Auth[Firebase Authentication<br/>email login now<br/>future SSO/MFA]
end

subgraph API[API Layer]
    CloudRunAPI[Cloud Run API<br/>FastAPI<br/>public authenticated endpoints]
    AdminSDK[Firebase Admin SDK<br/>ID token validation]
end

subgraph ASYNC[Async Processing]
    Tasks[Cloud Tasks<br/>OIDC-authenticated task dispatch]
    Worker[Cloud Run Worker<br/>private task endpoint<br/>document processing + AI calls]
end

subgraph DATA[Data Layer]
    GCS[Cloud Storage<br/>source DOCX/PDF<br/>converted PDF<br/>restricted artefacts]
    Firestore[Firestore<br/>jobs, progress, results<br/>roles, audit events]
    RawStore[Restricted raw artefact store<br/>raw model responses<br/>debug/provenance only]
end

subgraph AI[AI Evaluation]
    Vertex[Vertex AI Gemini<br/>multimodal PDF analysis]
    Rubrics[Versioned rubrics/prompts<br/>DSP, MLCC, AIDI]
end

subgraph GOV[Governance and Operations]
    Logs[Cloud Logging]
    Monitoring[Cloud Monitoring]
    Errors[Error Reporting]
    Audit[Cloud Audit Logs]
    Budgets[Billing Budgets and Alerts]
    IAM[IAM service accounts<br/>least privilege]
    Secrets[Secret Manager]
end

DLC --> Hosting
Manager --> Hosting
Quality --> Hosting
Admin --> Hosting

Hosting --> Auth
Hosting --> CloudRunAPI
CloudRunAPI --> AdminSDK
CloudRunAPI --> Firestore
CloudRunAPI --> GCS
CloudRunAPI --> Tasks
Tasks --> Worker
Worker --> GCS
Worker --> Firestore
Worker --> Vertex
Worker --> Rubrics
Worker --> RawStore

CloudRunAPI --> Logs
Worker --> Logs
Logs --> Errors
CloudRunAPI --> Monitoring
Worker --> Monitoring
Firestore --> Audit
IAM --> Audit
Vertex --> Budgets
CloudRunAPI --> IAM
Worker --> IAM
CloudRunAPI --> Secrets
Worker --> Secrets
```

---

## 4. Key design decisions

### 4.1 Asynchronous assessment processing

The frontend must not wait for the full KSB marking process inside one long HTTP request.

Instead:

1. The API creates an assessment job.
2. The file is uploaded to Cloud Storage.
3. The job is stored in Firestore as `queued`.
4. Cloud Tasks invokes the worker.
5. The frontend polls job status until completion.

This directly reduces the risk of browser-side `Failed to fetch` errors.

---

### 4.2 Per-KSB checkpointing

Each KSB result should be written to Firestore as soon as it is completed.

This prevents a retry from repeating all model calls if a later KSB fails.

Recommended structure:

```text
assessment_jobs/{job_id}/ksb_results/{ksb_code}
```

Each checkpoint should include:

- `ksb_code`
- `grade`
- `confidence`
- `pass_criteria_met`
- `merit_criteria_met`
- `evidence`
- `strengths`
- `improvements`
- `rationale`
- `borderline_flag`
- `borderline_reason`
- `model_name`
- `prompt_version`
- `rubric_version`
- `completed_at`

The job document should track:

- `total_ksbs`
- `completed_ksbs`
- `failed_ksbs`
- `progress_percent`
- `current_stage`

---

### 4.3 Processing leases and heartbeats

A worker may crash after claiming a job. To avoid jobs becoming stuck forever in `processing`, each processing claim should use a lease.

Recommended fields:

```text
status: queued | processing | completed | failed | cancelled
attempt_count: number
processing_started_at: timestamp
lease_until: timestamp
last_heartbeat_at: timestamp
worker_id: string
terminal_outcome: completed | failed | cancelled | null
```

A worker can claim a job if:

```text
status == queued
OR
status == processing AND lease_until < now()
```

The worker should periodically update:

```text
last_heartbeat_at = now()
lease_until = now() + lease_duration
```

---

### 4.4 Dynamic user-facing progress messaging

Do not hardcode a fixed estimate such as `4-6 minutes`.

Preferred messages:

```text
Assessment queued. You can close this tab and return later.
```

```text
Processing report. Progress: 8 of 19 KSBs completed.
```

```text
Finalising referencing and overall evaluation.
```

If an estimate is shown, it should be calculated from:

- module selected
- number of KSBs
- file size
- historical average duration
- current retry state

---

### 4.5 Separation of audit metadata and raw model outputs

Audit events should remain lightweight and governance-focused.

Recommended audit event fields:

```text
audit_events/{event_id}
- actor_uid
- actor_email
- action
- assessment_id
- job_id
- timestamp
- api_version
- worker_version
- model_name
- prompt_version
- rubric_version
- outcome
- error_summary
```

Raw model responses should not be casually embedded inside audit metadata because they may include learner evidence or sensitive report content.

If raw model outputs are retained, store them separately with tighter access controls and retention rules:

```text
assessment_raw_outputs/{assessment_id}/ksb/{ksb_code}
```

or:

```text
gs://restricted-ksb-marker-provenance/{assessment_id}/raw_outputs.json
```

Access should be restricted to admin/debug roles only.

---

## 5. Recommended API endpoints

### Public authenticated API

```text
POST /assessment-jobs
GET  /assessment-jobs/{job_id}
GET  /assessments/{assessment_id}
POST /feedback
GET  /modules
GET  /health
```

### Worker-only API

```text
POST /process-assessment-job
```

The worker endpoint should only accept requests from Cloud Tasks using an OIDC token from the approved service account.

---

## 6. Firestore collections

Recommended initial Firestore layout:

```text
users/{uid}
roles/{uid}
learners/{learner_id}
assessment_jobs/{job_id}
assessment_jobs/{job_id}/ksb_results/{ksb_code}
assessments/{assessment_id}
audit_events/{event_id}
module_rubrics/{module_code}
assessment_raw_outputs/{assessment_id}/...
```

---

## 7. Why this architecture matters

This architecture makes KSB Marker suitable for an internal QA platform because it provides:

- safer authentication and role validation;
- better resilience for long-running document processing;
- reduced risk of frontend timeouts;
- recovery from duplicate task delivery or worker crashes;
- auditability for quality and governance teams;
- controlled use of Vertex AI through GCP IAM;
- clearer separation between user-facing results, operational logs, audit events, and raw debug/provenance artefacts.

---

## 8. Implementation sequence

Recommended order:

1. Add Firebase Admin token validation to the API.
2. Add Firestore `assessment_jobs` and `assessments` collections.
3. Add Cloud Storage upload for source documents.
4. Add `POST /assessment-jobs` and `GET /assessment-jobs/{id}`.
5. Add Cloud Tasks and the worker endpoint.
6. Move the current synchronous assessment logic into the worker.
7. Add per-KSB checkpointing.
8. Add processing leases and heartbeats.
9. Switch Gemini access from direct API key to Vertex AI with a Cloud Run service account.
10. Add audit events, provenance, and restricted raw-output storage.
11. Update frontend polling and assessment detail pages.
12. Add monitoring, budget alerts, and error reporting.
