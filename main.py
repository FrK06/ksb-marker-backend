import os, json, tempfile, subprocess
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any
from google import genai
from google.genai import types
import pdfplumber
from docx import Document as DocxDocument

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("Environment variable 'GEMINI_API_KEY' is not set")

client_genai = genai.Client(api_key=GEMINI_API_KEY)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class FeedbackRequest(BaseModel):
    results: dict
    feedback_type: str
    learner_name: str = "the learner"

# ── KSB Rubrics ──────────────────────────────────────────────────────────────

DSP_RUBRIC = [
    {"code":"K2","title":"Modern storage/processing/ML methods for organisational impact","pass_criteria":"Describes an infrastructure approach and explains how storage/processing enables analysis and value.","merit_criteria":"Clear trade-offs (cost, scale, governance, latency), realistic technology choices, strong linkage from infrastructure to insights to business impact.","referral_criteria":"Infrastructure and impact link is unclear or incorrect."},
    {"code":"K5","title":"Design & deploy effective data analysis/research techniques","pass_criteria":"Applies appropriate analysis methods to the dataset and relates to business need.","merit_criteria":"Uses a structured approach (EDA → insights → recommendations), strong reasoning, demonstrates repeatable methodology.","referral_criteria":"Analysis is superficial or misaligned; conclusions not supported by evidence."},
    {"code":"K15","title":"Engineering principles for designing/developing new data products","pass_criteria":"Shows basic engineering discipline: clear artefact goal, steps, and evidence of build process.","merit_criteria":"Strong engineering approach: modularity, reproducibility, versioning, clear assumptions, test/validation thinking.","referral_criteria":"Artefact process unclear; poor engineering practice."},
    {"code":"K20","title":"Collect, store, analyse, and visualise data","pass_criteria":"Describes data collection and storage at a basic level; produces a dashboard/report with ≥2 visualisations.","merit_criteria":"Strong end-to-end data story: collection → prep → modelling/metrics → visuals → business decision.","referral_criteria":"Missing visuals / fewer than 2; unclear collection/storage; visuals not explained."},
    {"code":"K22","title":"Relationship between mathematical principles and AI/DS techniques","pass_criteria":"Demonstrates correct use/interpretation of core statistics (distributions, sampling, p-values, confidence).","merit_criteria":"Shows strong statistical reasoning: assumptions, effect size, uncertainty, limitations, correct interpretation tied to business decision-making.","referral_criteria":"Misinterprets statistics, ignores assumptions, or draws invalid conclusions."},
    {"code":"K24","title":"Sources of error and bias (dataset + methods)","pass_criteria":"Identifies at least 2 plausible sources of error/bias and proposes mitigations; applies basic cleaning/prep.","merit_criteria":"Provides structured bias/error analysis and shows evidence of mitigation and impact.","referral_criteria":"Little/no bias discussion; incorrect handling, or no cleaning where required."},
    {"code":"K26","title":"Scientific method, experiment design, hypothesis testing","pass_criteria":"States null and alternative hypotheses, chooses an appropriate test, runs it, and interprets results.","merit_criteria":"Justifies test choice vs alternatives, checks assumptions, includes effect size/CI, and links conclusion to organisational strategy.","referral_criteria":"Hypotheses missing/incorrect; wrong test or invalid interpretation."},
    {"code":"K27","title":"Engineering principles to create instruments/apps for data collection","pass_criteria":"Describes plausible data collection mechanisms and how data quality would be controlled.","merit_criteria":"Details instrumentation design: event schema, validation, monitoring, governance, and how it supports scaling and future ML.","referral_criteria":"Data collection is vague/unrealistic; no thought to instrumentation or quality controls."},
    {"code":"S1","title":"Use applied research & modelling to design/refine storage architectures","pass_criteria":"Proposes a coherent storage architecture and explains how it supports secure/stable/scalable data products.","merit_criteria":"Strong architecture rationale with applied research references, security controls, scaling approach.","referral_criteria":"Architecture is missing or inconsistent; security/stability/scalability not addressed."},
    {"code":"S9","title":"Manipulate, analyse, and visualise complex datasets","pass_criteria":"Demonstrates data manipulation and analysis steps with evidence and sensible visuals.","merit_criteria":"Efficient and accurate transformation pipeline; strong explanation; visuals reveal meaningful patterns.","referral_criteria":"No evidence of manipulation/analysis; results are unreliable or unclear."},
    {"code":"S10","title":"Select datasets and methodologies appropriate to business problem","pass_criteria":"Dataset is relevant to organisation/domain; methodology matches question.","merit_criteria":"Strong justification of dataset and methods; acknowledges constraints and explains why other options were rejected.","referral_criteria":"Dataset irrelevant/unrealistic; methodology mismatched; weak rationale."},
    {"code":"S13","title":"Identify appropriate resources/architectures for computational problem","pass_criteria":"Chooses reasonable tools/platforms and explains why at a basic level.","merit_criteria":"Strong resource selection with cost/performance/security considerations and realistic operational plan.","referral_criteria":"Tools/architecture choice unjustified or inappropriate."},
    {"code":"S17","title":"Implement data curation and data quality controls","pass_criteria":"Includes basic quality controls (schema checks, duplicates, missing values) and documents cleaning steps.","merit_criteria":"Strong data quality approach: validation rules, monitoring, data dictionary, lineage, and repeatability.","referral_criteria":"No curation/quality controls; data quality issues ignored."},
    {"code":"S18","title":"Develop tools that visualise data systems/structures for monitoring/performance","pass_criteria":"Includes an infrastructure diagram and explains how monitoring/performance could be observed.","merit_criteria":"Adds meaningful monitoring view: data pipeline health, latency, freshness, quality KPIs.","referral_criteria":"Diagram missing or not explained; no monitoring/performance thinking."},
    {"code":"S21","title":"Identify and quantify uncertainty in outputs","pass_criteria":"Mentions uncertainty sources and uses at least one way to quantify/express it.","merit_criteria":"Strong uncertainty treatment: effect size + CI, practical significance, sensitivity checks, and limitations.","referral_criteria":"Uncertainty ignored; overconfident claims; no quantification where needed."},
    {"code":"S22","title":"Apply scientific methods through EDA + hypothesis testing for business decisions","pass_criteria":"Shows EDA + hypothesis test and ties outcome to a business decision or strategy implication.","merit_criteria":"Strong decision framing: confirms/contradicts expectations, quantifies impact, and proposes next experiments/actions.","referral_criteria":"No EDA and/or hypothesis testing, or no business decision link."},
    {"code":"S26","title":"Select/apply appropriate AI/DS techniques to solve complex business problems","pass_criteria":"Applies suitable DS techniques for the task and explains rationale.","merit_criteria":"Goes beyond basics appropriately without overcomplicating; evaluates properly.","referral_criteria":"Techniques are inappropriate, misapplied, or create misleading conclusions."},
    {"code":"B3","title":"Integrity: ethical/legal/regulatory compliance; protect personal data","pass_criteria":"Shows GDPR-aware handling: anonymisation/synthetic data rationale, minimal personal data, ethical considerations.","merit_criteria":"Strong compliance-by-design: retention, access controls, lawful basis thinking, and ethical risk mitigations.","referral_criteria":"GDPR/ethics ignored or mishandled."},
    {"code":"B7","title":"Shares best practice in org/community (AI & DS)","pass_criteria":"Reflects on learning and states at least one way to share best practice.","merit_criteria":"Concrete dissemination plan: reusable assets, stakeholder enablement, community contribution.","referral_criteria":"No meaningful reflection or sharing; vague statements only."},
]

