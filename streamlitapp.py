# streamlit_app.py
import streamlit as st
import requests
import json
import time
import datetime # For potential use, though backend handles audit timestamp
import uuid # Import uuid to generate session IDs on the client side

# --- Configuration ---
FASTAPI_BASE_URL = "https://7ngokuvakqinzic4vldalmxyti.srv.us/api/v1"
INTERVIEW_INITIATE_ENDPOINT = f"{FASTAPI_BASE_URL}/interview/initiate"
INTERVIEW_SEND_MESSAGE_ENDPOINT = f"{FASTAPI_BASE_URL}/interview/send_message"
AEFNE_MAIN_ANALYSIS_ENDPOINT = f"{FASTAPI_BASE_URL}/initiate_project_analysis"
AEFNE_AUDIT_ENDPOINT = f"{FASTAPI_BASE_URL}/perform_audit"
FILE_UPLOAD_ENDPOINT = f"{FASTAPI_BASE_URL}/upload_files/"

# --- Initialize Session State (COMPLETE AND CORRECTED) ---
if 'stage' not in st.session_state: 
    st.session_state.stage = "initial_form"
if 'chat_session_id' not in st.session_state: 
    st.session_state.chat_session_id = None
if 'chat_history' not in st.session_state: 
    st.session_state.chat_history = []
if 'interview_active' not in st.session_state: 
    st.session_state.interview_active = False
if 'final_brief_for_analysis' not in st.session_state: 
    st.session_state.final_brief_for_analysis = None
if 'analysis_results' not in st.session_state: 
    st.session_state.analysis_results = None
if 'initial_form_data' not in st.session_state: # Ensured this is present
    st.session_state.initial_form_data = {}
if 'has_existing_files_checked' not in st.session_state: 
    st.session_state.has_existing_files_checked = False
if 'payload_for_main_analysis_rerun' not in st.session_state: 
    st.session_state.payload_for_main_analysis_rerun = None
if 'audit_report_data' not in st.session_state: 
    st.session_state.audit_report_data = None
if 'uploaded_files_info' not in st.session_state: st.session_state.uploaded_files_info = None
if 'project_currency' not in st.session_state: st.session_state.project_currency = "USD"
# --- END OF SESSION STATE INITIALIZATION ---


# --- Helper Functions ---
def start_new_project_process(initial_brief_payload, uploaded_files_list):
    # Step 1: Generate a NEW session_id for this new project run
    session_id = str(uuid.uuid4())
    st.session_state.chat_session_id = session_id
    st.session_state.project_currency = initial_brief_payload.get("currency", "USD") # Store currency
    
    # Step 2: Upload files if they exist, using the new session_id
    if uploaded_files_list:
        try:
            with st.spinner(f"Uploading {len(uploaded_files_list)} file(s)..."):
                # Prepare files for multipart upload
                files_to_upload = [('files', (file.name, file, file.type)) for file in uploaded_files_list]
                
                response_upload = requests.post(
                    FILE_UPLOAD_ENDPOINT,
                    data={'session_id': session_id},
                    files=files_to_upload,
                    timeout=60
                )
                response_upload.raise_for_status()
            st.session_state.uploaded_files_info = response_upload.json()
            st.success("Files uploaded successfully!")
            time.sleep(1) # Give user time to see success message
        except Exception as e:
            st.error(f"File Upload Failed: {e}. Please try again.")
            st.session_state.chat_session_id = None # Invalidate session on failure
            st.session_state.stage = "initial_form"
            st.rerun()
            return # IMPORTANT: Stop if upload fails

    # Step 3: Initiate the interview
    try:
        with st.spinner("AEFNE is preparing for the interview..."):
            # We now pass the session_id to the initiate endpoint.
            # This requires a backend change to the /interview/initiate endpoint.
            payload_for_initiate = {
                "session_id": session_id,
                "user_brief": initial_brief_payload
            }
            # Note: You must update the /interview/initiate endpoint to accept this payload.
            response = requests.post(INTERVIEW_INITIATE_ENDPOINT, json=payload_for_initiate, timeout=45)
            response.raise_for_status()
        
        data = response.json()
        st.session_state.chat_session_id = data.get("session_id", session_id)
        st.session_state.chat_history = [{"role": "assistant", "content": data.get("ai_response")}]
        st.session_state.interview_active = data.get("conversation_is_active", True)
        st.session_state.stage = "interview"
        st.rerun()
    except Exception as e:
        st.error(f"API Error (Initiate Interview): {e}")
        st.session_state.stage = "initial_form"

