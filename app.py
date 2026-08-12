import streamlit as st
from google import genai
import sqlite3
import json
import os
import io
import time
from pypdf import PdfReader, PdfWriter

# --- 페이지 설정 ---
st.set_page_config(page_title="나만의 영구 문제은행", layout="centered")
st.markdown("""
    <style>
    body { color: #000000; background-color: #ffffff; }
    h1, h2, h3, h4, h5, h6 { color: #000000; }
    .stButton>button { width: 100%; border-radius: 5px; border: 1px solid #ccc; background-color: #f8f9fa; color: #000000; }
    .stExpander { border: 1px solid #eee; border-radius: 5px; background-color: #ffffff; }
    </style>
    """, unsafe_allow_html=True)

ROUND_OPTIONS = [f"{i}회차" for i in range(1, 13)]
DB_FILE = "question_bank.db"

# --- 데이터베이스(DB) 초기화 ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS questions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  round TEXT, 
                  content TEXT, 
                  correct_answer TEXT, 
                  solution TEXT, 
                  is_wrong INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_progress 
                 (round TEXT, 
                  question_id INTEGER, 
                  user_answer TEXT, 
                  is_graded INTEGER DEFAULT 0,
                  PRIMARY KEY(round, question_id))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS wrong_progress 
                 (question_id INTEGER PRIMARY KEY, 
                  user_answer TEXT, 
                  is_graded INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

def save_question(round_name, content, answer, solution):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO questions (round, content, correct_answer, solution, is_wrong) VALUES (?, ?, ?, ?, 0)", 
              (round_name, content, answer, solution))
    conn.commit()
    conn.close()

def update_question_content_and_solution(q_id, content, solution):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE questions SET content=?, solution=? WHERE id=?", (content, solution, q_id))
    conn.commit()
    conn.close()

def update_question_answer(q_id, answer):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE questions SET correct_answer=? WHERE id=?", (answer, q_id))
    conn.commit()
    conn.close()

def mark_wrong(q_id, status):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE questions SET is_wrong = ? WHERE id = ?", (status, q_id))
    if status == 0: c.execute("DELETE FROM wrong_progress WHERE question_id = ?", (q_id,))
    conn.commit()
    conn.close()

def load_progress(round_name, q_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_answer, is_graded FROM user_progress WHERE round = ? AND question_id = ?", (round_name, q_id))
    row = c.fetchone()
    conn.close()
    return (row[0], bool(row[1])) if row else (None, False)

def save_progress(round_name, q_id, user_answer, is_graded):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO user_progress (round, question_id, user_answer, is_graded) VALUES (?, ?, ?, ?) 
                 ON CONFLICT(round, question_id) DO UPDATE SET user_answer = ?, is_graded = ?''', 
              (round_name, q_id, user_answer, int(is_graded), user_answer, int(is_graded)))
    conn.commit()
    conn.close()

def load_wrong_progress(q_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_answer, is_graded FROM wrong_progress WHERE question_id = ?", (q_id,))
    row = c.fetchone()
    conn.close()
    return (row[0], bool(row[1])) if row else (None, False)

def save_wrong_progress(q_id, user_answer, is_graded):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO wrong_progress (question_id, user_answer, is_graded) VALUES (?, ?, ?) 
                 ON CONFLICT(question_id) DO UPDATE SET user_answer = ?, is_graded = ?''', 
              (q_id, user_answer, int(is_graded), user_answer, int(is_graded)))
    conn.commit()
    conn.close()