MLCC_RUBRIC = [
    {"code":"K1","title":"ML methodologies to meet business objectives","pass_criteria":"States a clear business problem and identifies an appropriate ML approach. Describes why the approach fits the objective at a basic level.","merit_criteria":"Strong problem framing and justification of methodology choices. Includes alternatives considered and a reasoned selection tied to business outcomes.","referral_criteria":"ML approach is unclear or mismatched to objective. Little/no link between model choice and business need."},
    {"code":"K2","title":"Apply modern storage/processing/ML methods for organisational impact","pass_criteria":"Identifies storage/processing choices and explains how they support the workflow. Mentions governance/security at a basic level.","merit_criteria":"Demonstrates an end-to-end data flow with clear rationale (trade-offs: cost, throughput, latency, reliability).","referral_criteria":"Storage/processing decisions are missing, wrong, or unjustified."},
    {"code":"K16","title":"High-performance architectures and effective use","pass_criteria":"Explains CPU vs GPU at a basic level and relates this to training/inference. Includes at least some performance or configuration evidence.","merit_criteria":"Shows informed optimisation decisions (instance selection, profiling, bottlenecks, batch size, mixed precision). Links architecture choices to measured results/costs.","referral_criteria":"No credible understanding of compute options. No evidence of effective use."},
    {"code":"K18","title":"Programming languages and techniques for data engineering","pass_criteria":"Uses appropriate code tools with clear preprocessing steps and documented pipeline stages.","merit_criteria":"Clean structure (modularity, config, logging), good engineering practice (versioning, reproducible runs), robust handling of errors/edge cases.","referral_criteria":"Little/no evidence of data engineering practice. Pipeline is not reproducible."},
    {"code":"K19","title":"Statistical/ML principles and properties","pass_criteria":"Demonstrates basic ML principles: train/val/test split, evaluation metric, and explains overfitting/underfitting.","merit_criteria":"Shows deeper analysis: bias/variance considerations, metric choice justification, calibration/threshold discussion, error analysis.","referral_criteria":"Weak/incorrect ML reasoning (e.g., data leakage, invalid evaluation)."},
    {"code":"K25","title":"ML libraries for commercially beneficial analysis/simulation","pass_criteria":"Uses suitable ML libraries correctly and explains what was used and why. Runs successfully in cloud context.","merit_criteria":"Demonstrates effective library usage (callbacks, checkpoints, experiment tracking, efficient data loaders). Shows awareness of best practices.","referral_criteria":"Library usage is incorrect, undocumented, or fails to run."},
    {"code":"S15","title":"Develop/build/maintain services/platforms delivering AI","pass_criteria":"Produces a working PoC artefact in the cloud (training/inference), with basic deployment/run instructions and evidence.","merit_criteria":"PoC is robust and maintainable: repeatable deployment, clear monitoring/logging, sensible automation.","referral_criteria":"PoC is missing/non-functional, or cannot be reproduced."},
    {"code":"S16","title":"Define requirements and supervise data management infrastructure (cloud)","pass_criteria":"States functional + non-functional requirements and links them to architecture choices. Includes GDPR considerations.","merit_criteria":"Requirements are well-structured and traceable to design decisions. Includes clear mitigations, risk controls.","referral_criteria":"Requirements are absent or not linked to design. GDPR/security largely ignored."},
    {"code":"S19","title":"Use scalable infra / services management to generate solutions","pass_criteria":"Uses cloud resources appropriately and includes some benchmarking with basic cost/performance commentary.","merit_criteria":"Strong benchmarking methodology: repeatable experiments, clear comparison criteria, cost/performance trade-offs.","referral_criteria":"No meaningful benchmarking or scalability discussion."},
    {"code":"S23","title":"Disseminate AI/DS practices and best practice","pass_criteria":"Provides a reflective section describing what would be shared with others.","merit_criteria":"Clear plan for dissemination: playbooks/templates, stakeholder communication, training/enablement, governance alignment.","referral_criteria":"Reflection is missing or superficial."},
    {"code":"B5","title":"Continuous professional development (CPD)","pass_criteria":"Identifies learning undertaken and at least one concrete next step for development.","merit_criteria":"Strong CPD: specific evidence of learning, reflective improvement loop, and a credible plan tied to role/org needs.","referral_criteria":"No CPD evidence, or vague statements with no concrete learning actions or reflection."},
]