def send_chat_message(user_input_text):
    if st.session_state.chat_session_id and user_input_text:
        st.session_state.chat_history.append({"role": "user", "content": user_input_text})
        payload = {"session_id": st.session_state.chat_session_id, "prompt": user_input_text}
        try:
            response = requests.post(INTERVIEW_SEND_MESSAGE_ENDPOINT, json=payload, timeout=60)
            response.raise_for_status()
            data = response.json()
            st.session_state.chat_history.append({"role": "assistant", "content": data.get("ai_response")})
            st.session_state.interview_active = data.get("conversation_is_active", True)
            if not st.session_state.interview_active and data.get("final_brief_if_complete"):
                st.session_state.final_brief_for_analysis = data.get("final_brief_if_complete")
                st.session_state.stage = "review_brief"
            st.rerun()
        except requests.exceptions.RequestException as e: st.error(f"API Error (Send Message): {e}")
        except json.JSONDecodeError as je: st.error(f"API Response Error (Send Message). Raw: {je.doc[:200]}...")

def trigger_main_analysis_from_interview():
    if st.session_state.final_brief_for_analysis and st.session_state.chat_session_id:
        enriched_brief = st.session_state.final_brief_for_analysis
        
        # This part constructs the rich text summary for the UserBrief
        summary_parts = [
            f"Initial Idea: {enriched_brief.get('project_idea_summary_initial', 'N/A')}",
            f"Goal: {enriched_brief.get('project_goal', 'N/A')}",
            f"Budget: {enriched_brief.get('budget_range_pkr', 'N/A')}",
            f"Location: {enriched_brief.get('project_location_details', 'N/A')}",
            f"Project Currency: The currency for all financial figures is {enriched_brief.get('currency', 'USD')}."
            # The file summary is now part of the EnrichedUserProjectBrief schema
            # But for the handoff, we can just pass the references directly.
            # The DataStructurerForCFO will use the references.
        ]
        adapted_summary = ". ".join(summary_parts)
        if len(adapted_summary) > 1500: adapted_summary = adapted_summary[:1497] + "..."
        
        # --- THIS IS THE CORRECT, FINAL PAYLOAD STRUCTURE ---
        payload = {
            "session_id": st.session_state.chat_session_id,
            "user_brief": {
                "project_idea_summary": adapted_summary,
                "has_existing_files": enriched_brief.get("has_existing_files_confirmed", False),
                "existing_files_description": enriched_brief.get("existing_files_description_updated"),
            "currency": enriched_brief.get("currency", "USD") # Pass currency along
        },
        "file_references": enriched_brief.get("uploaded_file_references", [])
    }
        
        # Store this complete payload and change the stage
        st.session_state.payload_for_main_analysis_rerun = payload
        st.session_state.stage = "analysis_progress"
        st.rerun()
    else:
        st.error("Final brief or Session ID is missing. Cannot proceed.")
        st.session_state.stage = "review_brief" # Stay on the review page

def trigger_main_analysis(payload):
    # This function now correctly receives the fully formed payload
    st.session_state.payload_for_main_analysis = payload
    st.session_state.stage = "analysis_progress"
    st.rerun()

def trigger_audit():
    if st.session_state.analysis_results and "error" not in st.session_state.analysis_results:
        st.session_state.stage = "performing_audit"
        st.rerun()
    else:
        st.error("Cannot perform audit: Main financial analysis was not successful or results are missing.")

