import uuid

import httpx
import streamlit as st


st.set_page_config(page_title="AIA Tester", page_icon="🧪", layout="wide")
st.title("AIA System Tester")

if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = str(uuid.uuid4())
if "last_file_id" not in st.session_state:
    st.session_state.last_file_id = ""
if "history" not in st.session_state:
    st.session_state.history = []


with st.sidebar:
    st.header("Settings")
    base_url = st.text_input("API Base URL", value="http://localhost:8000").rstrip("/")
    user_id = st.text_input("User ID", value="streamlit-user")
    st.session_state.conversation_id = st.text_input(
        "Conversation ID", value=st.session_state.conversation_id
    )
    st.session_state.last_file_id = st.text_input("File ID", value=st.session_state.last_file_id)

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
                        resp = client.get(
                            f"{base_url}/upload/{st.session_state.last_file_id}/status"
                        )
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
    st.subheader("2) Send Message")
    instruction = st.text_area(
        "Instruction",
        value="Find issues assigned to me in Jira and send a summary to Telegram.",
        height=120,
    )
    if st.button("Send /qa-intake"):
        try:
            payload = {
                "user_id": user_id,
                "conversation_id": st.session_state.conversation_id,
                "instruction": instruction,
            }
            if st.session_state.last_file_id:
                payload["file_id"] = st.session_state.last_file_id
            with httpx.Client(timeout=120.0) as client:
                resp = client.post(f"{base_url}/qa-intake", json=payload)
            st.write(f"HTTP {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                st.session_state.history.append(
                    {"instruction": instruction, "response": data}
                )
                st.json(data)
            else:
                st.code(resp.text)
        except Exception as exc:
            st.error(f"Request error: {exc}")

st.subheader("3) Conversation Inspect")
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
