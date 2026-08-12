import streamlit as st
import sqlite3
import json
import os

# --- 페이지 설정 ---
st.set_page_config(page_title="JSON 문제은행 시스템", layout="centered")

# CSS 스타일링
st.markdown("""
    <style>
    .stButton>button { width: 100%; }
    .stExpander { background-color: #f9f9f9; }
    </style>
    """, unsafe_allow_html=True)

DB_FILE = "question_bank.db"

# --- DB 초기화 ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS questions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, round TEXT, content TEXT, 
                  correct_answer TEXT, solution TEXT, is_wrong INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_progress 
                 (round TEXT, question_id INTEGER, user_answer TEXT, is_graded INTEGER DEFAULT 0,
                  PRIMARY KEY(round, question_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS wrong_progress 
                 (question_id INTEGER PRIMARY KEY, user_answer TEXT, is_graded INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

# --- 도우미 함수 ---
def save_json_to_db(json_data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    count = 0
    for q in json_data:
        round_val = q.get("round", "1회차")
        q_text = q.get("question_text", "").strip()
        opts = q.get("options", [])
        full_content = json.dumps({"question": q_text, "options": opts}, ensure_ascii=False)
        answer = str(q.get("answer", "")).strip()
        solution = q.get("solution", "").strip()
        
        c.execute("INSERT INTO questions (round, content, correct_answer, solution) VALUES (?, ?, ?, ?)", 
                  (round_val, full_content, answer, solution))
        count += 1
    conn.commit()
    conn.close()
    return count

# --- 사이드바 메뉴 ---
st.sidebar.title("📚 학습 메뉴")
menu = st.sidebar.radio("이동할 메뉴", ["문제 등록", "회차별 시험", "오답 노트", "문제 관리/수정"])

# 1. 문제 등록
if menu == "문제 등록":
    st.header("📌 JSON 파일로 문제 등록")
    st.info("JSON 파일을 업로드하여 문제를 일괄 등록합니다.\n\n"
            "형식: `[{'round': '1회차', 'question_text': '...', 'options': [...], 'answer': '...', 'solution': '...'}]`")
    
    uploaded_file = st.file_uploader("JSON 파일 선택", type=["json"])
    
    if uploaded_file and st.button("데이터 등록하기"):
        try:
            data = json.load(uploaded_file)
            count = save_json_to_db(data)
            st.success(f"🎉 총 {count}개의 문제가 성공적으로 등록되었습니다!")
        except Exception as e:
            st.error(f"오류 발생: {e}")

    if st.button("⚠️ 모든 데이터 초기화"):
        conn = sqlite3.connect(DB_FILE)
        conn.execute("DELETE FROM questions")
        conn.execute("DELETE FROM user_progress")
        conn.execute("DELETE FROM wrong_progress")
        conn.commit()
        conn.close()
        st.warning("모든 문제가 삭제되었습니다.")
        st.rerun()

# 2. 회차별 시험
elif menu == "회차별 시험":
    st.header("🎯 시험 풀기")
    rounds = [r[0] for r in sqlite3.connect(DB_FILE).execute("SELECT DISTINCT round FROM questions").fetchall()]
    if not rounds:
        st.warning("등록된 문제가 없습니다.")
    else:
        sel_round = st.selectbox("회차 선택", rounds)
        conn = sqlite3.connect(DB_FILE)
        questions = conn.execute("SELECT * FROM questions WHERE round = ?", (sel_round,)).fetchall()
        conn.close()

        for q in questions:
            q_id, r_name, raw_content, correct, sol, _ = q
            content = json.loads(raw_content)
            st.markdown(f"**문제:** {content['question']}")
            
            user_ans = st.radio(f"보기 (ID:{q_id})", content['options'], key=f"q_{q_id}")
            if st.button("정답 확인", key=f"btn_{q_id}"):
                if user_ans == correct:
                    st.success("정답입니다!")
                else:
                    st.error(f"오답! 정답: {correct}\n\n해설: {sol}")
                    conn = sqlite3.connect(DB_FILE)
                    conn.execute("UPDATE questions SET is_wrong = 1 WHERE id = ?", (q_id,))
                    conn.commit()
                    conn.close()

# 3. 오답 노트
elif menu == "오답 노트":
    st.header("📝 오답 노트")
    conn = sqlite3.connect(DB_FILE)
    wrongs = conn.execute("SELECT * FROM questions WHERE is_wrong = 1").fetchall()
    conn.close()
    
    if not wrongs:
        st.success("틀린 문제가 없습니다!")
    else:
        for q in wrongs:
            q_id, _, raw_content, correct, sol, _ = q
            content = json.loads(raw_content)
            st.write(f"**문제:** {content['question']}")
            if st.button(f"오답 해제 (ID:{q_id})"):
                conn = sqlite3.connect(DB_FILE)
                conn.execute("UPDATE questions SET is_wrong = 0 WHERE id = ?", (q_id,))
                conn.commit()
                conn.close()
                st.rerun()

# 4. 문제 관리/수정
elif menu == "문제 관리/수정":
    st.header("🛠 문제 수정")
    conn = sqlite3.connect(DB_FILE)
    questions = conn.execute("SELECT * FROM questions").fetchall()
    conn.close()
    
    for q in questions:
        q_id, r_name, raw_content, correct, sol, _ = q
        with st.expander(f"[{r_name}] 문제 ID: {q_id}"):
            new_sol = st.text_area("해설 수정", value=sol, key=f"sol_{q_id}")
            if st.button("저장", key=f"save_{q_id}"):
                conn = sqlite3.connect(DB_FILE)
                conn.execute("UPDATE questions SET solution = ? WHERE id = ?", (new_sol, q_id))
                conn.commit()
                conn.close()
                st.success("수정 완료!")
                st.rerun()