def reset_app_state():
    st.session_state.stage = "initial_form"
    st.session_state.chat_session_id = None; st.session_state.chat_history = []
    st.session_state.interview_active = False; st.session_state.final_brief_for_analysis = None
    st.session_state.analysis_results = None; st.session_state.initial_form_data = {}
    st.session_state.has_existing_files_checked = False
    st.session_state.payload_for_main_analysis_rerun = None
    st.session_state.audit_report_data = None # Reset audit data too
    st.session_state.uploaded_files_info = None
    st.rerun()

# --- Streamlit UI ---
st.set_page_config(layout="wide", page_title="AEFNE AI Platform Demo")
st.title("AEFNE AI Platform - Multi-Agent Demo 🚀")

# ============================ STAGE 1: INITIAL FORM ============================
if st.session_state.stage == "initial_form":
    st.header("1. Submit Your Project for AEFNE Analysis")
    st.markdown("Provide an initial summary and any relevant files (images, documents). AEFNE will analyze them and then start an interactive interview.")

    with st.form("project_idea_form_with_files_v3"):
        project_idea_summary = st.text_area(
            "Brief Project Idea Summary:",
            height=100,
            placeholder="e.g., I want to build a small, eco-friendly cafe in a suburban area. I have a sketch of the floor plan."
        )
        
        # <<< NEW CURRENCY FIELD >>>
        currency = st.selectbox("Select Project Currency", ["USD", "PKR", "AED", "SAR", "EUR"], index=0)

        uploaded_files = st.file_uploader(
            "Upload Documents or Images (Optional)",
            accept_multiple_files=True,
            type=['png', 'jpg', 'jpeg', 'pdf', 'txt']
        )
        
        submitted_form = st.form_submit_button("Begin AEFNE Process")

        if submitted_form:
            if not project_idea_summary.strip():
                st.error("Please provide a Project Idea Summary.")
            else:
                # Prepare the initial brief payload
                brief = {
                    "project_idea_summary": project_idea_summary,
                    "has_existing_files": bool(uploaded_files),
                    "existing_files_description": f"{len(uploaded_files)} files uploaded: " + ", ".join([f.name for f in uploaded_files]) if uploaded_files else "No files uploaded.",
                    "currency": currency # <<< ADD CURRENCY TO PAYLOAD
                }
                st.session_state.initial_form_data = brief
                start_new_project_process(brief, uploaded_files)


# ============================ STAGE 2: INTERVIEW CHAT ============================
elif st.session_state.stage == "interview":
    st.header("2. Chat with AEFNE's Intake Specialist")
    st.markdown("Let's discuss your project. Type `/analyze` when ready, or AEFNE will suggest.")
    chat_container = st.container(height=400); 
    with chat_container:
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]): st.markdown(message["content"])
    if st.session_state.interview_active:
        user_input = st.chat_input("Your response to AEFNE...")
        if user_input: send_chat_message(user_input)

# ============================ STAGE 3: REVIEW BRIEF ============================
elif st.session_state.stage == "review_brief":
    st.header("Interview Complete!")
    st.markdown("AEFNE has compiled this understanding of your project:")
    if st.session_state.final_brief_for_analysis:
        with st.expander("View Compiled Interview Brief", expanded=True): st.json(st.session_state.final_brief_for_analysis)
        st.markdown("---")
        col1, col2, col3 = st.columns([2,2,1])
        with col1:
            if st.button("Proceed to Detailed Financial Analysis", type="primary", use_container_width=True): trigger_main_analysis_from_interview() 
        with col2:
            if st.button("Restart Interview (Refine Details)", use_container_width=True):
                st.session_state.chat_history = []; st.session_state.final_brief_for_analysis = None; st.session_state.interview_active = False
                initiate_interview(st.session_state.initial_form_data)
        with col3:
            if st.button("Start Over (New Project)", use_container_width=True): reset_app_state()
    else:
        st.error("Could not retrieve compiled brief."); 
        if st.button("Try Interview Again"): initiate_interview(st.session_state.initial_form_data)
        if st.button("Start Over (New Project)"): reset_app_state()

