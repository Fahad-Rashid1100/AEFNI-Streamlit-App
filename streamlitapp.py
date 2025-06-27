import streamlit as st
import requests
import json
import uuid
import re

# --- Configuration ---
FASTAPI_BASE_URL = "https://7ngokuvakqinzic4vldalmxyti.srv.us"
API_V2_PREFIX = "/api/v2"
PROJECT_INITIATE_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V2_PREFIX}/project/initiate"
PROJECT_CHAT_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V2_PREFIX}/project/chat"
PROJECT_ANALYZE_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V2_PREFIX}/project/analyze"
PROJECT_GET_SESSION_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V2_PREFIX}/project"
API_V1_PREFIX = "/api/v1"
AEFNE_AUDIT_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V1_PREFIX}/perform_audit"

# --- Session State Initialization ---
def init_session_state():
    if "user_id" not in st.session_state: st.session_state.user_id = f"user_demo_{uuid.uuid4()}"
    if "project_session_id" not in st.session_state: st.session_state.project_session_id = None
    if "current_project_data" not in st.session_state: st.session_state.current_project_data = None
    if "analysis_triggered" not in st.session_state: st.session_state.analysis_triggered = False
    if "audit_triggered" not in st.session_state: st.session_state.audit_triggered = False
    if "show_audit_results" not in st.session_state: st.session_state.show_audit_results = False
    if "version_to_audit" not in st.session_state: st.session_state.version_to_audit = None

init_session_state()

# --- Helper & Formatting ---
def format_brief_for_display(brief: dict) -> str:
    if not brief: return "Error: The compiled brief data is missing."
    currency = brief.get('currency', 'Not Specified')
    md_string = f"""
    #### Project Brief Summary
    Excellent! Based on our conversation, here is my understanding of your project. Please review it before we proceed.

    *   **Project Goal**: {brief.get('project_goal', 'N/A')}
    *   **Location**: {brief.get('project_location_details', 'N/A')}
    *   **Budget**: {brief.get('budget_range_pkr', 'N/A')}
    *   **Currency**: **{currency}**
    """
    return md_string

def reset_app_state():
    user_id = st.session_state.user_id
    keys_to_delete = [key for key in st.session_state.keys() if key != 'user_id']
    for key in keys_to_delete: del st.session_state[key]
    init_session_state()
    st.rerun()

# --- UI Rendering Functions ---
def render_interview_page(project_data):
    st.header("2. Chat with AEFNE's Intake Specialist")
    chat_container = st.container(height=450)
    with chat_container:
        for message in project_data.get("interview_history", []):
            with st.chat_message(message["role"]): st.markdown(message["content"])
        
        # <<< FIX: Display the compiled brief as the final message when interview is complete >>>
        if project_data.get("status") == "interview_complete":
            with st.chat_message("ai", avatar="🤖"):
                st.markdown(format_brief_for_display(project_data.get("compiled_brief")))

    # <<< FIX: Display the correct controls based on the status >>>
    if project_data.get("status") == "interview_in_progress":
        user_input = st.chat_input("Your response to AEFNE...")
        if user_input:
            payload = {"project_session_id": st.session_state.project_session_id, "message": {"role": "user", "content": user_input}}
            headers = {"Authorization": st.session_state.user_id}
            requests.post(PROJECT_CHAT_ENDPOINT, json=payload, headers=headers, timeout=90)
            st.rerun()
    elif project_data.get("status") == "interview_complete":
        st.info("The interview is complete. Review the final brief summary above.", icon="✅")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Proceed to Detailed Financial Analysis", type="primary", use_container_width=True):
                st.session_state.analysis_triggered = True
                st.rerun()
        with col2:
            if st.button("Restart Interview to Refine Details", use_container_width=True):
                payload = {"project_session_id": st.session_state.project_session_id, "message": {"role": "user", "content": "/restart_interview"}}
                headers = {"Authorization": st.session_state.user_id}
                requests.post(PROJECT_CHAT_ENDPOINT, json=payload, headers=headers, timeout=90)
                st.rerun()