AIDI_RUBRIC = [
    {"code":"K1","title":"AI/ML methodologies to meet business objectives","pass_criteria":"Identifies a valid AI/ML method for the product/artefact and links it to the business objective at a basic level.","merit_criteria":"Justifies methodology choices vs alternatives and links to measurable business value.","referral_criteria":"Method choice is unclear/mismatched; weak link to business objective."},
    {"code":"K4","title":"Extract and link data from multiple systems","pass_criteria":"Describes data sources and a plausible approach to extraction/linkage. Mentions identifiers/joins at a basic level.","merit_criteria":"Demonstrates linkage logic, data lineage, and integration risks; shows evidence.","referral_criteria":"Data sources unclear; no credible extraction/linkage approach."},
    {"code":"K5","title":"Design/deploy data analysis & research to meet needs","pass_criteria":"Includes basic analysis/research approach and explains how it informs solution.","merit_criteria":"Strong research/analysis design with traceable insights informing decisions; limitations acknowledged.","referral_criteria":"Little/no research or analysis; recommendations not grounded in evidence."},
    {"code":"K6","title":"Deliver data products using iterative/incremental approaches","pass_criteria":"Describes delivery approach (agile/iterative/stage-gate) and shows a basic plan for iterations.","merit_criteria":"Clear iteration strategy with prioritisation, feedback loops, MVP scope control, and delivery risks managed.","referral_criteria":"No delivery approach or unrealistic plan."},
    {"code":"K8","title":"Interpret organisational policies/standards/guidelines","pass_criteria":"References relevant org policies/standards and applies them to the solution at a basic level.","merit_criteria":"Shows concrete compliance-by-design decisions (access control, retention, risk approvals, SDLC).","referral_criteria":"Policies not addressed, or addressed superficially."},
    {"code":"K9","title":"Legal/ethical/professional/regulatory frameworks","pass_criteria":"Identifies key legal/ethical issues (GDPR, privacy, IP/licensing) and states basic mitigations.","merit_criteria":"Applies frameworks with specificity: lawful basis, DPIA-style risks, safeguards, accountability, auditability.","referral_criteria":"Ignores or misstates major legal/ethical requirements."},
    {"code":"K11","title":"Roles/impact of AI, DS & DE in industry and society","pass_criteria":"Explains at a basic level who does what (AI/DS/DE roles) and why it matters for delivery.","merit_criteria":"Connects roles to lifecycle responsibilities (governance, monitoring, retraining) and real-world impact.","referral_criteria":"No clear understanding of roles or their impact on outcomes."},
    {"code":"K12","title":"Wider social context, ethical issues (automation/misuse)","pass_criteria":"Discusses at least one social/ethical impact relevant to the product.","merit_criteria":"Balanced assessment of harms/benefits, affected groups, and practical mitigations (HITL, transparency).","referral_criteria":"No meaningful social context; ignores foreseeable misuse/harms."},
    {"code":"K21","title":"How AI/DS supports other team members","pass_criteria":"Shows how the solution integrates with stakeholders/teams and supports workflows.","merit_criteria":"Demonstrates collaboration touchpoints (handover, runbook, stakeholder comms, adoption plan).","referral_criteria":"No consideration of team integration."},
    {"code":"K24","title":"Sources of error and bias","pass_criteria":"Identifies likely errors/bias sources and includes at least simple checks or discussion.","merit_criteria":"Provides structured bias/robustness testing, error analysis, and mitigations.","referral_criteria":"No bias/error thinking or major evaluation flaws."},
    {"code":"K29","title":"Accessibility and diverse user needs","pass_criteria":"Mentions accessibility needs and includes basic design considerations.","merit_criteria":"Concrete accessibility plan with testing evidence or checklists, inclusive design decisions, and trade-offs.","referral_criteria":"Accessibility absent or tokenistic."},
    {"code":"S3","title":"Critically evaluate arguments/assumptions/incomplete data; recommend","pass_criteria":"Makes recommendations based on some evidence; acknowledges constraints/assumptions.","merit_criteria":"Strong critical evaluation: compares options, handles uncertainty, justifies recommendations with clear rationale.","referral_criteria":"Recommendations unsupported, or ignores key uncertainties/assumptions."},
    {"code":"S5","title":"Manage expectations & present insight/solutions/findings to stakeholders","pass_criteria":"Identifies stakeholders and communicates findings in a clear, structured way (incl. KPIs).","merit_criteria":"Tailors messaging by audience; includes clear success criteria, risks, and decisions.","referral_criteria":"Stakeholder comms unclear; expectations unmanaged; missing KPIs."},
    {"code":"S6","title":"Provide direction and technical guidance on AI/DS opportunities","pass_criteria":"Offers basic guidance on feasibility, scope, and next steps.","merit_criteria":"Provides actionable roadmap: scaling, resourcing, governance, monitoring, and adoption steps.","referral_criteria":"No credible guidance; next steps vague or unrealistic."},
    {"code":"S25","title":"Programming languages/tools & software development practices","pass_criteria":"Artefact implemented with basic good practice (readme, dependencies, repeatable run, simple tests/logging).","merit_criteria":"Strong engineering discipline: version control evidence, unit tests, modular code, logging, reproducibility.","referral_criteria":"Artefact missing/non-functional, not reproducible, or poor practices."},
    {"code":"S26","title":"Select/apply appropriate AI/DS techniques for complex problems","pass_criteria":"Technique is appropriate for the problem; evaluation uses suitable metrics at a basic level.","merit_criteria":"Strong technique selection with benchmarking, ablation/alternatives, and clear metric justification.","referral_criteria":"Technique poorly chosen or evaluation invalid."},
    {"code":"B3","title":"Integrity: ethical/legal/regulatory; protect data, safety, security","pass_criteria":"Demonstrates awareness and basic safeguards (privacy, security, safe handling).","merit_criteria":"Proactive integrity: clear controls, transparent limitations, responsible AI approach, documented decisions.","referral_criteria":"Neglects protections; risky handling of data/security."},
    {"code":"B4","title":"Initiative and responsibility to overcome challenges","pass_criteria":"Identifies challenges and shows ownership in resolving them (even if partial).","merit_criteria":"Evidence of strong initiative: iterates, documents decisions, learns from failures, adapts scope effectively.","referral_criteria":"Avoids ownership; challenges not addressed."},
    {"code":"B8","title":"Awareness of trends/innovation; uses literature and sources","pass_criteria":"Uses some relevant references (academic/industry) and links them to the project.","merit_criteria":"Strong, current literature + trend awareness; synthesises sources into decisions and business value.","referral_criteria":"Little/no referencing; weak understanding of innovation landscape."},
]

