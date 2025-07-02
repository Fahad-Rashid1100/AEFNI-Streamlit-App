import streamlit as st
import requests
import json
import uuid
import re
import time

# --- Configuration ---
FASTAPI_BASE_URL = "https://7ngokuvakqinzic4vldalmxyti.srv.us"
API_V2_PREFIX = "/api/v2"
API_V1_PREFIX = "/api/v1"
PROJECT_INITIATE_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V2_PREFIX}/project/initiate"
PROJECT_CHAT_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V2_PREFIX}/project/chat"
PROJECT_ANALYZE_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V2_PREFIX}/project/analyze"
PROJECT_LIST_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V2_PREFIX}/projects"
PROJECT_GET_SESSION_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V2_PREFIX}/project"
AEFNE_AUDIT_ENDPOINT = f"{FASTAPI_BASE_URL}{API_V1_PREFIX}/perform_audit"

# --- Session State Management ---
def init_session():
    if "user_id" not in st.session_state: st.session_state.user_id = f"user_demo_{uuid.uuid4()}"
    if "project_session_id" not in st.session_state: st.session_state.project_session_id = None
    if "view" not in st.session_state: st.session_state.view = "form"
    if "last_error" not in st.session_state: st.session_state.last_error = None

def reset_session():
    user_id = st.session_state.user_id
    st.session_state.clear()
    st.session_state.user_id = user_id
    init_session()
    st.rerun()

init_session()

