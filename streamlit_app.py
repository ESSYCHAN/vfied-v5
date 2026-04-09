import json
from pathlib import Path

import streamlit as st

from report_formatter import generate_client_report


st.set_page_config(
    page_title="AI Behaviour Lab",
    layout="wide",
)


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def severity_badge(severity: str) -> str:
    if severity == "HIGH":
        return "🔴 HIGH"
    if severity == "MEDIUM":
        return "🟠 MEDIUM"
    return "🟢 LOW"


def render_header(client_report: dict):
    summary = client_report["executive_summary"]

    st.title("AI Behaviour Lab")
    st.subheader(summary["title"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Overall Risk Score", summary["overall_risk_score"])
    c2.metric("Status", summary["status"])
    c3.metric("Top Finding", summary["key_finding"].split(" in ")[-1].split(" ")[0])

    st.markdown("### Executive Summary")
    st.write(summary["key_finding"])
    st.write(summary["business_impact"])


def render_risk_breakdown(client_report: dict):
    st.markdown("### Risk Breakdown")

    for item in client_report["risk_breakdown"]:
        with st.container(border=True):
            col1, col2 = st.columns([2, 1])
            col1.markdown(f"**{item['family'].replace('_', ' ').title()}**")
            col1.write(item["explanation"])
            col2.markdown(f"**Score:** {item['score']}")
            col2.markdown(f"**Severity:** {severity_badge(item['severity'])}")


def render_failures(client_report: dict):
    st.markdown("### Failure Proof")

    failures = client_report.get("failure_proofs", [])
    if not failures:
        st.success("No high-priority failure examples were captured in this run.")
        return

    for i, failure in enumerate(failures, start=1):
        with st.container(border=True):
            st.markdown(f"**Failure Example {i}**")
            st.markdown("**User Prompt**")
            st.code(failure["prompt"])
            st.markdown("**Model Response**")
            st.write(failure["response"])
            st.markdown(f"**Lambda:** {failure['lambda']}")
            st.markdown(f"**Issue:** {failure['issue']}")
            st.markdown(f"**Risk:** {failure['risk']}")


def render_root_causes(client_report: dict):
    st.markdown("### Root Causes")
    for cause in client_report.get("root_causes", []):
        st.write(f"- {cause}")


def render_recommendations(client_report: dict):
    st.markdown("### Recommendations")

    recs = client_report.get("recommendations", [])
    if not recs:
        st.info("No recommendations available.")
        return

    for i, rec in enumerate(recs, start=1):
        with st.container(border=True):
            st.markdown(f"**Recommendation {i}**")
            st.write(rec)


def render_verdict(client_report: dict):
    st.markdown("### Final Verdict")
    st.warning(client_report["final_verdict"])


def main():
    st.sidebar.header("Load Audit")

    default_path = "reports/tax_audit.json"
    report_path = st.sidebar.text_input("Audit JSON path", value=default_path)

    if not Path(report_path).exists():
        st.error(f"File not found: {report_path}")
        return

    raw_report = load_json(report_path)
    client_report = generate_client_report(raw_report)

    render_header(client_report)
    st.divider()
    render_risk_breakdown(client_report)
    st.divider()
    render_failures(client_report)
    st.divider()
    render_root_causes(client_report)
    st.divider()
    render_recommendations(client_report)
    st.divider()
    render_verdict(client_report)


if __name__ == "__main__":
    main()