MODULES = {
    "DSP": {"name": "Data Science Principles", "ksbs": DSP_RUBRIC},
    "MLCC": {"name": "Machine Learning Cloud Computing", "ksbs": MLCC_RUBRIC},
    "AIDI": {"name": "AI & Digital Innovation", "ksbs": AIDI_RUBRIC},
}

# ── Document conversion & extraction ─────────────────────────────────────────

def convert_docx_to_pdf(docx_path: str) -> str:
    """
    Convert DOCX to PDF using LibreOffice headless mode.
    Preserves full page layout: images, charts, diagrams, code, tables.
    """
    output_dir = str(Path(docx_path).parent)

    result = subprocess.run(
        [
            "soffice",
            "--headless",
            "--norestore",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            docx_path
        ],
        capture_output=True,
        text=True,
        timeout=120
    )

    if result.returncode != 0:
        raise RuntimeError(f"DOCX to PDF conversion failed: {result.stderr}")

    pdf_path = str(Path(docx_path).with_suffix(".pdf"))

    if not Path(pdf_path).exists():
        raise RuntimeError("PDF file was not created by LibreOffice conversion")

    return pdf_path


def extract_text_from_pdf(path: str) -> str:
    """Extract text from PDF — kept for the feedback endpoint."""
    text_parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n\n".join(text_parts)


def extract_text_from_docx(path: str) -> str:
    """Extract text from DOCX — kept for the feedback endpoint."""
    doc = DocxDocument(path)
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


# ── Grading (multimodal PDF) ─────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a rigorous UK academic assessor evaluating Level 7 apprenticeship coursework against KSB criteria. You must grade fairly but critically — do NOT inflate grades.

You are receiving the student's submission as a PDF document. You can see the FULL document including all text, images, diagrams, charts, tables, code snippets, screenshots, and figures.

CRITICAL RULES:
1. ONLY use evidence from the SUBMISSION DOCUMENT provided
2. NEVER invent quotes, company names, or technical details
3. If evidence is missing, write NOT FOUND
4. When referencing evidence, describe WHERE in the document you found it (section, page, figure)
5. Consider VISUAL evidence — diagrams, charts, screenshots, code — not just written text

EVIDENCE QUALITY RULES — apply these strictly:
6. DEMONSTRATED evidence (code, screenshots, implemented artefacts, real outputs) is stronger than DESCRIBED evidence (plans, proposals, "I would do X")
7. Saying "I would do X in a workplace" is NOT the same as showing you did X — grade what IS shown, not what is promised
8. Synthetic or dummy data is acceptable for academic submissions BUT it limits the strength of evidence for KSBs requiring real-world data manipulation, collection, or stakeholder impact. A synthetic dataset can still demonstrate methodology but should not automatically receive MERIT for complexity or real-world applicability
9. Theoretical designs (e.g. proposed architectures, future plans) without implementation evidence should be graded on the quality of the design rationale, but the lack of implementation should be noted and should generally cap the grade at PASS unless the design is exceptionally well-justified with trade-offs, alternatives considered, and clear technical depth
10. Well-written prose alone does not justify MERIT — MERIT requires genuine depth, critical thinking, and evidence that goes meaningfully beyond the pass criteria

GRADING SCALE — apply conservatively:
- REFERRAL: Pass criteria NOT met (significant gaps, missing or fundamentally wrong evidence)
- PASS: Pass criteria met (basic requirements satisfied, competence demonstrated at a foundational level)
- MERIT: Pass criteria AND Merit criteria SUBSTANTIALLY met with strong, concrete evidence — not just well-articulated descriptions. MERIT should feel genuinely earned, not given because the writing is competent

COMMON GRADE INFLATION TRAPS — avoid these:
- Do not give MERIT just because the report is well-structured or professionally written
- Do not give MERIT for breadth of coverage if the depth is shallow
- Do not treat a plan or proposal as equivalent to a demonstrated implementation
- Do not ignore missing practical evidence (code, tool outputs, real data) when the KSB requires demonstration of a skill
- If the improvements field would be empty or trivial, you are probably grading too generously — every submission has meaningful areas for development"""


def grade_ksb(ksb: dict, pdf_bytes: bytes) -> dict:
    """
    Grade a single KSB by sending the full PDF to Gemini as multimodal input.

    Google docs confirm:
    - Gemini 2.5 Flash supports PDF up to 50MB / 1000 pages (258 tokens/page)
    - PDFs processed with native vision — text + images + diagrams + charts
    - Part.from_bytes(data=pdf_bytes, mime_type='application/pdf') for inline PDF
    - Best practice: place the PDF before the text prompt
    """
    prompt = f"""Evaluate the student's submission (provided as the PDF above) against this KSB criterion.