# --- API Communication ---
@st.cache_data(ttl=10) # Cache for 10 seconds to avoid rapid re-fetching
def get_project_list(user_id):
    try:
        headers = {"Authorization": user_id}
        response = requests.get(PROJECT_LIST_ENDPOINT, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json().get("projects", [])
    except requests.exceptions.RequestException as e:
        st.sidebar.error("Could not load projects.")
        print(e)
        return []

def get_session_data(session_id, user_id):
    if not session_id: return None
    try:
        headers = {"Authorization": user_id}
        response = requests.get(f"{PROJECT_GET_SESSION_ENDPOINT}/{session_id}", headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching session data: {e}")
        return None

# --- UI Rendering Functions ---
def render_sidebar(projects):
    st.sidebar.title("AEFNE Projects")
    if st.sidebar.button("Start New Project", use_container_width=True):
        reset_session()
    
    st.sidebar.markdown("---")
    for project in projects:
        if st.sidebar.button(f"{project.get('project_name', 'Untitled')} ({project['status']})", key=project['project_session_id'], use_container_width=True):
            st.session_state.project_session_id = project['project_session_id']
            st.rerun()

def render_form_page():
    st.header("1. Submit Your Project Idea")
    with st.form("project_idea_form"):
        project_idea_summary = st.text_area("Brief Project Idea Summary:", height=100, placeholder="e.g., I want to analyze the STRABAG annual report...")
        uploaded_files = st.file_uploader("Upload Financial Docs (Optional)", accept_multiple_files=True)
        
        if st.form_submit_button("Begin AEFNE Process", type="primary"):
            if not project_idea_summary.strip():
                st.warning("Please provide a project summary.")
                return
            files_to_send = [('files', (f.name, f, f.type)) for f in uploaded_files] if uploaded_files else None
            data_payload = {'user_brief_json': json.dumps({"project_idea_summary": project_idea_summary})}
            headers = {"Authorization": st.session_state.user_id}
            
            with st.spinner("AEFNE is initiating your session..."):
                try:
                    response = requests.post(PROJECT_INITIATE_ENDPOINT, data=data_payload, files=files_to_send, headers=headers, timeout=90)
                    response.raise_for_status()
                    st.session_state.project_session_id = response.json().get("project_session_id")
                    st.rerun()
                except requests.exceptions.RequestException as e:
                    st.error(f"Failed to initiate session: {e}")


def format_brief_for_display(brief: dict, interview_type: str) -> str:
    """Dynamically formats the brief based on the interview type."""
    if not brief: return "Error: The compiled brief data is missing."
    if interview_type == 'analysis':
        return f"""
        #### Analysis Brief Summary
        *   **Target Entity**: {brief.get('target_entity_name', 'N/A')}
        *   **Document Type**: {brief.get('document_type', 'N/A')}
        *   **Primary Focus**: {brief.get('analytical_focus', 'N/A')}
        """
    else:
        return f"""
        #### Project Brief Summary
        *   **Project Goal**: {brief.get('project_goal', 'N/A')}
        *   **Location**: {brief.get('project_location_details', 'N/A')}
        *   **Budget**: {brief.get('budget_range', 'N/A')}
        *   **Currency**: **{brief.get('currency', 'N/A')}**
        *   **Timeline**: {brief.get('project_timeline', 'N/A')}
        """

def render_interview_page(project_data):
    st.header("2. Chat with AEFNE's Intake Specialist")

    if st.session_state.last_error:
        st.error(f"**Previous Analysis Failed:** {st.session_state.last_error}")
        st.session_state.last_error = None # Clear error after showing it

    chat_container = st.container(height=450)
    with chat_container:
        for message in project_data.get("interview_history", []):
            with st.chat_message(message["role"]): st.markdown(message["content"])
        
        if project_data.get("status") == "interview_complete":
            brief = project_data.get("compiled_brief")
            interview_type = project_data.get("interview_type", "creation")
            with st.chat_message("ai", avatar="🤖"):
                st.markdown(format_brief_for_display(brief, interview_type))

    if project_data.get("status") == "interview_in_progress":
        user_input = st.chat_input("Your response to AEFNE...")
        if user_input:
            payload = {"project_session_id": st.session_state.project_session_id, "message": {"role": "user", "content": user_input}}
            requests.post(PROJECT_CHAT_ENDPOINT, json=payload, headers={"Authorization": st.session_state.user_id}, timeout=90)
            st.rerun()
            
    # --- THIS IS THE FIX ---
    # Add the action buttons back for the "interview_complete" state.
    elif project_data.get("status") == "interview_complete":
        st.info("The interview is complete. Please review the summary above.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Looks Good, Proceed to Analysis", type="primary", use_container_width=True):
                st.session_state.analysis_triggered = True
                st.rerun()
        with col2:
            if st.button("🔄 Restart Interview", use_container_width=True):
                payload = {"project_session_id": st.session_state.project_session_id, "message": {"role": "user", "content": "/restart_interview"}}
                requests.post(PROJECT_CHAT_ENDPOINT, json=payload, headers={"Authorization": st.session_state.user_id}, timeout=90)
                st.rerun()

def render_results_page(project_data):
    st.header("4. Boardroom: Analysis & Strategy")
    st.success("Analysis Complete!")

    analysis_list = project_data.get("analysis_results", [])
    if not analysis_list:
        st.warning("No analysis results found."); return

    active_version = project_data.get("active_analysis_version", 1)
    version_summaries = {v["version"]: f"v{v['version']}: {v['summary']}" for v in analysis_list}
    version_options = list(version_summaries.keys())
    try: active_index = version_options.index(active_version)
    except ValueError: active_index = len(version_options) - 1
    
    st.info("The Boardroom Chat can be used to ask 'what-if' questions, which will generate new versions of the analysis.")
    selected_version = st.selectbox(
        "Select Analysis Version to View:",
        options=version_options,
        format_func=lambda x: version_summaries.get(x, f"Version {x}"),
        index=active_index
    )
    
    analysis_to_display = next((r["result"] for r in analysis_list if r["version"] == selected_version), None)
    
    if not analysis_to_display:
        st.error(f"Could not load data for version {selected_version}."); return
    
    inputs_received = analysis_to_display.get("inputs_received", {})
    is_equity_research = "target_entity_name" in inputs_received

    st.subheader(f"AI Strategic Summary (Version {selected_version})")
    st.markdown(f"> {analysis_to_display.get('summary_text', 'Not available.')}")
    st.markdown("---")

    tab_titles = ["Key Findings", "Agent Insights", "Detailed Report", "Boardroom Chat"]
    tab1, tab2, tab3, tab4 = st.tabs(tab_titles)

    if is_equity_research:
        with tab1:
            st.subheader("Key Findings & Ratios")
            findings = analysis_to_display.get("investment_analysis_report", {}).get("key_findings", {})
            st.markdown(f"**Financial Health:** {findings.get('financial_health_summary', 'N/A')}")
            st.markdown(f"**Management Outlook:** {findings.get('management_outlook_summary', 'N/A')}")
            st.subheader("Financial Ratios")
            st.json(analysis_to_display.get("investment_analysis_report", {}).get("financial_ratios", {}))
        
        with tab2:
            st.subheader("Strategic Analysis")
            strat_analysis = analysis_to_display.get("investment_analysis_report", {}).get("strategic_analysis", {})
            st.markdown("**SWOT Analysis**")
            st.json(strat_analysis.get("swot_analysis", {}))
            st.markdown("**Identified Red Flags**")
            for flag in strat_analysis.get("identified_red_flags", []):
                st.warning(f"- {flag}")

        with tab3:
            st.subheader("Full Junior Analyst Report (JSON)")
            st.json(analysis_to_display.get("investment_analysis_report", {}))
            with st.expander("View Original Extracted Financials"):
                st.json(analysis_to_display.get("structured_financial_data", {}))

    else: # Conceptual Project
        # --- THIS IS THE FIX ---
        fa_report = analysis_to_display.get("detailed_financial_analysis", {})
        
        with tab1:
            st.subheader("Key Viability Metrics")
            currency_code = analysis_to_display.get("currency", "USD")
            metrics = fa_report.get("viability_metrics", {})
            
            col1, col2, col3 = st.columns(3)
            with col1:
                # Get the cost from the cash flow statement, which is the TRUE final cost
                cash_flow = fa_report.get("projected_cash_flow_statement", {}).get("annual_breakdown", [])
                cost = abs(cash_flow[0].get('cash_flow')) if cash_flow and cash_flow[0].get('year') == 0 else None
                st.metric(f"AI Estimated Cost ({currency_code})", f"{cost:,.0f}" if cost is not None else "N/A")
                
                revenue = metrics.get('total_projected_revenue')
                st.metric(f"Total Projected Revenue ({currency_code})", f"{revenue:,.0f}" if revenue is not None else "N/A")
            with col2:
                profit = metrics.get('total_projected_profit_loss')
                st.metric(f"Total Projected Profit/Loss ({currency_code})", f"{profit:,.0f}" if profit is not None else "N/A")
                
                npv = metrics.get('npv')
                st.metric(f"Net Present Value (NPV)", f"{npv:,.0f}" if npv is not None else "N/A")
            with col3:
                irr = metrics.get('irr_percentage')
                st.metric("Internal Rate of Return (IRR)", f"{irr:.2%}" if irr is not None else "N/A")
                
                roi = metrics.get('simple_roi_percentage')
                st.metric("Simple ROI", f"{roi:.2%}" if roi is not None else "N/A")
        # --- END OF FIX ---
    
    with tab2:
        st.subheader("AI Agent Insights")
        log_string = "\n".join(analysis_to_display.get("processing_log_combined", []))
        
        with st.expander("AI Cost Estimator's Rationale"):
            cost_rationale_match = re.search(r"Detailed Cost Rationale and Breakdown:(.*)", log_string, re.DOTALL)
            st.markdown(cost_rationale_match.group(1).strip() if cost_rationale_match else "Rationale not found in logs for this workflow.")

        with st.expander("AI Revenue Projector's Rationale"):
            revenue_rationale_match = re.search(r"Detailed Revenue Rationale and Breakdown:(.*)", log_string, re.DOTALL)
            st.markdown(revenue_rationale_match.group(1).strip() if revenue_rationale_match else "Rationale not found in logs for this workflow.")
        
        raw_cfo_output = analysis_to_display.get("raw_llm_output", "")
        observations_match = re.search(r"Key CFO Observations:(.*?)Further Questions/Considerations for Next Phase:", raw_cfo_output, re.DOTALL | re.IGNORECASE)
        if observations_match:
            with st.expander("AI CFO's Key Observations"):
                st.markdown(observations_match.group(1).strip())
    
    with tab3:
        st.subheader("Full Detailed Report (JSON)")
        st.json(analysis_to_display)

    with tab4:
        st.subheader("Chat with Your AI CFO")
        chat_container = st.container(height=400)
        with chat_container:
            for message in project_data.get("post_analysis_history", []):
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
        user_input = st.chat_input("Ask 'what-if' questions to generate a new version...")
        if user_input:
            payload = {"project_session_id": st.session_state.project_session_id, "message": {"role": "user", "content": user_input}}
            requests.post(PROJECT_CHAT_ENDPOINT, json=payload, headers={"Authorization": st.session_state.user_id}, timeout=120)
            st.rerun()

    st.markdown("---")
    if st.button(f"Perform AI Internal Audit on Version {selected_version}", type="primary"):
        st.session_state.version_to_audit = selected_version
        st.session_state.audit_triggered = True
        st.rerun()

def render_audit_page(audit_data):
    st.header("5. AI Internal Audit Report")
    if not audit_data:
        st.error("Audit report data is not available."); return

    if "error" in audit_data:
        st.error("Audit process failed."); st.json(audit_data)
    else:
        st.success("AI Internal Audit Complete!")
        st.markdown(f"**Project Audited:** `{audit_data.get('project_name_audited', 'N/A')}`")
        st.markdown(f"**Audit Timestamp:** `{audit_data.get('audit_timestamp', 'N/A')}`")
        st.subheader("Overall Audit Summary:")
        st.markdown(f"> {audit_data.get('overall_audit_summary', 'Not available.')}")
        
        with st.expander("View Detailed Audit Findings"):
            st.subheader("Log Review Analysis"); st.markdown(audit_data.get('log_review_summary', "Not available."))
            st.subheader("Data Consistency Analysis"); st.markdown(audit_data.get('data_consistency_summary', "Not available."))
    
    if st.button("Back to Analysis Boardroom"):
        st.session_state.show_audit_results = False
        st.rerun()

# --- Main Application Controller ---
st.set_page_config(layout="wide", page_title="AEFNE AI Platform")
st.title("AEFNE AI Platform")

# 1. Always render the sidebar and get the list of projects
projects = get_project_list(st.session_state.user_id)
render_sidebar(projects)

# 2. Fetch the current session data if an ID is set
current_project_data = None
if st.session_state.project_session_id:
    current_project_data = get_session_data(st.session_state.project_session_id, st.session_state.user_id)

# 3. Determine the view based on the current state
view = "form" # Default view
if current_project_data:
    status = current_project_data.get("status")
    if status in ["interview_in_progress", "interview_complete"]:
        view = "interview"
    elif status == "analysis_failed":
        view = "analysis_failed"
    elif status == "analysis_complete":
        view = "analysis"

# Handle action triggers from the previous run
if "analysis_triggered" in st.session_state and st.session_state.analysis_triggered:
    st.session_state.analysis_triggered = False
    st.session_state.view = "analysis_progress"
    st.rerun()
if "audit_triggered" in st.session_state and st.session_state.audit_triggered:
    st.session_state.audit_triggered = False
    st.session_state.view = "audit_progress"
    st.rerun()

# 4. Display the correct view
if view == "form":
    render_form_page()
elif view == "interview":
    render_interview_page(current_project_data)
elif view == "analysis":
    render_results_page(current_project_data)
elif view == "analysis_failed":
    st.error("The previous analysis failed.")
    if st.button("Try Analysis Again", type="primary"):
        st.session_state.analysis_triggered = True
        st.rerun()
elif view == "analysis_progress":
    with st.spinner("AI agents are collaborating..."):
        st.header("3. AEFNE's AI Team at Work...")
    with st.spinner("AI agents are collaborating... This may take a few moments."):
        try:
            payload = {"project_session_id": st.session_state.project_session_id}
            headers = {"Authorization": st.session_state.user_id}
            response = requests.post(PROJECT_ANALYZE_ENDPOINT, json=payload, headers=headers, timeout=300)
            response.raise_for_status()
        except requests.exceptions.RequestException:
            # The backend will have already updated the status to "analysis_failed".
            # We don't need to do anything here except stop the trigger.
            pass
        finally:
            st.session_state.analysis_triggered = False
            st.rerun()
elif st.session_state.view == "audit_progress":
    st.header("5. Performing AI Internal Audit...")
    with st.spinner("Auditor agents are reviewing the entire workflow..."):
        version = st.session_state.get("version_to_audit", 1)
        audit_payload = {
            "project_session_id": st.session_state.project_session_id,
            "version_to_audit": version
        }
        try:
            headers = {"Authorization": st.session_state.user_id}
            response = requests.post(AEFNE_AUDIT_ENDPOINT, json=audit_payload, headers=headers, timeout=180)
            response.raise_for_status()
            st.session_state.audit_report = response.json()
        except requests.exceptions.RequestException as e:
            st.session_state.audit_report = {"error": str(e), "detail": "Failed during audit API call."}
        finally:
            st.session_state.audit_triggered = False
            st.session_state.show_audit_results = True
            st.rerun()