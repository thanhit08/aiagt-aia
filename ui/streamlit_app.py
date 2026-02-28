import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
import streamlit as st


WORKFLOW_NODES = ["intake", "rag_check", "rag_query_enrichment", "rag", "route", "execute_actions", "aggregate", "done"]


def _post_qa(base_url: str, payload: dict) -> httpx.Response:
    with httpx.Client(timeout=180.0) as client:
        return client.post(f"{base_url}/qa-intake", json=payload)


def _draw_workflow_map() -> None:
    st.graphviz_chart(
        """
digraph AIA {
  rankdir=LR;
  node [shape=box, style="rounded,filled", color="#1f2937", fillcolor="#f8fafc"];
  user [label="User Request"];
  intake [label="Intake"];
  ragcheck [label="RAG Check"];
  ragenrich [label="RAG Query Enrichment"];
  rag [label="RAG Retrieve + Clean"];
  route [label="Route Plan"];
  exec [label="Execute Actions Dispatcher"];
  fanout [label="Parallel Actions", shape=diamond, fillcolor="#eef2ff"];
  jira [label="Jira Action(s)"];
  telegram [label="Telegram Action(s)"];
  join [label="All Actions Completed", shape=diamond, fillcolor="#eef2ff"];
  aggregate [label="Aggregate"];
  done [label="Done"];

  user -> intake -> ragcheck;
  ragcheck -> route [label="no file_id"];
  ragcheck -> ragenrich [label="has file_id"];
  ragenrich -> rag -> route;
  route -> exec -> fanout;
  fanout -> jira;
  fanout -> telegram;
  jira -> join;
  telegram -> join;
  join -> aggregate -> done;
}
"""
    )


def _render_progress_html(status: dict | None) -> str:
    current_node = (status or {}).get("current_node", "")
    step_index = int((status or {}).get("step_index", 0))
    state = (status or {}).get("state", "idle")
    lines = [
        "<style>",
        ".wf-row {display:flex; align-items:center; gap:10px; margin:6px 0; font-family:monospace;}",
        ".wf-spin {width:12px; height:12px; border:2px solid #cbd5e1; border-top:2px solid #2563eb; border-radius:50%; animation:spin 1s linear infinite;}",
        ".wf-dot {width:12px; height:12px; border-radius:50%; background:#cbd5e1;}",
        ".wf-done {color:#166534; font-weight:600;}",
        ".wf-run {color:#1d4ed8; font-weight:700;}",
        ".wf-pend {color:#475569;}",
        "@keyframes spin {0%{transform:rotate(0deg);}100%{transform:rotate(360deg);}}",
        "</style>",
    ]
    for idx, node in enumerate(WORKFLOW_NODES, start=1):
        if state == "completed" and node == "done":
            icon = "<span>[OK]</span>"
            klass = "wf-done"
        elif idx < step_index:
            icon = "<span>[OK]</span>"
            klass = "wf-done"
        elif node == current_node and state == "running":
            icon = "<span class='wf-spin'></span>"
            klass = "wf-run"
        elif state == "failed" and node == "failed":
            icon = "<span>[X]</span>"
            klass = "wf-run"
        else:
            icon = "<span class='wf-dot'></span>"
            klass = "wf-pend"
        lines.append(f"<div class='wf-row {klass}'>{icon}<span>{idx}. {node}</span></div>")
    return "\n".join(lines)


def _render_step_detail_buttons(status: dict | None) -> None:
    details = (status or {}).get("step_details", [])
    if not isinstance(details, list) or not details:
        st.caption("Step details will appear after workflow starts.")
        return
    for idx, item in enumerate(details, start=1):
        node = item.get("node", f"step_{idx}")
        state = item.get("state", "unknown")
        duration = _step_duration_seconds(item)
        c1, c2, c3, c4 = st.columns([4, 2, 2, 2])
        with c1:
            st.write(f"{idx}. `{node}`")
        with c2:
            st.write(state)
        with c3:
            st.write(f"{duration:.2f}s")
        with c4:
            if st.button("Detail", key=f"detail_btn_{idx}_{node}"):
                st.session_state.selected_step_detail = item

    selected = st.session_state.get("selected_step_detail")
    if isinstance(selected, dict):
        st.markdown("**Step Detail**")
        st.json(selected)