You must grade fairly but critically. Do NOT inflate grades.

## KSB: {ksb['code']} - {ksb['title']}

| Grade | Criteria |
|-------|----------|
| PASS | {ksb['pass_criteria']} |
| MERIT | {ksb['merit_criteria']} |
| REFERRAL | {ksb['referral_criteria']} |

## YOUR TASK
1. Examine the FULL document including any diagrams, charts, code, screenshots, and tables
2. For each piece of evidence, classify it as:
   - DEMONSTRATED (actually shown: code, outputs, screenshots, implemented artefacts, real results)
   - DESCRIBED (written about: plans, proposals, theoretical designs, "I would do X")
3. Assess pass criteria (MET / NOT MET) — explain why
4. Assess merit criteria (MET / NOT MET) — be strict. MERIT requires concrete depth beyond pass, not just good writing
5. Provide your grade decision with honest rationale
6. Always provide at least 2 genuine, specific improvements — if you cannot think of any, you are grading too generously

Respond with ONLY this JSON:
{{
  "grade": "PASS" or "MERIT" or "REFERRAL",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "pass_criteria_met": true or false,
  "merit_criteria_met": true or false,
  "evidence": ["evidence 1 — state if DEMONSTRATED or DESCRIBED", "evidence 2 — state if DEMONSTRATED or DESCRIBED"],
  "strengths": ["strength 1", "strength 2"],
  "improvements": ["specific improvement 1", "specific improvement 2"],
  "rationale": "2-3 sentence explanation of the grade. If awarding MERIT, explicitly state what concrete evidence elevates it beyond PASS. If awarding PASS, explain what would be needed for MERIT."
}}"""

    pdf_part = types.Part.from_bytes(
        data=pdf_bytes,
        mime_type="application/pdf"
    )

    response = client_genai.models.generate_content(
        model="gemini-2.5-flash",
        contents=[pdf_part, prompt],
        config={"system_instruction": SYSTEM_PROMPT, "temperature": 0}
    )

    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "grade": "REFERRAL",
            "confidence": "LOW",
            "pass_criteria_met": False,
            "merit_criteria_met": False,
            "evidence": [],
            "strengths": [],
            "improvements": ["Could not parse evaluation response"],
            "rationale": "Evaluation failed - please retry"
        }

    result["ksb_code"] = ksb["code"]
    result["ksb_title"] = ksb["title"]
    return result


# ── Harvard Referencing Quality Check ─────────────────────────────────────────

def check_referencing(pdf_bytes: bytes) -> dict:
    """
    Assess the quality of Harvard referencing in the submission.
    Runs once per submission (not per KSB).
    """
    ref_prompt = """Analyse the academic referencing in this student submission (provided as the PDF above).

Assess the following aspects:

1. PRESENCE: Does the report include a references section or bibliography?
2. STYLE: Are references formatted in Harvard style (Author, Year) with in-text citations?
3. IN-TEXT CITATIONS: Are claims, frameworks, and external ideas cited in the body text using (Author, Year) format?
4. REFERENCE LIST: Is there a properly formatted reference list at the end?
5. QUALITY: Are the sources appropriate for Level 7 academic work (peer-reviewed papers, official documentation, established frameworks — not just websites or blogs)?
6. CONSISTENCY: Is the Harvard formatting applied consistently throughout (capitalisation, italics, punctuation, ordering)?
7. COMPLETENESS: Are all in-text citations matched to a reference list entry, and vice versa?