# ============================ STAGE 4: ANALYSIS PROGRESS (Normal & Override) ============================
elif st.session_state.stage in ["analysis_progress", "analysis_progress_from_override"]: # Combined logic
    progress_bar_text_prefix = "Main Analysis: "
    if st.session_state.stage == "analysis_progress_from_override": # This stage name is not used anymore with simplified logic
        # This if-condition might not be hit if we simplify trigger functions.
        # For safety, keeping it, but trigger_main_analysis_from_override now sets stage to 'analysis_progress'
        st.header("3b. AEFNE AI at Work (with Demo Override Parameters)")
        st.info("Re-running analysis with manually provided 'VIAB-equivalent' parameters...")
        progress_bar_text_prefix = "Override Analysis Re-run: "
    else: # analysis_progress
        st.header("3. AEFNE's AI CFO & Analysts at Work...")
        st.info("Processing with details from interview. This may take a few moments...")
    
    progress_bar = st.progress(0, text=f"{progress_bar_text_prefix}Initializing...")
    payload_to_send = st.session_state.payload_for_main_analysis_rerun
    if not payload_to_send: st.error("Error: Payload for analysis missing."); time.sleep(2); reset_app_state(); st.stop()
    st.write("Data being sent for analysis:"); st.json(payload_to_send, expanded=False)
    analysis_data_from_api = None 
    api_called_this_stage = False
    try:
        progress_stages = {10:"Pre-processing data...",25:"VIAB Checks (simulated)...",40:"Structuring data...",55:"Cost Estimation...",70:"Revenue Projection (RAG)...",80:"Detailed Financial Modeling...",90:"CFO Strategic Review...",99:"Compiling Final Report..."}
        for pc, txt in progress_stages.items():
            time.sleep(0.7 if pc < 80 else 0.2); progress_bar.progress(pc, text=f"{progress_bar_text_prefix}{txt}")
            if pc >= 20 and not api_called_this_stage : 
                api_called_this_stage = True
                try:
                    api_response = requests.post(AEFNE_MAIN_ANALYSIS_ENDPOINT, json=payload_to_send, timeout=300)
                    api_response.raise_for_status()
                    analysis_data_from_api = api_response.json()
                except requests.exceptions.HTTPError as http_err:
                    st.error(f"Analysis Failed: {http_err}")
                    detail = "Could not retrieve specific reason from API."
                    try: payload = http_err.response.json(); detail = payload.get('detail', detail); st.warning(f"Reason: {detail}")
                    except json.JSONDecodeError: st.warning(f"Raw error: {http_err.response.text[:500]}")
                    st.session_state.analysis_results = {"error": str(http_err), "detail": detail}; st.session_state.stage = "results_display"; st.rerun(); break 
                except Exception as e: st.error(f"Error during API call: {e}"); st.session_state.analysis_results = {"error": str(e), "detail": "General API call error."}; st.session_state.stage = "results_display"; st.rerun(); break
        if analysis_data_from_api: progress_bar.progress(100, text=f"{progress_bar_text_prefix}Complete!"); st.session_state.analysis_results = analysis_data_from_api; st.session_state.stage = "results_display"; st.rerun()
        elif not st.session_state.get("analysis_results", {}).get("error"): st.error(f"{progress_bar_text_prefix.strip()} did not return data."); st.session_state.stage = "initial_form"; st.rerun()
    except Exception as e: st.error(f"Error in {st.session_state.stage} stage: {e}"); st.session_state.stage = "initial_form"; st.rerun()

