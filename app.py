import streamlit as st
from google import genai
import sqlite3
import json

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

# --- 데이터베이스(DB) 초기화 ---
def init_db():
    conn = sqlite3.connect("question_bank.db")
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
    conn.commit()
    conn.close()

init_db()

def save_question(round_name, content, answer, solution):
    conn = sqlite3.connect("question_bank.db")
    c = conn.cursor()
    c.execute("INSERT INTO questions (round, content, correct_answer, solution, is_wrong) VALUES (?, ?, ?, ?, 0)", 
              (round_name, content, answer, solution))
    conn.commit()
    conn.close()

def update_question(q_id, content, answer, solution):
    conn = sqlite3.connect("question_bank.db")
    c = conn.cursor()
    c.execute("UPDATE questions SET content=?, correct_answer=?, solution=? WHERE id=?", 
              (content, answer, solution, q_id))
    conn.commit()
    conn.close()

def mark_wrong(q_id, status):
    conn = sqlite3.connect("question_bank.db")
    c = conn.cursor()
    c.execute("UPDATE questions SET is_wrong = ? WHERE id = ?", (status, q_id))
    conn.commit()
    conn.close()

def load_progress(round_name, q_id):
    conn = sqlite3.connect("question_bank.db")
    c = conn.cursor()
    c.execute("SELECT user_answer, is_graded FROM user_progress WHERE round = ? AND question_id = ?", (round_name, q_id))
    row = c.fetchone()
    conn.close()
    if row:
        return row[0], bool(row[1])
    return None, False

def save_progress(round_name, q_id, user_answer, is_graded):
    conn = sqlite3.connect("question_bank.db")
    c = conn.cursor()
    c.execute('''INSERT INTO user_progress (round, question_id, user_answer, is_graded) 
                 VALUES (?, ?, ?, ?) 
                 ON CONFLICT(round, question_id) 
                 DO UPDATE SET user_answer = ?, is_graded = ?''', 
              (round_name, q_id, user_answer, int(is_graded), user_answer, int(is_graded)))
    conn.commit()
    conn.close()

def clear_progress(round_name):
    conn = sqlite3.connect("question_bank.db")
    c = conn.cursor()
    c.execute("DELETE FROM user_progress WHERE round = ?", (round_name,))
    conn.commit()
    conn.close()

def reset_all_questions():
    conn = sqlite3.connect("question_bank.db")
    c = conn.cursor()
    c.execute("DELETE FROM questions")
    c.execute("DELETE FROM user_progress")
    conn.commit()
    conn.close()

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 로그인 필요")
        pwd = st.text_input("앱 잠금 해제 비밀번호를 입력하세요", type="password")
        if pwd == st.secrets.get("APP_PASSWORD"):
            st.session_state["password_correct"] = True
            st.rerun()
        elif pwd:
            st.error("비밀번호가 틀렸습니다.")
        return False
    return True