def render_boardroom_page(project_data):
    st.header("4. Boardroom: Analysis & Strategy")
    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Financial Viability Analysis")
        analysis_list = project_data.get("analysis_results", [])
        if not analysis_list:
            if project_data.get("status") == "analysis_failed":
                 st.error("The last analysis attempt failed.")
                 st.json(project_data.get("analysis_result", {}))
            else: st.warning("No analysis results found.")
            return

        active_version = project_data.get("active_analysis_version", 1)
        version_summaries = {v["version"]: f"v{v['version']}: {v['summary']}" for v in analysis_list}
        version_options = list(version_summaries.keys())
        try: active_index = version_options.index(active_version)
        except ValueError: active_index = len(version_options) - 1
        
        selected_version = st.selectbox("Select Analysis Version:", options=version_options, format_func=lambda x: version_summaries.get(x, f"Version {x}"), index=active_index)
        analysis_to_display = next((r["result"] for r in analysis_list if r["version"] == selected_version), None)
        
        if not analysis_to_display:
            st.error(f"Could not load data for version {selected_version}."); return
        
        currency_code = analysis_to_display.get("currency", "USD")
        st.metric(f"Projected Revenue ({currency_code})", f"{analysis_to_display.get('calculated_revenue', 0):,.0f}")
        cost_disp = "N/A"
        if analysis_to_display.get("inputs_received"):
             cost_v = analysis_to_display["inputs_received"].get("estimated_total_cost")
             if cost_v is not None: cost_disp = f"{cost_v:,.0f}"
        st.metric(f"AI Estimated Project Cost ({currency_code})", cost_disp)
        st.metric(f"Projected Profit/Loss ({currency_code})", f"{analysis_to_display.get('calculated_profit_loss', 0):,.0f}")
        st.markdown("**AI CFO Strategic Summary:**"); st.markdown(f"> {analysis_to_display.get('summary_text', 'Not available.')}")
        with st.expander("View Full Detailed Report & Logs for this Version"): st.json(analysis_to_display)
        
        st.markdown("---")
        if st.button(f"Perform AI Internal Audit on Version {selected_version}", type="primary"):
            st.session_state.version_to_audit = selected_version
            st.session_state.audit_triggered = True; st.rerun()

    with col2:
        st.subheader("Boardroom Chat")
        chat_container = st.container(height=500)
        with chat_container:
            for message in project_data.get("post_analysis_history", []):
                with st.chat_message(message["role"]): st.markdown(message["content"])
        user_input = st.chat_input("Ask about the analysis or suggest changes...")
        if user_input:
            payload = {"project_session_id": st.session_state.project_session_id, "message": {"role": "user", "content": user_input}}
            headers = {"Authorization": st.session_state.user_id}
            requests.post(PROJECT_CHAT_ENDPOINT, json=payload, headers=headers, timeout=120)
            st.rerun()

# --- Main App Logic ---
st.set_page_config(layout="wide", page_title="AEFNE AI Platform")
st.title("AEFNE AI Platform - Multi-Agent Demo 🚀")

if st.sidebar.button("Start New Project", use_container_width=True):
    reset_app_state()

if st.session_state.project_session_id and not st.session_state.analysis_triggered and not st.session_state.audit_triggered:
    try:
        headers = {"Authorization": st.session_state.user_id}
        response = requests.get(f"{PROJECT_GET_SESSION_ENDPOINT}/{st.session_state.project_session_id}", headers=headers)
        response.raise_for_status()
        st.session_state.current_project_data = response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Could not load project session: {e}"); st.session_state.current_project_data = None

project_data = st.session_state.current_project_data
current_stage = project_data.get("status") if project_data else "initial_form"

# --- Primary Application Router ---
if st.session_state.analysis_triggered:
    st.header("3. AEFNE's AI Team at Work...")
    try:
        with st.spinner("AI agents are collaborating... This may take a few moments."):
            payload = {"project_session_id": st.session_state.project_session_id}
            headers = {"Authorization": st.session_state.user_id}
            response = requests.post(PROJECT_ANALYZE_ENDPOINT, json=payload, headers=headers, timeout=300)
            response.raise_for_status()
    except requests.exceptions.RequestException as e: st.error(f"Analysis Failed: {e}")
    finally: st.session_state.analysis_triggered = False; st.rerun()