# ============================ STAGE 5: RESULTS DISPLAY (Financial Analysis) ============================
elif st.session_state.stage == "results_display":
    st.header("4. Financial Viability Analysis Results")
    results = st.session_state.analysis_results
    if results:
        is_preprocessing_failure_for_override = False
        preprocessing_error_detail = ""
        if "error" in results and isinstance(results.get("detail"), str) and \
           ("Pre-processing stage failed" in results["detail"] or "Major discrepancies" in results["detail"]):
            is_preprocessing_failure_for_override = True
            preprocessing_error_detail = results["detail"]

        if is_preprocessing_failure_for_override:
            st.error("Pre-Analysis Check Failed by AEFNE")
            st.warning(f"{preprocessing_error_detail}")
            st.markdown("---"); st.subheader("Demo Override: Manually Provide Key Project Parameters")
            st.caption("For this demo, as VIAB interaction is simulated, you can input key parameters as if VIAB had verified them. AEFNE will then attempt the financial analysis with these figures.")
            with st.form("manual_override_form_key_v4"): # Incremented key
                enriched_brief = st.session_state.get("final_brief_for_analysis", {}) 
                default_name = enriched_brief.get('project_idea_summary_initial', "My Demo Project")[:70]
                default_cost_str = enriched_brief.get('budget_range_pkr', "10M") 
                try: numeric_part = "".join(filter(str.isdigit, default_cost_str.split('-')[0].split('M')[0].split('m')[0])); default_cost_numeric = float(numeric_part) * (1000000 if 'M' in default_cost_str.upper() else 1) if numeric_part else 10000000.0
                except: default_cost_numeric = 10000000.0
                override_project_name = st.text_input("Override Project Name (for context)", value=default_name)
                override_location_factors = st.text_input("Override Location Factors", value=enriched_brief.get("project_location_details", "Good commercial area"))
                override_building_type = st.text_input("Override Building Type", value=enriched_brief.get("building_type_clarified", "Standard Retail Outlet")) # You might want to get this from initial_form_data if enriched_brief doesn't have it
                override_num_units = st.number_input("Override Number of Units", min_value=1, value=int(enriched_brief.get("num_units_suggestion", 1)))
                override_price_per_unit = st.number_input("Override Avg. Price/Unit (PKR)", min_value=0.0, value=float(enriched_brief.get("price_per_unit_suggestion_pkr", default_cost_numeric / 10 if default_cost_numeric > 0 and int(enriched_brief.get("num_units_suggestion", 1)) > 0 else 5000000.0)), format="%.0f")
                override_total_cost = st.number_input("Override Est. Total Cost (PKR)", min_value=1.0, value=default_cost_numeric, format="%.0f")
                override_market_factor = st.selectbox("Override Market Factor", ["High", "Medium", "Low"], index=1)
                override_quality_level = st.selectbox("Override Quality Level", ["Premium", "Standard", "Basic"], index=1)
                submitted_override = st.form_submit_button("Re-run Analysis with These Override Parameters")
                if submitted_override:
                    # --- THIS IS THE CORRECTED PAYLOAD CONSTRUCTION ---
                    
                    # 1. Get the original enriched_brief to access session_id and original file references
                    enriched_brief = st.session_state.get("final_brief_for_analysis", {})

                    # 2. Construct the rich text summary from the override form fields
                    override_summary = (
                        f"Project Concept: {override_project_name}. Original Goal Context: {enriched_brief.get('project_goal', 'N/A')}. "
                        f"DEMO OVERRIDE - Assumed VIAB-equivalent figures: "
                        f"Estimated Total Cost is {override_total_cost:.0f} PKR, "
                        f"Number of Units is {int(override_num_units)}, "
                        f"Building Type for costing is '{override_building_type}', "
                        f"Location context for costing: '{override_location_factors}', "
                        f"Avg. Price Per Unit for revenue is approx {override_price_per_unit:.0f} PKR. "
                        f"Market Factor: {override_market_factor}. Quality: {override_quality_level}."
                    )
                    
                    # 3. Construct the nested 'user_brief' object
                    user_brief_for_payload = {
                        "project_idea_summary": override_summary,
                        "has_existing_files": enriched_brief.get("has_existing_files_confirmed", False),
                        "existing_files_description": enriched_brief.get("existing_files_description_updated"),
                        "currency": st.session_state.project_currency # Pass original currency
                    }
                    final_payload_for_rerun = {
                        "session_id": st.session_state.chat_session_id,
                        "user_brief": user_brief_for_payload,
                        "file_references": enriched_brief.get("uploaded_file_references", [])
                    }

                    # 5. Call the trigger function with this correctly structured payload
                    trigger_main_analysis(final_payload_for_rerun) # We can use the same trigger as the normal path
        
        elif "error" in results:
            st.error(f"Analysis Process Terminated."); 
            if "detail" in results: st.warning(f"Details: {results['detail']}")
            else: st.warning(f"Reason: {results['error']}")
        else: 
            st.success("AI Financial Analysis Complete!"); st.balloons()
            currency_code = st.session_state.get("project_currency", "USD")
            st.subheader(f"Key Financial Projections ({currency_code})") # <<< DYNAMIC CURRENCY IN TITLE
            col1, col2, col3 = st.columns(3)
            with col1: st.metric(label=f"Projected Revenue ({currency_code})", value=f"{results.get('calculated_revenue'):,.0f}" if results.get('calculated_revenue') is not None else "N/A")
            cost_disp = "N/A"
            if results.get('calculated_cost') is not None:
                cost_disp = f"{results.get('calculated_cost'):,.0f}"
            elif results.get('estimated_cost_from_brief') is not None:
                cost_disp = f"{results.get('estimated_cost_from_brief'):,.0f} (from brief)"
            with col2: st.metric(label=f"AI Estimated Project Cost ({currency_code})", value=cost_disp)
            with col3: st.metric(label=f"Projected Profit/Loss ({currency_code})", value=f"{results.get('calculated_profit_loss'):,.0f}" if results.get('calculated_profit_loss') is not None else "N/A")
            st.subheader("AI CFO Strategic Summary:"); st.markdown(f"> {results.get('summary_text', 'Not available.')}")
            if results.get("detailed_financial_analysis"):
                fa_report = results["detailed_financial_analysis"]
                with st.expander("View Detailed Financial Analyst's Report", expanded=False):
                    st.write(f"**Project Name (FA):** {fa_report.get('project_name')}")
                    st.write(f"**Overall Summary & Rationale (FA):**"); st.markdown(fa_report.get("overall_summary_and_rationale", "Not available."))
                    if fa_report.get("assumptions_made_by_fa"): st.json(fa_report.get("assumptions_made_by_fa"), expanded=False)
                    if fa_report.get("viability_metrics"): st.json(fa_report.get("viability_metrics"), expanded=False)
                    if fa_report.get("projected_income_statement"): st.json(fa_report.get("projected_income_statement", {}).get("annual_breakdown", []), expanded=False)
                    if fa_report.get("projected_cash_flow_statement"): st.json(fa_report.get("projected_cash_flow_statement", {}).get("annual_breakdown", []), expanded=False)
            else: st.warning("Detailed Financial Analyst report not available.")
            if results.get("processing_log"):
                with st.expander("View Detailed Processing Log", expanded=False):
                    for log_entry in results["processing_log"]:
                        st.text(str(log_entry))
                    else: st.text(str(results["processing_log"]))
            if results.get("raw_llm_output"):
                with st.expander("View Raw LLM Output (CFO Interpreter)", expanded=False): st.text(results["raw_llm_output"])
            st.markdown("---") 
            if st.button("Perform AI Internal Audit on These Results", key="audit_button_v2", type="primary"):
                trigger_audit()
    else:
        st.error("Analysis results are not available or an unknown error occurred.")
    if st.button("Start New Analysis", key="final_reset_button_v4"):
        reset_app_state()