def _parse_iso(ts: str | None) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _step_duration_seconds(item: dict) -> float:
    started = _parse_iso(item.get("started_at"))
    finished = _parse_iso(item.get("finished_at"))
    if started is None:
        return 0.0
    end = finished or datetime.now(timezone.utc)
    return max(0.0, (end - started).total_seconds())


def _workflow_total_seconds(status: dict | None) -> float:
    details = (status or {}).get("step_details", [])
    if not isinstance(details, list) or not details:
        return 0.0
    starts = [_parse_iso(item.get("started_at")) for item in details if isinstance(item, dict)]
    ends = [(_parse_iso(item.get("finished_at")) or datetime.now(timezone.utc)) for item in details if isinstance(item, dict)]
    starts = [x for x in starts if x is not None]
    ends = [x for x in ends if x is not None]
    if not starts or not ends:
        return 0.0
    return max(0.0, (max(ends) - min(starts)).total_seconds())


st.set_page_config(page_title="AIA Tester", page_icon="AIA", layout="wide")
st.title("AIA System Tester")

if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = str(uuid.uuid4())
if "last_file_id" not in st.session_state:
    st.session_state.last_file_id = ""
if "history" not in st.session_state:
    st.session_state.history = []
if "latest_status_payload" not in st.session_state:
    st.session_state.latest_status_payload = {}
if "selected_step_detail" not in st.session_state:
    st.session_state.selected_step_detail = None
if "accept_parallel" not in st.session_state:
    st.session_state.accept_parallel = False

with st.sidebar:
    st.header("Settings")
    base_url = st.text_input("API Base URL", value="http://localhost:8000").rstrip("/")
    user_id = st.text_input("User ID", value="streamlit-user")
    st.session_state.conversation_id = st.text_input("Conversation ID", value=st.session_state.conversation_id)
    st.session_state.last_file_id = st.text_input("File ID", value=st.session_state.last_file_id)
    st.session_state.accept_parallel = st.checkbox(
        "ACCEPT_PARALLEL (request override)",
        value=st.session_state.accept_parallel,
    )

col_a, col_b = st.columns([1, 1])

with col_a:
    st.subheader("1) Upload File")
    uploaded = st.file_uploader("Choose a file", type=["txt", "md", "csv"])
    if st.button("Upload"):
        if uploaded is None:
            st.error("Please select a file.")
        else:
            files = {"file": (uploaded.name, uploaded.getvalue(), uploaded.type or "text/plain")}
            data = {"user_id": user_id}
            try:
                with httpx.Client(timeout=60.0) as client:
                    resp = client.post(f"{base_url}/upload", files=files, data=data)
                if resp.status_code == 200:
                    payload = resp.json()
                    st.session_state.last_file_id = payload.get("file_id", "")
                    st.success("Upload complete.")
                    st.json(payload)
                else:
                    st.error(f"Upload failed: {resp.status_code}")
                    st.code(resp.text)
            except Exception as exc:
                st.error(f"Upload error: {exc}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Check Upload Status"):
            if not st.session_state.last_file_id:
                st.warning("Set file_id first.")
            else:
                try:
                    with httpx.Client(timeout=30.0) as client:
                        resp = client.get(f"{base_url}/upload/{st.session_state.last_file_id}/status")
                    st.write(f"HTTP {resp.status_code}")
                    if resp.status_code == 200:
                        st.json(resp.json())
                    else:
                        st.code(resp.text)
                except Exception as exc:
                    st.error(f"Status error: {exc}")
    with c2:
        if st.button("Get Upload Metadata"):
            if not st.session_state.last_file_id:
                st.warning("Set file_id first.")
            else:
                try:
                    with httpx.Client(timeout=30.0) as client:
                        resp = client.get(f"{base_url}/upload/{st.session_state.last_file_id}")
                    st.write(f"HTTP {resp.status_code}")
                    if resp.status_code == 200:
                        st.json(resp.json())
                    else:
                        st.code(resp.text)
                except Exception as exc:
                    st.error(f"Metadata error: {exc}")