Respond with ONLY this JSON:
{
  "has_references_section": true or false,
  "harvard_style_used": true or false,
  "in_text_citations_present": true or false,
  "in_text_citation_count": number (approximate count of unique in-text citations found),
  "reference_list_count": number (count of entries in the reference list),
  "source_quality": "STRONG" or "ADEQUATE" or "WEAK" or "NONE",
  "consistency": "CONSISTENT" or "MINOR_ISSUES" or "INCONSISTENT" or "NOT_APPLICABLE",
  "issues": ["specific issue 1", "specific issue 2"],
  "overall_rating": "EXCELLENT" or "GOOD" or "ADEQUATE" or "POOR" or "MISSING",
  "summary": "2-3 sentence assessment of the referencing quality"
}"""

    pdf_part = types.Part.from_bytes(
        data=pdf_bytes,
        mime_type="application/pdf"
    )

    try:
        response = client_genai.models.generate_content(
            model="gemini-2.5-flash",
            contents=[pdf_part, ref_prompt],
            config={"system_instruction": "You are an academic quality assessor checking Harvard referencing standards in student submissions. Be thorough and specific.", "temperature": 0}
        )

        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        return json.loads(raw)
    except Exception:
        return {
            "has_references_section": False,
            "harvard_style_used": False,
            "in_text_citations_present": False,
            "in_text_citation_count": 0,
            "reference_list_count": 0,
            "source_quality": "NONE",
            "consistency": "NOT_APPLICABLE",
            "issues": ["Could not assess referencing — evaluation failed"],
            "overall_rating": "MISSING",
            "summary": "Referencing quality could not be assessed."
        }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/modules")
async def get_modules():
    return {k: {"name": v["name"], "ksb_count": len(v["ksbs"])} for k, v in MODULES.items()}

@app.post("/assess")
async def assess(
    file: UploadFile = File(...),
    module: str = Form(...)
):
    if module not in MODULES:
        raise HTTPException(status_code=400, detail=f"Unknown module: {module}")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in [".pdf", ".docx"]:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    pdf_path = None

    try:
        # Step 1: Get canonical PDF
        if suffix == ".docx":
            pdf_path = convert_docx_to_pdf(tmp_path)
        else:
            pdf_path = tmp_path

        # Step 2: Read PDF bytes for Gemini multimodal input
        pdf_bytes = Path(pdf_path).read_bytes()

        if len(pdf_bytes) < 1000:
            raise HTTPException(status_code=400, detail="Document appears to be empty or too short")

        if len(pdf_bytes) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Document exceeds 50MB size limit")

        # Step 3: Grade each KSB with multimodal PDF
        ksbs = MODULES[module]["ksbs"]
        results = []
        for ksb in ksbs:
            result = grade_ksb(ksb, pdf_bytes)
            results.append(result)

        # Step 4: Check Harvard referencing quality (once per submission)
        referencing = check_referencing(pdf_bytes)

    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if pdf_path and pdf_path != tmp_path:
            Path(pdf_path).unlink(missing_ok=True)

    grades = [r["grade"] for r in results]
    merit_count = grades.count("MERIT")
    pass_count = grades.count("PASS")
    referral_count = grades.count("REFERRAL")

    if referral_count > 0:
        overall = "REFERRAL"
    elif merit_count > len(grades) / 2:
        overall = "MERIT"
    else:
        overall = "PASS"

    return {
        "module": module,
        "module_name": MODULES[module]["name"],
        "overall_recommendation": overall,
        "summary": {
            "total": len(results),
            "merit": merit_count,
            "pass": pass_count,
            "referral": referral_count
        },
        "referencing": referencing,
        "results": results
    }


# ─── Feedback endpoint ───────────────────────────────────────────────────────

@app.post("/feedback")
async def generate_feedback(req: FeedbackRequest):
    results = req.results
    feedback_type = req.feedback_type
    learner_name = req.learner_name

    module_name = results.get("module_name", "Unknown Module")
    overall = results.get("overall_recommendation", "UNKNOWN")
    summary = results.get("summary", {})
    ksb_results = results.get("results", [])

    merit_ksbs   = [r for r in ksb_results if r.get("grade") == "MERIT"]
    pass_ksbs    = [r for r in ksb_results if r.get("grade") == "PASS"]
    referral_ksbs = [r for r in ksb_results if r.get("grade") == "REFERRAL"]

    def ksb_lines(ksbs):
        lines = []
        for r in ksbs:
            strengths = "; ".join(r.get("strengths", []))
            improvements = "; ".join(r.get("improvements", []))
            lines.append(
                f"- {r['ksb_code']} ({r['ksb_title']}): {r.get('rationale', '')} "
                f"Strengths: {strengths}. Areas for development: {improvements}."
            )
        return "\n".join(lines) if lines else "None"

    assessment_summary = f"""
Module: {module_name}
Learner: {learner_name}
Overall Recommendation: {overall}
Total KSBs: {summary.get('total', 0)} | Merit: {summary.get('merit', 0)} | Pass: {summary.get('pass', 0)} | Referral: {summary.get('referral', 0)}

MERIT KSBs:
{ksb_lines(merit_ksbs)}

PASS KSBs:
{ksb_lines(pass_ksbs)}

REFERRAL KSBs (requiring further development):
{ksb_lines(referral_ksbs)}
"""

    type_prompts = {
        "formal_letter": f"""
Write a formal feedback letter addressed to {learner_name} regarding their {module_name} coursework assessment (overall: {overall}).

This is a professional letter that a learner could keep as a formal record of their assessment outcome. It should be clear, respectful, and constructive.

STYLE RULES:
- Write in PLAIN TEXT only. No markdown, no bold, no italics, no asterisks, no underscores, no special formatting
- Do NOT use dashes as punctuation. Use commas, full stops, or semicolons instead
- Keep sentences SHORT and clear. Maximum 25 to 30 words per sentence
- Do NOT use excessive superlatives. Keep praise genuine but measured
- Total length: 400 to 600 words. This is a HARD limit

STRUCTURE:

1. SALUTATION AND OUTCOME (2 to 3 sentences). Open with "Dear {learner_name}," then state the module and the overall assessment outcome clearly and directly. Set a respectful tone.

2. STRENGTHS (one paragraph, 4 to 6 sentences). Acknowledge the strongest areas of the submission. Group MERIT and strong PASS KSBs thematically rather than listing each one individually. Reference 2 to 3 KSB codes naturally within the prose. Be specific about what was done well but keep it concise.

3. AREAS FOR DEVELOPMENT (one paragraph, 4 to 6 sentences). Address REFERRAL KSBs sensitively but honestly. Describe the overall theme of what needs improving (e.g. "practical demonstration of your designs") rather than addressing each referred KSB in its own sentence. You may reference 2 to 3 KSB codes in parentheses to support your point but do NOT write "KSB X requires... KSB Y necessitates... KSB Z requires..." as separate sentences. That is a list, not a paragraph. Explain clearly what is needed without being punitive.

4. CLOSING (2 to 3 sentences). Encourage the learner. Express confidence in their ability to improve. Invite them to seek support from their tutor or assessor. Sign off formally with "Kind regards," followed by "The Assessment Team" on the next line.

WHAT TO AVOID:
- Do NOT write a separate paragraph or bullet point for every KSB
- Do NOT include detailed action plans or step by step guidance (that is what the Action Plan feedback type is for)
- Do NOT use headers, sub-headers, or horizontal rules within the letter
- Do NOT exceed 600 words
- Do NOT use "Sincerely," as the sign off. Use "Kind regards," instead
""",
        "developmental": f"""
Write a developmental summary for {learner_name} based on their {module_name} coursework assessment (overall: {overall}).

This document helps the learner understand their professional development trajectory. It identifies patterns across their work, not individual KSB grades. Think of it as a mentor reflecting on the learner's growth and guiding their next steps.