# ============================ STAGE 6: PERFORMING AUDIT ============================
elif st.session_state.stage == "performing_audit":
    st.header("5. Performing AI Internal Audit...")
    st.info("AEFNE's AI Auditor is reviewing the entire process and data. Please wait.")
    audit_payload = None
    if st.session_state.analysis_results:
        main_analysis_output = st.session_state.analysis_results
        # Ensure all parts of the payload are valid before sending
        if main_analysis_output.get("project_name") and \
           main_analysis_output.get("processing_log") is not None and \
           main_analysis_output.get("inputs_received"):
            audit_payload = {
                "project_name": main_analysis_output.get("project_name"),
                "combined_processing_log": main_analysis_output.get("processing_log"),
                "pre_processing_data": main_analysis_output.get("inputs_received"),
                "cfo_and_fa_main_output": main_analysis_output
            }
        else:
            st.error("Key data missing from previous analysis results to perform audit (e.g. project_name, processing_log, or inputs_received).")
            time.sleep(3); st.session_state.stage = "results_display"; st.rerun(); st.stop()

    if not audit_payload:
        if not st.session_state.analysis_results: # If analysis_results itself is None
            st.error("Cannot perform audit: Main financial analysis results are missing.")
        # (The case where analysis_results exists but parts are missing is handled above)
        time.sleep(3); st.session_state.stage = "results_display"; st.rerun()
    else:
        try:
            with st.spinner("Auditor agents are meticulously working... This might take a moment."):
                audit_api_response = requests.post(AEFNE_AUDIT_ENDPOINT, json=audit_payload, timeout=180) # Adjusted timeout
                audit_api_response.raise_for_status()
            st.session_state.audit_report_data = audit_api_response.json()
            st.session_state.stage = "audit_results_display"
            st.rerun()
        except requests.exceptions.HTTPError as http_err_audit:
            st.error(f"AI Audit Failed: {http_err_audit}")
            detail = "Could not retrieve specific reason from audit API."
            try: payload = http_err_audit.response.json(); detail = payload.get('detail', detail); st.warning(f"Reason: {detail}")
            except json.JSONDecodeError: st.warning(f"Raw error (audit): {http_err_audit.response.text[:500]}")
            st.session_state.audit_report_data = {"error": str(http_err_audit), "detail": detail}; st.session_state.stage = "audit_results_display"; st.rerun()
        except Exception as e_audit:
            st.error(f"An unexpected error occurred during audit: {e_audit}")
            st.session_state.audit_report_data = {"error": str(e_audit), "detail": "General error during audit process."}; st.session_state.stage = "audit_results_display"; st.rerun()