elif st.session_state.audit_triggered:
    st.header("5. Performing AI Internal Audit...")
    try:
        with st.spinner("Auditor agents are reviewing the entire workflow..."):
            version_to_audit = st.session_state.get("version_to_audit")
            if not version_to_audit:
                st.error("Error: Could not determine which version to audit.")
            else:
                st.info(f"Auditing Version {version_to_audit}...")
                analysis_list = st.session_state.current_project_data.get("analysis_results", [])
                data_to_audit = next((r["result"] for r in analysis_list if r["version"] == version_to_audit), None)
                if not data_to_audit:
                    st.error(f"Could not find data for version {version_to_audit} to audit.")
                else:
                    pre_proc_data = data_to_audit.get("inputs_received", {})
                    audit_payload = {"project_name": data_to_audit.get("project_name"), "combined_processing_log": data_to_audit.get("processing_log_combined") or data_to_audit.get("processing_log", []), "pre_processing_data": pre_proc_data, "cfo_and_fa_main_output": data_to_audit}
                    if not all(audit_payload.values()): st.error("Cannot perform audit: Key data is missing.")
                    else:
                        audit_response = requests.post(AEFNE_AUDIT_ENDPOINT, json=audit_payload, timeout=180)
                        audit_response.raise_for_status()
                        st.session_state.audit_report_data = audit_response.json()
    except requests.exceptions.RequestException as e: st.error(f"Audit Failed: {e}"); st.session_state.audit_report_data = {"error": str(e)}
    finally: st.session_state.audit_triggered = False; st.session_state.show_audit_results = True; st.rerun()

elif current_stage == "initial_form":
    st.header("1. Submit Your Project Idea")
    with st.form("project_idea_form"):
        project_idea_summary = st.text_area("Brief Project Idea Summary:", height=100, placeholder="e.g., I want to build a small, eco-friendly cafe in Dubai.")
        uploaded_files = st.file_uploader("Upload Docs (Optional)", accept_multiple_files=True)
        if st.form_submit_button("Begin AEFNE Process"):
            if project_idea_summary.strip():
                data_to_send = {'user_brief_json': json.dumps({"project_idea_summary": project_idea_summary})}
                files_to_send = [('files', (file.name, file, file.type)) for file in uploaded_files] if uploaded_files else None
                headers = {"Authorization": st.session_state.user_id}
                with st.spinner("AEFNE is initiating your session..."):
                    response = requests.post(PROJECT_INITIATE_ENDPOINT, data=data_to_send, files=files_to_send, headers=headers, timeout=90)
                st.session_state.project_session_id = response.json().get("project_session_id")
                st.rerun()

elif current_stage in ["interview_in_progress", "interview_complete"]:
    render_interview_page(project_data)

elif current_stage in ["analysis_complete", "analysis_failed"]:
    if st.session_state.get("show_audit_results"):
        st.header("6. AI Internal Audit Report")
        audit_report = st.session_state.get("audit_report_data", {})
        if "error" in audit_report: st.error("Audit process failed."); st.json(audit_report)
        elif audit_report:
            st.success("AI Internal Audit Complete!")
            st.markdown(f"**Project Audited:** {audit_report.get('project_name_audited', 'N/A')}")
            st.subheader("Overall Audit Summary:"); st.markdown(f"> {audit_report.get('overall_audit_summary', 'Not available.')}")
            with st.expander("View Detailed Audit Findings"):
                st.subheader("Log Review Analysis"); st.markdown(audit_report.get('log_review_summary', "Not available."))
                st.subheader("Data Consistency Analysis"); st.markdown(audit_report.get('data_consistency_summary', "Not available."))
        if st.button("Back to Financial Analysis"): st.session_state.show_audit_results = False; st.rerun()
    else:
        render_boardroom_page(project_data)
else:
    st.info("Waiting for project state...")