STYLE RULES:
- Write in PLAIN TEXT only. No markdown, no bold, no italics, no asterisks, no underscores, no special formatting
- Do NOT use dashes as punctuation. Use commas, full stops, or semicolons instead
- Keep sentences SHORT and clear. Maximum 25 to 30 words per sentence
- Do NOT use excessive superlatives. Keep the tone supportive but honest
- Total length: 400 to 600 words. This is a HARD limit

STRUCTURE:

1. OVERVIEW (2 to 3 sentences). State the module, overall outcome, and a brief characterisation of the learner's profile (e.g. "Your work shows a strong conceptual thinker who now needs to build confidence in practical execution").

2. STRENGTHS AS A PRACTITIONER (one paragraph, 4 to 6 sentences). Identify the patterns across their strongest KSBs. Do NOT list each KSB separately. Instead, describe 2 to 3 professional qualities the learner has demonstrated (e.g. "systematic thinking", "strong compliance awareness", "clear stakeholder communication"). Reference KSB codes naturally to support the observations.

3. DEVELOPMENT AREAS (one paragraph, 4 to 6 sentences). Identify the patterns across their weakest KSBs. Again, group thematically. Describe the underlying skill gap rather than restating the rubric criteria (e.g. "bridging the gap between planning and execution" rather than "K25, S15, S19 all had TBD tables"). Be constructive and frame development positively.

4. WHAT THIS MEANS FOR YOUR CAREER (one paragraph, 3 to 4 sentences). Connect the strengths and development areas to the learner's broader professional growth. How do the patterns identified relate to their progression as a data scientist, cloud engineer, or AI practitioner? What should they prioritise in their next 3 to 6 months of professional development?

5. CLOSING (1 to 2 sentences). Warm, encouraging, and forward looking.