# ============================ STAGE 7: AUDIT RESULTS DISPLAY ============================
elif st.session_state.stage == "audit_results_display":
    st.header("6. AI Internal Audit Report")
    audit_report = st.session_state.audit_report_data
    if audit_report:
        if "error" in audit_report:
            st.error(f"Audit Process Encountered an Issue.")
            if "detail" in audit_report: st.warning(f"Details: {audit_report['detail']}")
            else: st.warning(f"Reason: {audit_report['error']}")
        else: 
            st.success("AI Internal Audit Complete!")
            st.markdown(f"**Project Audited:** {audit_report.get('project_name_audited', 'N/A')}")
            st.markdown(f"**Audit Timestamp:** {audit_report.get('audit_timestamp', 'N/A')}")
            st.subheader("Overall Audit Summary by AEFNE AI Auditor:"); st.markdown(f"> {audit_report.get('overall_audit_summary', 'Not available.')}")
            st.markdown("---")
            with st.expander("Detailed Log Review Analysis", expanded=False): st.markdown(audit_report.get('log_review_summary', "Not available."))
            with st.expander("Detailed Data Consistency Analysis", expanded=False): st.markdown(audit_report.get('data_consistency_summary', "Not available."))
            with st.expander("Compliance Check Status (MVP)", expanded=False): st.markdown(audit_report.get('compliance_status_summary', "Not available."))
            if audit_report.get("key_recommendations_or_concerns"):
                st.subheader("Key Recommendations or Concerns from Audit:")
                for item in audit_report["key_recommendations_or_concerns"]: st.markdown(f"- {item}")
            if audit_report.get("auditor_processing_log_snippet"):
                 with st.expander("Auditor's Own Processing Log Snippet", expanded=False):
                    if isinstance(audit_report["auditor_processing_log_snippet"], list): [st.text(str(log)) for log in audit_report["auditor_processing_log_snippet"]]
                    else: st.text(str(audit_report["auditor_processing_log_snippet"]))
    else: st.error("Audit report data is not available.")
    if st.button("Start New Project Analysis", key="audit_reset_button_v2"): # Incremented key
        reset_app_state()