def clear_progress(round_name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM user_progress WHERE round = ?", (round_name,))
    conn.commit()
    conn.close()

def reset_round_questions(round_name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    q_ids = [row[0] for row in c.execute("SELECT id FROM questions WHERE round = ?", (round_name,)).fetchall()]
    if q_ids: c.execute(f"DELETE FROM wrong_progress WHERE question_id IN ({','.join(['?']*len(q_ids))})", q_ids)
    c.execute("DELETE FROM questions WHERE round = ?", (round_name,))
    c.execute("DELETE FROM user_progress WHERE round = ?", (round_name,))
    conn.commit()
    conn.close()

# --- 503 및 과부하 방지용 재시도(Retry) 래퍼 함수 ---
def call_gemini_with_retry(client, contents, max_retries=5, initial_delay=3):
    """503 에러나 일시적 서버 과부하시 대기 시간을 늘려가며 재시도"""
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=contents
            )
            return response
        except Exception as e:
            error_str = str(e)
            if "503" in error_str or "UNAVAILABLE" in error_str or "429" in error_str:
                if attempt == max_retries - 1:
                    raise e
                time.sleep(delay)
                delay *= 2  # 실패할 경우 대기 시간을 3초 -> 6초 -> 12초로 배가시킴
            else:
                raise e

def check_password():
    if "password_correct" not in st.session_state: st.session_state["password_correct"] = False
    if not st.session_state["password_correct"]:
        st.title("🔒 로그인 필요")
        pwd = st.text_input("앱 잠금 해제 비밀번호를 입력하세요", type="password")
        if pwd == st.secrets.get("APP_PASSWORD"):
            st.session_state["password_correct"] = True
            st.rerun()
        elif pwd: st.error("비밀번호가 틀렸습니다.")
        return False
    return True

if check_password():
    client = genai.Client(api_key=st.secrets.get("GEMINI_API_KEY"))
    st.sidebar.title("📚 학습 메뉴")
    menu = st.sidebar.radio("이동할 메뉴", ["문제 등록", "회차별 시험", "오답 노트", "문제 관리/수정"])

    # ================= 1. 문제 등록 =================
    if menu == "문제 등록":
        st.header("📌 신규 문제 등록")
        round_name = st.selectbox("회차 선택", ROUND_OPTIONS)
        
        if st.button(f"⚠️ [{round_name}]에 등록된 모든 문제 데이터 초기화하기"):
            reset_round_questions(round_name)
            st.success(f"[{round_name}]의 모든 문제와 학습 기록이 깨끗하게 초기화되었습니다!")
            st.toast("초기화 완료!", icon="🗑️")

        st.markdown("---")
        upload_mode = st.radio("업로드 방식을 선택하세요:", ["기본 (문제+해설 일체형)", "고급 (문제지 + 해설지 분리 업로드)"], horizontal=True)

        if upload_mode == "기본 (문제+해설 일체형)":
            uploaded_file = st.file_uploader("문제 사진 또는 PDF 업로드", type=["jpg", "jpeg", "png", "pdf"])
            if st.button("AI 분석 및 DB 저장"):
                if uploaded_file:
                    total_count = 0
                    
                    # 1. PDF인 경우 2페이지씩 아주 잘게 쪼개서 순차 처리 (부하 최소화)
                    if uploaded_file.type == "application/pdf":
                        try:
                            pdf_reader = PdfReader(uploaded_file)
                            total_pages = len(pdf_reader.pages)
                            chunk_size = 2  # 5장에서 2장 단위로 축소
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()

                            for i in range(0, total_pages, chunk_size):
                                start_p = i
                                end_p = min(i + chunk_size, total_pages)
                                
                                status_text.text(f"PDF 안전 처리 중... ({start_p + 1} ~ {end_p}페이지 / 총 {total_pages}페이지)")
                                progress_bar.progress((i + 1) / total_pages)

                                pdf_writer = PdfWriter()
                                for p_idx in range(start_p, end_p):
                                    pdf_writer.add_page(pdf_reader.pages[p_idx])
                                
                                chunk_io = io.BytesIO()
                                pdf_writer.write(chunk_io)
                                chunk_bytes = chunk_io.getvalue()

                                prompt_contents = [
                                    {
                                        "inline_data": {
                                            "data": chunk_bytes,
                                            "mime_type": "application/pdf"
                                        }
                                    },
                                    """
                                    이 PDF 구간(일부 페이지)에 포함된 모든 문제를 각각 독립적인 낱개 문제로 분리해서 추출해줘.
                                    핵심 규칙: 
                                    1. "question_text"에는 보기(①, ② 등)를 제외한 순수 문제 본문만 담아줘.
                                    2. "options"에는 보기들을 리스트 형태로 각각 담아줘 (예: ["① 보기내용1", "② 보기내용2", "③ 보기내용3", "④ 보기내용4"]).
                                    3. "answer"에는 정답 번호나 내용 (예: "①" 또는 "1" 등 정확한 정답)을 적어줘.
                                    4. "solution"에는 해설을 적어줘.
                                    반드시 아래 JSON 형식의 배열(Array) 형태로만 정확하게 답변해줘. 마크다운 기호(```json 등)는 제외하거나 표준 JSON으로 줘.
                                    [
                                      {
                                        "question_text": "문제 본문 내용",
                                        "options": ["① 보기1", "② 보기2", "③ 보기3", "④ 보기4"],
                                        "answer": "①",
                                        "solution": "해설 내용"
                                      }
                                    ]
                                    """
                                ]

                                response = call_gemini_with_retry(client, prompt_contents)
                                
                                raw_text = response.text.strip()
                                if raw_text.startswith("```json"): raw_text = raw_text[7:]
                                if raw_text.startswith("```"): raw_text = raw_text[3:]
                                if raw_text.endswith("```"): raw_text = raw_text[:-3]
                                raw_text = raw_text.strip()

                                questions_list = json.loads(raw_text)
                                for q in questions_list:
                                    q_text = q.get("question_text", "").strip()
                                    opts = q.get("options", [])
                                    full_content = json.dumps({"question": q_text, "options": opts}, ensure_ascii=False)
                                    a_text = str(q.get("answer", "")).strip()
                                    s_text = q.get("solution", "").strip()
                                    if q_text:
                                        save_question(round_name, full_content, a_text, s_text)
                                        total_count += 1

                                # 각 2페이지 처리 직후 서버 안정화를 위해 2초 대기
                                time.sleep(2.0)

                            progress_bar.empty()
                            status_text.empty()
                            st.success(f"🎉 총 {total_count}개의 문제가 성공적으로 등록되었습니다!")
                            st.toast("문제 등록 완료!", icon="✅")

                        except Exception as e:
                            st.error(f"AI 분석 중 오류가 발생했습니다: {e}")

                    # 2. 이미지 파일인 경우 (단건 처리)
                    else:
                        with st.spinner("AI가 이미지를 분석하고 보기를 분리하는 중..."):
                            try:
                                file_bytes = uploaded_file.getvalue()
                                mime_type = uploaded_file.type

                                prompt_contents = [
                                    {
                                        "inline_data": {
                                            "data": file_bytes,
                                            "mime_type": mime_type
                                        }
                                    },
                                    """
                                    이 이미지에 포함된 모든 문제를 각각 독립적인 낱개 문제로 완벽하게 분리해서 추출해줘.
                                    핵심 규칙: 
                                    1. "question_text"에는 보기(①, ② 등)를 제외한 순수 문제 본문만 담아줘.
                                    2. "options"에는 보기들을 리스트 형태로 각각 담아줘 (예: ["① 보기내용1", "② 보기내용2", "③ 보기내용3", "④ 보기내용4"]).
                                    3. "answer"에는 정답 번호나 내용 (예: "①" 또는 "1" 등 정확한 정답)을 적어줘.
                                    4. "solution"에는 해설을 적어줘.
                                    반드시 아래 JSON 형식의 배열(Array) 형태로만 정확하게 답변해줘. 마크다운 기호(```json 등)는 제외하거나 표준 JSON으로 줘.
                                    [
                                      {
                                        "question_text": "문제 본문 내용",
                                        "options": ["① 보기1", "② 보기2", "③ 보기3", "④ 보기4"],
                                        "answer": "①",
                                        "solution": "해설 내용"
                                      }
                                    ]
                                    """
                                ]

                                response = call_gemini_with_retry(client, prompt_contents)
                                raw_text = response.text.strip()
                                if raw_text.startswith("```json"): raw_text = raw_text[7:]
                                if raw_text.startswith("```"): raw_text = raw_text[3:]
                                if raw_text.endswith("```"): raw_text = raw_text[:-3]
                                raw_text = raw_text.strip()

                                questions_list = json.loads(raw_text)
                                count = 0
                                for q in questions_list:
                                    q_text = q.get("question_text", "").strip()
                                    opts = q.get("options", [])
                                    full_content = json.dumps({"question": q_text, "options": opts}, ensure_ascii=False)
                                    a_text = str(q.get("answer", "")).strip()
                                    s_text = q.get("solution", "").strip()
                                    if q_text:
                                        save_question(round_name, full_content, a_text, s_text)
                                        count += 1

                                st.success(f"🎉 총 {count}개의 문제가 성공적으로 등록되었습니다!")
                                st.toast("문제 등록 완료!", icon="✅")
                            except Exception as e:
                                st.error(f"AI 분석 중 오류가 발생했습니다: {e}")
                else:
                    st.warning("파일을 업로드해주세요.")
        
        else: # 고급 분리 업로드 (문제지+해설지)
            st.info("💡 문제지와 해설지가 따로 있는 경우, AI가 두 파일을 대조해 자동 매칭합니다.")
            col1, col2 = st.columns(2)
            with col1: q_file = st.file_uploader("1. 문제지 파일", type=["jpg", "jpeg", "png", "pdf"])
            with col2: s_file = st.file_uploader("2. 해설지 파일", type=["jpg", "jpeg", "png", "pdf"])
            
            if st.button("문제+해설 동시 분석 및 자동 매칭"):
                if q_file and s_file:
                    with st.spinner("AI가 문제지와 해설지를 매칭하는 중... (대용량 파일일 경우 시간이 걸릴 수 있습니다)"):
                        try:
                            q_bytes = q_file.getvalue()
                            q_mime = q_file.type
                            s_bytes = s_file.getvalue()
                            s_mime = s_file.type

                            prompt_contents = [
                                {
                                    "inline_data": {
                                        "data": q_bytes,
                                        "mime_type": q_mime
                                    }
                                },
                                {
                                    "inline_data": {
                                        "data": s_bytes,
                                        "mime_type": s_mime
                                    }
                                },
                                """
                                첫 번째로 제공된 자료는 '문제지'이고, 두 번째로 제공된 자료는 '해설지'야.
                                이 두 자료를 상호 대조하여 각 문제 번호에 맞는 정답과 해설을 정확하게 찾아내어 완전한 세트로 구성해줘.
                                핵심 규칙: 
                                1. "question_text"에는 보기(①, ② 등)를 제외한 순수 문제 본문만 담아줘.
                                2. "options"에는 보기들을 리스트 형태로 각각 담아줘 (예: ["① 보기내용1", "② 보기내용2", "③ 보기내용3", "④ 보기내용4"]).
                                3. "answer"에는 해설지/정답지를 참고하여 정확한 정답 번호나 내용 (예: "①" 또는 "1")을 적어줘.
                                4. "solution"에는 해당 문제의 해설 내용을 적어줘.
                                반드시 아래 JSON 형식의 배열(Array) 형태로만 정확하게 답변해줘. 마크다운 기호(```json 등)는 제외하거나 표준 JSON으로 줘.
                                [
                                  {
                                    "question_text": "문제 본문 내용",
                                    "options": ["① 보기1", "② 보기2", "③ 보기3", "④ 보기4"],
                                    "answer": "①",
                                    "solution": "해설 내용"
                                  }
                                ]
                                """
                            ]

                            response = call_gemini_with_retry(client, prompt_contents)
                            raw_text = response.text.strip()
                            if raw_text.startswith("```json"): raw_text = raw_text[7:]
                            if raw_text.startswith("```"): raw_text = raw_text[3:]
                            if raw_text.endswith("```"): raw_text = raw_text[:-3]
                            raw_text = raw_text.strip()

                            questions_list = json.loads(raw_text)
                            count = 0
                            for q in questions_list:
                                q_text = q.get("question_text", "").strip()
                                opts = q.get("options", [])
                                full_content = json.dumps({"question": q_text, "options": opts}, ensure_ascii=False)
                                a_text = str(q.get("answer", "")).strip()
                                s_text = q.get("solution", "").strip()
                                if q_text:
                                    save_question(round_name, full_content, a_text, s_text)
                                    count += 1

                            st.success(f"🎉 총 {count}개의 문제가 자동 매칭을 통해 등록되었습니다!")
                            st.toast("자동 매칭 완료!", icon="✨")
                        except Exception as e:
                            st.error(f"AI 분석 중 오류가 발생했습니다: {e}")
                else:
                    st.warning("두 파일을 모두 업로드해주세요.")

        # --- 데이터 백업 및 복구 구역 ---
        st.markdown("---")
        st.subheader("💾 데이터 백업 및 복구 (서버 초기화 대비)")
        
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "rb") as f:
                db_bytes = f.read()
            
            download_clicked = st.download_button(
                label="📥 현재 문제 데이터 백업하기 (.db 다운로드)",
                data=db_bytes,
                file_name="question_bank.db",
                mime="application/x-sqlite3"
            )
            if download_clicked:
                st.toast("백업 파일이 다운로드되었습니다!", icon="💾")

        uploaded_db = st.file_uploader("📤 백업해둔 DB 파일 업로드하여 복구하기", type=["db"])
        if uploaded_db is not None:
            if st.button("🔄 데이터 복구 적용하기"):
                try:
                    with open(DB_FILE, "wb") as f:
                        f.write(uploaded_db.getbuffer())
                    st.success("🎉 데이터가 성공적으로 복구되었습니다! 잠시 후 새로고침됩니다.")
                    st.toast("복구 완료!", icon="🔄")
                    st.rerun()
                except Exception as e:
                    st.error(f"복구 중 오류가 발생했습니다: {e}")

    # ================= 2. 회차별 시험 =================
    elif menu == "회차별 시험":
        st.header("🎯 회차별 시험 풀기")
        selected_round = st.selectbox("풀어볼 회차 선택", ROUND_OPTIONS)
        
        conn = sqlite3.connect(DB_FILE)
        total_q_count = conn.execute("SELECT COUNT(*) FROM questions WHERE round = ?", (selected_round,)).fetchone()[0]
        has_history = conn.execute("SELECT COUNT(*) FROM user_progress WHERE round = ?", (selected_round,)).fetchone()[0] > 0
        conn.close()

        st.info(f"📊 **[{selected_round}]** 현재 총 **{total_q_count}문제**가 등록되어 있습니다.")

        mode = "이어서 풀기"
        if has_history:
            st.markdown("---")
            st.info(f"📌 **{selected_round}**에 이전에 풀던 기록이 존재합니다.")
            mode = st.radio("학습 방식을 선택하세요:", ["이어서 풀기", "처음부터 새로 풀기"], horizontal=True, key="mode_select")
            if mode == "처음부터 새로 풀기":
                if st.button("🔄 기존 기록 초기화하고 새로 시작하기"):
                    clear_progress(selected_round)
                    st.success("기존 풀이 기록이 초기화되었습니다!")
                    st.toast("기록 초기화 완료", icon="🔄")
                    st.rerun()

        if mode == "이어서 풀기" or not has_history:
            conn = sqlite3.connect(DB_FILE)
            questions = conn.execute("SELECT * FROM questions WHERE round = ?", (selected_round,)).fetchall()
            conn.close()

            score = 0
            total_q = len(questions)

            if not questions:
                st.warning("해당 회차에 등록된 문제가 없습니다. '문제 등록' 메뉴에서 먼저 문제를 추가해주세요.")
            else:
                for idx, q in enumerate(questions):
                    q_id = q[0]
                    raw_content = q[2]
                    correct_ans = q[3]
                    solution = q[4]

                    try:
                        content_dict = json.loads(raw_content)
                        q_text = content_dict.get("question", raw_content)
                        options = content_dict.get("options", [])
                    except:
                        q_text = raw_content
                        options = []

                    st.markdown(f"---")
                    st.markdown(f"**[문제 {idx + 1}] (ID: {q_id})**")
                    st.markdown(q_text)
                    
                    saved_ans, saved_graded = load_progress(selected_round, q_id)
                    ans = saved_ans

                    if options:
                        default_idx = None
                        if saved_ans in options:
                            default_idx = options.index(saved_ans)

                        selected_option = st.radio(
                            f"보기 선택 (ID: {q_id})", 
                            options, 
                            index=default_idx, 
                            key=f"radio_{q_id}"
                        )
                        
                        if selected_option and selected_option != saved_ans:
                            ans = selected_option
                            saved_graded = True
                            save_progress(selected_round, q_id, ans, saved_graded)
                    else:
                        ans = st.text_input(f"답안 입력", value=saved_ans if saved_ans else "", key=f"ans_{q_id}")
                        if st.button(f"채점 및 확인 (ID: {q_id})", key=f"grade_btn_{q_id}"):
                            saved_graded = True
                            save_progress(selected_round, q_id, ans, saved_graded)

                    if saved_graded and ans:
                        is_correct = (ans.strip() == correct_ans.strip()) or (ans.strip()[:1] == correct_ans.strip()[:1])
                        if is_correct:
                            st.success(f"정답입니다! (선택한 답: {ans})")
                            score += 1
                            mark_wrong(q_id, 0)
                        else:
                            st.error(f"오답! (선택한 답: {ans}) / 정답: {correct_ans}")
                            st.info(f"해설: {solution}")
                            mark_wrong(q_id, 1)

                st.markdown("---")
                if st.button("🏁 최종 점수 확인하기"):
                    st.balloons()
                    st.metric(label=f"{selected_round} 최종 성적", value=f"{score} / {total_q} 문항 정답")

    # ================= 3. 오답 노트 =================
    elif menu == "오답 노트":
        st.header("📝 오답 노트")
        conn = sqlite3.connect(DB_FILE)
        wrongs = conn.execute("SELECT * FROM questions WHERE is_wrong = 1").fetchall()
        conn.close()

        if not wrongs:
            st.success("현재 틀린 문제가 없습니다. 아주 잘하고 계십니다!")
        else:
            st.info("틀린 문제들을 다시 풀고, 완벽히 맞히면 오답 노트에서 자동으로 해제됩니다.")
            for idx, q in enumerate(wrongs):
                q_id = q[0]
                round_name = q[1]
                raw_content = q[2]
                correct_ans = q[3]
                solution = q[4]

                try:
                    content_dict = json.loads(raw_content)
                    q_text = content_dict.get("question", raw_content)
                    options = content_dict.get("options", [])
                except:
                    q_text = raw_content
                    options = []

                st.markdown(f"---")
                st.markdown(f"**[{round_name}] 오답 문제 #{idx + 1} (ID: {q_id})**")
                st.markdown(q_text)

                saved_ans, saved_graded = load_wrong_progress(q_id)
                ans = saved_ans

                if options:
                    default_idx = None
                    if saved_ans in options:
                        default_idx = options.index(saved_ans)

                    selected_option = st.radio(
                        f"오답 다시 풀기 (ID: {q_id})", 
                        options, 
                        index=default_idx, 
                        key=f"wrong_radio_{q_id}"
                    )
                    
                    if selected_option and selected_option != saved_ans:
                        ans = selected_option
                        saved_graded = True
                        save_wrong_progress(q_id, ans, saved_graded)
                else:
                    ans = st.text_input(f"답안 입력 (ID: {q_id})", value=saved_ans if saved_ans else "", key=f"wrong_ans_{q_id}")
                    if st.button(f"정답 확인 (ID: {q_id})", key=f"wrong_btn_{q_id}"):
                        saved_graded = True
                        save_wrong_progress(q_id, ans, saved_graded)

                if saved_graded and ans:
                    is_correct = (ans.strip() == correct_ans.strip()) or (ans.strip()[:1] == correct_ans.strip()[:1])
                    if is_correct:
                        st.success(f"정답입니다! 🎉 완벽하게 이해하셨네요.")
                        mark_wrong(q_id, 0)
                        if st.button(f"🔄 오답노트에서 즉시 삭제하기 (ID: {q_id})", key=f"del_now_{q_id}"):
                            st.toast("오답노트에서 삭제되었습니다.", icon="🗑️")
                            st.rerun()
                    else:
                        st.error(f"오답입니다! (선택한 답: {ans}) / 정답: {correct_ans}")
                        st.info(f"해설: {solution}")

    # ================= 4. 문제 관리/수정 =================
    elif menu == "문제 관리/수정":
        st.header("🛠 문제 내용 및 정답/해설 수정")
        st.info("문제를 개별적으로 관리하고, 보기를 선택해 정답을 간편하게 수정할 수 있습니다.")
        
        conn = sqlite3.connect(DB_FILE)
        questions = conn.execute("SELECT * FROM questions").fetchall()
        conn.close()

        if not questions:
            st.info("수정할 문제가 없습니다.")
        else:
            for q in questions:
                q_id = q[0]
                round_name = q[1]
                raw_content = q[2]
                current_ans = q[3]
                current_sol = q[4]

                try:
                    cd = json.loads(raw_content)
                    q_text = cd.get("question", raw_content)
                    options = cd.get("options", [])
                except:
                    q_text = raw_content
                    options = []

                with st.expander(f"[{round_name}] 문제 ID: {q_id} 수정하기"):
                    new_content_text = st.text_area("문제 내용", value=q_text, key=f"c_text_{q_id}")
                    new_sol = st.text_area("해설 수정", value=current_sol, key=f"s_{q_id}")
                    
                    if st.button(f"문제 내용 및 해설 저장 (ID: {q_id})", key=f"save_content_{q_id}"):
                        updated_full_content = json.dumps({"question": new_content_text, "options": options}, ensure_ascii=False)
                        update_question_content_and_solution(q_id, updated_full_content, new_sol)
                        st.success("🎉 문제 내용과 해설이 성공적으로 수정되었습니다!")
                        st.toast("수정 완료!", icon="✏️")
                        st.rerun()

                    st.markdown("---")
                    st.markdown(f"**현재 설정된 정답:** `{current_ans}`")

                    if options:
                        ans_default_idx = 0
                        for i, opt in enumerate(options):
                            if current_ans.strip() in opt or (opt.strip() and current_ans.strip()[:1] == opt.strip()[:1]):
                                ans_default_idx = i
                                break

                        selected_new_ans = st.radio(
                            "정답으로 지정할 보기 선택", 
                            options, 
                            index=ans_default_idx, 
                            key=f"edit_ans_radio_{q_id}"
                        )
                        
                        if st.button(f"선택한 보기로 정답 변경 (ID: {q_id})", key=f"save_ans_{q_id}"):
                            update_question_answer(q_id, selected_new_ans)
                            st.success(f"🎉 정답이 '{selected_new_ans}'로 변경되었습니다!")
                            st.toast("정답 변경 완료!", icon="✨")
                            st.rerun()
                    else:
                        new_ans_text = st.text_input("정답 직접 입력", value=current_ans, key=f"edit_ans_input_{q_id}")
                        if st.button(f"정답 변경 (ID: {q_id})", key=f"save_ans_txt_{q_id}"):
                            update_question_answer(q_id, new_ans_text)
                            st.success("🎉 정답이 성공적으로 변경되었습니다!")
                            st.toast("정답 변경 완료!", icon="✨")
                            st.rerun()