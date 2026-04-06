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
        config={"system_instruction": SYSTEM_PROMPT}
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
            config={"system_instruction": "You are an academic quality assessor checking Harvard referencing standards in student submissions. Be thorough and specific."}
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
Write a formal, professional feedback letter addressed to {learner_name} regarding their {module_name} coursework assessment.
The letter should:
- Open with a formal salutation
- Clearly state the overall assessment outcome ({overall})
- Acknowledge the KSBs where merit was demonstrated, with specific praise
- Address KSBs where a pass was achieved, noting solid performance
- Sensitively but clearly explain any KSBs requiring further development (referrals), with specific guidance
- Close with an encouraging and professional sign-off
- Be written in formal academic/professional English
- Be detailed and personalised — avoid generic phrases
""",
        "developmental": f"""
Write a detailed developmental summary for {learner_name} based on their {module_name} coursework assessment.
The summary should:
- Begin with an overview of overall performance ({overall})
- Highlight key strengths demonstrated across the KSBs in detail
- Identify clear patterns in areas requiring development
- Provide specific, constructive and actionable developmental feedback
- Be written in a supportive, professional tone
- Be structured with clear sections (e.g. Overview, Strengths, Areas for Development)
- Be detailed enough to be genuinely useful for the learner's professional development
""",
        "action_plan": f"""
Write a detailed, structured learner action plan for {learner_name} based on their {module_name} coursework assessment (overall: {overall}).
The action plan should:
- Begin with a brief context statement about the assessment
- For each KSB that received REFERRAL, provide a specific numbered action item with:
  * What needs to be improved
  * Specific steps the learner should take
  * Suggested resources or approaches
  * A suggested timeframe (e.g. within 2 weeks, within 1 month)
- For PASS KSBs, suggest one enhancement action to push toward merit level
- Close with a motivating statement about next steps
- Be practical, specific and achievable
""",
        "brief_summary": f"""
Write a concise but comprehensive assessment summary for {learner_name}'s {module_name} coursework.
The summary should:
- Be no longer than 3-4 paragraphs
- State the overall outcome ({overall}) clearly in the first sentence
- Summarise the key strengths briefly
- Summarise the key areas for development briefly
- End with a clear recommendation or next step
- Be written in plain, professional English suitable for sharing with the learner
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
- Use the learner's name ({learner_name}) naturally throughout
"""

    try:
        response = client_genai.models.generate_content(
            model="gemini-2.5-flash",
            contents=full_prompt,
        )
        return {"feedback": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Feedback generation failed: {str(e)}")