with col_b:
    st.subheader("2) Workflow View")
    _draw_workflow_map()
    progress_placeholder = st.empty()
    detail_placeholder = st.empty()
    timing_placeholder = st.empty()
    per_step_placeholder = st.container()

    st.subheader("3) Send Message")
    instruction = st.text_area(
        "Instruction",
        value="Get all issues in the file related to accuracy and send to Telegram channel.",
        height=120,
    )

    if st.button("Send /qa-intake"):
        try:
            st.session_state.selected_step_detail = None
            request_id = str(uuid.uuid4())
            payload = {
                "request_id": request_id,
                "user_id": user_id,
                "conversation_id": st.session_state.conversation_id,
                "instruction": instruction,
                "accept_parallel": bool(st.session_state.accept_parallel),
            }
            if st.session_state.last_file_id:
                payload["file_id"] = st.session_state.last_file_id

            ui_started_at = time.perf_counter()
            progress_placeholder.markdown(
                _render_progress_html({"state": "running", "current_node": "intake", "step_index": 1}),
                unsafe_allow_html=True,
            )
            detail_placeholder.info(f"Request ID: {request_id}")
            timing_placeholder.info("Total runtime: 0.00s")

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_post_qa, base_url, payload)
                with httpx.Client(timeout=10.0) as poll_client:
                    while not future.done():
                        try:
                            sresp = poll_client.get(f"{base_url}/qa-intake/{request_id}/status")
                            if sresp.status_code == 200:
                                status_payload = sresp.json()
                                st.session_state.latest_status_payload = status_payload
                                progress_placeholder.markdown(
                                    _render_progress_html(status_payload),
                                    unsafe_allow_html=True,
                                )
                                detail_placeholder.info(
                                    f"State: {status_payload.get('state')} | "
                                    f"Current: {status_payload.get('current_node')} | "
                                    f"Step: {status_payload.get('step_index')}/{status_payload.get('total_steps')}"
                                )
                                total_secs = _workflow_total_seconds(status_payload)
                                live_secs = max(total_secs, time.perf_counter() - ui_started_at)
                                timing_placeholder.info(f"Total runtime: {live_secs:.2f}s")
                        except Exception:
                            pass
                        time.sleep(0.4)

                resp = future.result()

            st.write(f"HTTP {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.history.append({"instruction": instruction, "response": data})
                progress_placeholder.markdown(
                    _render_progress_html({"state": "completed", "current_node": "done", "step_index": len(WORKFLOW_NODES)}),
                    unsafe_allow_html=True,
                )
                detail_placeholder.success("Workflow completed.")
                total_secs = _workflow_total_seconds(st.session_state.latest_status_payload)
                ui_total = time.perf_counter() - ui_started_at
                timing_placeholder.success(f"Total runtime: {max(total_secs, ui_total):.2f}s")
                try:
                    with httpx.Client(timeout=10.0) as client:
                        done_status = client.get(f"{base_url}/qa-intake/{request_id}/status")
                        if done_status.status_code == 200:
                            st.session_state.latest_status_payload = done_status.json()
                            final_total = _workflow_total_seconds(st.session_state.latest_status_payload)
                            timing_placeholder.success(f"Total runtime: {final_total:.2f}s")
                except Exception:
                    pass
                st.json(data)
            else:
                progress_placeholder.markdown(
                    _render_progress_html({"state": "failed", "current_node": "failed", "step_index": 0}),
                    unsafe_allow_html=True,
                )
                detail_placeholder.error("Workflow failed.")
                total_secs = _workflow_total_seconds(st.session_state.latest_status_payload)
                ui_total = time.perf_counter() - ui_started_at
                timing_placeholder.error(f"Total runtime: {max(total_secs, ui_total):.2f}s")
                st.code(resp.text)
        except Exception as exc:
            progress_placeholder.markdown(
                _render_progress_html({"state": "failed", "current_node": "failed", "step_index": 0}),
                unsafe_allow_html=True,
            )
            detail_placeholder.error(f"Request error: {exc}")
            timing_placeholder.error("Total runtime: failed")

    st.markdown("**Workflow Step Details**")
    with per_step_placeholder:
        _render_step_detail_buttons(st.session_state.latest_status_payload)

st.subheader("4) Conversation Inspect")
if st.button("Get Conversation"):
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(f"{base_url}/conversation/{st.session_state.conversation_id}")
        st.write(f"HTTP {resp.status_code}")
        if resp.status_code == 200:
            st.json(resp.json())
        else:
            st.code(resp.text)
    except Exception as exc:
        st.error(f"Conversation fetch error: {exc}")

st.subheader("Session History")
for idx, row in enumerate(st.session_state.history[-10:], start=1):
    with st.expander(f"Request #{idx}"):
        st.write("Instruction:")
        st.code(row["instruction"])
        st.write("Response:")
        st.json(row["response"])