WHAT TO AVOID:
- Do NOT write a separate paragraph for every KSB
- Do NOT repeat the same point multiple times across different KSBs
- Do NOT include detailed action steps (that is the Action Plan's job)
- Do NOT use headers or sub-headers within the document
- Do NOT exceed 600 words
""",
        "action_plan": f"""
Write a learner action plan for {learner_name} based on their {module_name} coursework assessment (overall: {overall}).

This is a practical, focused document that tells the learner exactly what to do next. It should feel like a coach giving clear instructions, not an examiner writing a report.

STYLE RULES:
- Write in PLAIN TEXT only. No markdown, no bold, no italics, no asterisks, no underscores, no special formatting
- Do NOT use dashes as punctuation. Use commas, full stops, or semicolons instead
- Keep sentences SHORT and clear. Maximum 25 to 30 words per sentence
- Do NOT use excessive superlatives. Keep the tone warm but measured
- Total length: 400 to 600 words. This is a HARD limit

STRUCTURE:

1. CONTEXT (2 to 3 sentences). State the module, overall outcome, and a one sentence summary of the main theme (e.g. "Your Machine Learning Cloud Computing coursework has received an overall outcome of Referral. Your theoretical work is strong but the main gap is practical demonstration."). Do NOT open with "Dear" or any letter-style salutation. This is an action plan, not a letter. Start directly with the context.

2. PRIORITY ACTIONS (this is the core of the plan). Group REFERRAL KSBs thematically rather than listing each one separately. Write 2 to 3 short paragraphs, each covering a theme (e.g. "Executing your PoC and capturing real results" might cover S15, K25, and S19 together). For each theme:
   - State what needs to happen in plain language
   - Give 1 to 2 concrete steps
   - Suggest a realistic timeframe (e.g. "within 2 to 3 weeks")
   Do NOT write sub-bullets, resource lists, or multi-level nested structures. Keep it direct.

3. QUICK WINS (one short paragraph). For the strongest PASS KSBs, suggest 2 to 3 brief enhancements that would push toward Merit. Group them thematically. One sentence per suggestion is enough.

4. CLOSING (1 to 2 sentences). Acknowledge the learner's strengths briefly and encourage them to reach out for support.

WHAT TO AVOID:
- Do NOT write a separate numbered action item for every single KSB
- Do NOT include "Suggested Resources" or "Suggested Approaches" sub-sections
- Do NOT use headers, sub-headers, or horizontal rules
- Do NOT repeat the same improvement point across multiple KSBs (e.g. "populate TBD tables" only needs saying once)
- Do NOT exceed 600 words
""",
        "brief_summary": f"""
Write a brief assessment summary for {learner_name}'s {module_name} coursework (overall: {overall}).

This is the shortest feedback format. It is designed to be shared quickly with the learner or their employer as a snapshot of the assessment outcome. Think of it as an executive summary.

STYLE RULES:
- Write in PLAIN TEXT only. No markdown, no bold, no italics, no asterisks, no underscores, no special formatting
- Do NOT use dashes as punctuation. Use commas, full stops, or semicolons instead
- Keep sentences SHORT and clear. Maximum 25 to 30 words per sentence
- Do NOT use excessive superlatives
- Total length: 150 to 250 words maximum. This is a HARD limit. Brevity is the entire point of this format

STRUCTURE (3 short paragraphs, no headers):

1. OUTCOME (2 to 3 sentences). State the module, overall outcome, and the EXACT grade breakdown from the assessment data. Use the precise numbers provided in the summary section (total, merit, pass, referral). Do NOT guess or calculate these yourself. Copy them directly from the data.

2. KEY THEMES (3 to 4 sentences). One or two sentences on what was done well, grouped thematically. One or two sentences on the main development area, also grouped thematically. Reference 2 to 3 KSB codes at most.

3. NEXT STEP (1 to 2 sentences). A single clear recommendation for what the learner should focus on next.

WHAT TO AVOID:
- Do NOT list individual KSBs with descriptions
- Do NOT include detailed guidance or action steps
- Do NOT exceed 250 words. If the output is longer than 3 short paragraphs, it is too long
""",
        "tag_feedback": f"""
Write feedback for {learner_name} on their {module_name} coursework (overall: {overall}) using the TAG model from QA Apprenticeships.

TAG stands for TELL, ASK, GIVE — but do NOT use these as section headers. Instead, weave them naturally into flowing prose, the way a real Digital Learning Consultant (DLC) would write feedback on a learner's activity submission.

STYLE — this is critical:
- Write in natural, warm, conversational paragraphs — like a real person talking to the learner
- DO NOT write bullet points, numbered lists, or per-KSB breakdowns
- DO NOT exhaustively cover every single KSB — pick the 3–5 most important themes and weave in KSB codes naturally (e.g. "your work on storage architectures (S1) and data quality (S17) showed...")
- Group related KSBs together thematically rather than addressing each one individually
- Total length: approximately 400–600 words (roughly one page). This is a HARD limit — do not exceed it
- Tone: supportive, personal, encouraging — like a coach, not an examiner

BALANCE — this is equally critical:
- TELL should be roughly ONE SHORT PARAGRAPH (4–6 sentences). Do not list every strength — pick the 2–3 most impressive things and praise them specifically. Less is more.
- ASK should be the LONGEST section (roughly 40% of the feedback). This is where the real developmental value is. Write a full paragraph of 3–5 reflective questions woven into natural prose.
- GIVE should be ONE PARAGRAPH of concise, actionable guidance (4–6 sentences). Brief and practical — not a full action plan.
- The greeting and closing are short — 1–2 sentences each.

STRUCTURE (use these as your guide, not as visible headers):

1. GREETING — One warm sentence. If a real name is provided, use "Hi {learner_name}, thank you for your submission..." If the name is "the learner", just write "Hi, thank you for your submission..." without using "the learner" as a name. State the overall outcome simply.

2. TELL — One short paragraph of specific praise. Pick the 2–3 strongest areas, group them thematically, reference evidence. Do NOT individually address every PASS and MERIT KSB. Keep it focused and genuine.

3. ASK — This is the heart of the feedback. Transition naturally into reflective questions. These must be:
   - Specific to the learner's actual work, not generic (e.g. "How could you take your benchmarking plan for CPU vs GPU and run it to capture actual training times and costs?" NOT "What metrics could you capture?")
   - Tied to workplace application (e.g. "How would you present these results to your line manager to justify the infrastructure spend?")
   - A mix of stretch questions for PASS KSBs and gap-identification questions for REFERRAL KSBs
   - Connected to wider skills where natural: literacy (report structure, clarity), numeracy (metrics, cost analysis), digital skills (cloud tooling, dashboards)
   Write 3–5 questions flowing naturally in a paragraph, not as a numbered list.

4. GIVE — One concise paragraph of practical IAG (Information, Advice, Guidance). For REFERRAL KSBs: state briefly what's needed (e.g. "The main thing to focus on is turning your excellent designs into demonstrated evidence — screenshots of executed SageMaker jobs, actual metrics from training runs, and a working code repository"). For the strongest PASS KSBs: one sentence suggesting what would push toward Merit. Keep it brief and actionable.

5. CLOSING — End warmly and personally, like a real DLC would: "Looking forward to seeing your next submission, keep up the great work!" or "I'm really looking forward to seeing these designs come to life in your next iteration." Do NOT end with a generic "Best regards,". Make it feel human. If the name is "the learner", do NOT use it in the closing sentence.

WHAT TO AVOID:
- Do NOT write a structured report with headers, sub-headers, and bullet lists
- Do NOT address every KSB individually — synthesise and group
- Do NOT use phrases like "Regarding K16..." or "For S15..." as paragraph openers
- Do NOT exceed 600 words — brevity is quality
- Do NOT include meta-commentary like "This follows the TAG model..."
- Do NOT let the TELL section dominate — if it's longer than the ASK section, you've got the balance wrong
- Do NOT end with "Best regards," — end with a warm, personalised sentence

FORMATTING AND STYLE RULES:
- Write in PLAIN TEXT only. No markdown, no bold, no italics, no asterisks, no underscores, no special formatting characters whatsoever
- Do NOT use dashes (—, –, -) as punctuation mid-sentence. Use commas, full stops, or semicolons instead
- Do NOT use excessive superlatives. Vary your praise vocabulary and keep it measured. Words like "remarkable", "incredible", "exceptional", "superb", "fantastic" should not all appear in the same piece of feedback. Use 1-2 at most
- Keep sentences SHORT and clear. Maximum 25-30 words per sentence. If a sentence has more than one comma, break it into two sentences
- Write the way a person would speak to someone face to face: clear, direct, and easy to follow
""",
    }

    type_prompt = type_prompts.get(feedback_type, type_prompts["brief_summary"])

    full_prompt = f"""
You are an expert academic assessor writing feedback for an apprenticeship programme.
Based on the following assessment data, {type_prompt}

ASSESSMENT DATA:
{assessment_summary}

Important:
- Write ONLY the feedback document itself — no preamble, no meta-commentary
- Do not include phrases like "Here is the feedback" or "As requested"
- Make it specific to the actual KSB results provided — do not be generic
- Use the learner's name ({learner_name}) naturally throughout. If the name is "the learner", do not write "Dear the learner" or "Hi the learner". Instead use "Dear Learner" or "Hi there" as appropriate for the format
- Write in British English throughout (e.g. organisation not organization, utilisation not utilization, behaviour not behavior, analyse not analyze, colour not color, programme not program, centre not center, defence not defense, practise not practice for the verb)
"""

    try:
        response = client_genai.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
        )
        return {"feedback": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feedback generation failed: {str(e)}")