if check_password():
    client = genai.Client(api_key=st.secrets.get("GEMINI_API_KEY"))

    st.sidebar.title("📚 학습 메뉴")
    menu = st.sidebar.radio("이동할 메뉴", ["문제 등록", "회차별 시험", "오답 노트", "문제 관리/수정"])

    # ================= 1. 문제 등록 =================
    if menu == "문제 등록":
        st.header("📌 신규 문제 등록 (사진/PDF)")
        round_name = st.selectbox("회차 선택", ["1회차", "2회차", "3회차", "4회차", "5회차", "기타"])
        
        if st.button("⚠️ 기존 등록된 모든 문제 데이터 초기화하기"):
            reset_all_questions()
            st.success("모든 문제가 초기화되었습니다!")
            st.rerun()

        uploaded_file = st.file_uploader("문제 사진 또는 PDF 업로드", type=["jpg", "jpeg", "png", "pdf"])
        
        if st.button("AI 분석 및 DB 저장"):
            if uploaded_file:
                with st.spinner("AI가 문제를 분석하고 보기를 분리하는 중..."):
                    try:
                        file_bytes = uploaded_file.getvalue()
                        mime_type = uploaded_file.type

                        response = client.models.generate_content(
                            model="gemini-3.5-flash",
                            contents=[
                                {
                                    "inline_data": {
                                        "data": file_bytes,
                                        "mime_type": mime_type
                                    }
                                },
                                """
                                이 자료(이미지/PDF)에 포함된 모든 문제를 각각 독립적인 낱개 문제로 완벽하게 분리해서 추출해줘.
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
                        )
                        raw_text = response.text.strip()
                        
                        if raw_text.startswith("```json"):
                            raw_text = raw_text[7:]
                        if raw_text.startswith("```"):
                            raw_text = raw_text[3:]
                        if raw_text.endswith("```"):
                            raw_text = raw_text[:-3]
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

                        st.success(f"총 {count}개의 문제가 클릭형 보기 구조로 완벽하게 분리되어 등록되었습니다!")
                        
                    except Exception as e:
                        st.error(f"AI 분석 중 오류가 발생했습니다: {e}")
            else:
                st.warning("파일을 업로드해주세요.")

    # ================= 2. 회차별 시험 =================
    elif menu == "회차별 시험":
        st.header("🎯 회차별 시험 풀기")
        conn = sqlite3.connect("question_bank.db")
        rounds = [r[0] for r in conn.execute("SELECT DISTINCT round FROM questions").fetchall()]
        conn.close()
        
        if not rounds:
            st.info("등록된 문제가 없습니다. '문제 등록' 메뉴에서 먼저 문제를 추가해주세요.")
        else:
            selected_round = st.selectbox("풀어볼 회차 선택", rounds)
            
            conn = sqlite3.connect("question_bank.db")
            has_history = conn.execute("SELECT COUNT(*) FROM user_progress WHERE round = ?", (selected_round,)).fetchone()[0] > 0
            conn.close()

            mode = "이어서 풀기"
            if has_history:
                st.markdown("---")
                st.info(f"📌 **{selected_round}**에 이전에 풀던 기록이 존재합니다.")
                mode = st.radio("학습 방식을 선택하세요:", ["이어서 풀기", "처음부터 새로 풀기"], horizontal=True, key="mode_select")
                
                if mode == "처음부터 새로 풀기":
                    if st.button("🔄 기존 기록 초기화하고 새로 시작하기"):
                        clear_progress(selected_round)
                        st.success("기록이 초기화되었습니다. 잠시 후 새로 시작합니다!")
                        st.rerun()

            if mode == "이어서 풀기" or not has_history:
                conn = sqlite3.connect("question_bank.db")
                questions = conn.execute("SELECT * FROM questions WHERE round = ?", (selected_round,)).fetchall()
                conn.close()

                score = 0
                total_q = len(questions)

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
                        # 💡 저장된 답안이 있으면 해당 인덱스를 지정하고, 없으면 None으로 지정하여 초기에 아무것도 선택되지 않게 함
                        default_idx = None
                        if saved_ans in options:
                            default_idx = options.index(saved_ans)

                        selected_option = st.radio(
                            f"보기 선택 (ID: {q_id})", 
                            options, 
                            index=default_idx, 
                            key=f"radio_{q_id}"
                        )
                        
                        # 사용자가 실제로 보기를 클릭했을 때만 채점 상태로 전환
                        if selected_option and selected_option != saved_ans:
                            ans = selected_option
                            saved_graded = True
                            save_progress(selected_round, q_id, ans, saved_graded)
                    else:
                        ans = st.text_input(f"답안 입력", value=saved_ans if saved_ans else "", key=f"ans_{q_id}")
                        if st.button(f"채점 및 확인 (ID: {q_id})", key=f"grade_btn_{q_id}"):
                            saved_graded = True
                            save_progress(selected_round, q_id, ans, saved_graded)

                    # 💡 채점이 완료된 경우에만 정답/해설 노출
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
        conn = sqlite3.connect("question_bank.db")
        wrongs = conn.execute("SELECT * FROM questions WHERE is_wrong = 1").fetchall()
        conn.close()

        if not wrongs:
            st.success("현재 틀린 문제가 없습니다. 아주 잘하고 계십니다!")
        else:
            st.info("틀린 문제들을 다시 풀고, 완벽히 이해했다면 오답 노트에서 제거할 수 있습니다.")
            for q in wrongs:
                try:
                    content_dict = json.loads(q[2])
                    q_text = content_dict.get("question", q[2])
                except:
                    q_text = q[2]

                with st.expander(f"[{q[1]}] 오답 문제 (ID: {q[0]})"):
                    st.markdown(f"**문제 내용:**\n{q_text}")
                    st.markdown(f"**정답:** {q[3]}")
                    st.info(f"**해설:** {q[4]}")

                    if st.button(f"🗑 오답 노트에서 이 문제 제거하기", key=f"del_{q[0]}"):
                        mark_wrong(q[0], 0)
                        st.success("오답 노트에서 제거되었습니다.")
                        st.rerun()

    # ================= 4. 문제 관리/수정 =================
    elif menu == "문제 관리/수정":
        st.header("🛠 문제 내용 및 정답/해설 수정")
        st.info("문제를 개별적으로 관리하고 수정할 수 있습니다.")
        
        conn = sqlite3.connect("question_bank.db")
        questions = conn.execute("SELECT * FROM questions").fetchall()
        conn.close()

        if not questions:
            st.info("수정할 문제가 없습니다.")
        else:
            for q in questions:
                try:
                    cd = json.loads(q[2])
                    display_content = cd.get("question", q[2])
                except:
                    display_content = q[2]

                with st.expander(f"[{q[1]}] 문제 ID: {q[0]} 수정하기"):
                    new_content = st.text_area("문제 내용", value=display_content, key=f"c_{q[0]}")
                    new_ans = st.text_input("정답", value=q[3], key=f"a_{q[0]}")
                    new_sol = st.text_area("해설", value=q[4], key=f"s_{q[0]}")
                    
                    if st.button(f"변경사항 저장 (ID: {q[0]})", key=f"save_{q[0]}"):
                        update_question(q[0], new_content, new_ans, new_sol)
                        st.success("성공적으로 수정되었습니다!")
                        st.rerun()