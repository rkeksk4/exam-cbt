import streamlit as st
import sqlite3
import json
import os

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

# --- 데이터베이스(DB) 초기화 및 마이그레이션 ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS questions 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  round TEXT, 
                  question_number INTEGER,
                  content TEXT, 
                  correct_answer TEXT, 
                  solution TEXT, 
                  is_wrong INTEGER DEFAULT 0)''')
    
    # 기존 DB에 question_number 컬럼이 없을 경우 자동으로 추가하는 안전 장치
    try:
        c.execute("SELECT question_number FROM questions LIMIT 1")
    except sqlite3.OperationalError:
        c.execute("ALTER TABLE questions ADD COLUMN question_number INTEGER")

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

def get_existing_question_numbers(round_name):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        rows = c.execute("SELECT question_number FROM questions WHERE round = ?", (round_name,)).fetchall()
        conn.close()
        return [row[0] for row in rows if row[0] is not None]
    except sqlite3.OperationalError:
        init_db()
        return []

def save_question_direct(round_name, q_num, q_text, answer, solution):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO questions (round, question_number, content, correct_answer, solution, is_wrong) VALUES (?, ?, ?, ?, ?, 0)", 
              (round_name, q_num, q_text, answer, solution))
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
    st.sidebar.title("📚 학습 메뉴")
    menu = st.sidebar.radio("이동할 메뉴", ["문제 등록 (JSON)", "회차별 시험", "오답 노트", "문제 관리/수정"])

    # ================= 1. 문제 등록 (JSON 포맷) =================
    if menu == "문제 등록 (JSON)":
        st.header("📌 JSON 데이터로 신규 문제 등록")
        round_name = st.selectbox("회차 선택", ROUND_OPTIONS)

        existing_nums = get_existing_question_numbers(round_name)
        if existing_nums:
            st.info(f"💡 현재 **[{round_name}]**에 등록된 문제 번호: `{sorted(existing_nums)}`")

        st.markdown("---")
        
        # 세션 상태 초기화
        if "json_input_text" not in st.session_state:
            st.session_state["json_input_text"] = json.dumps([
               {
                  "question_number": 1,
                  "question_text": "예시 문제 본문 내용",
                  "options": [
                     "① 보기 1",
                     "② 보기 2",
                     "③ 보기 3",
                     "④ 보기 4",
                     "⑤ 보기 5"
                  ],
                  "answer": "①",
                  "solution": "해설 내용"
               }
            ], ensure_ascii=False, indent=4)

        # 1-1. JSON 파일 업로드 방식 (업로드 시 텍스트 상자에 반영)
        st.subheader("📁 JSON 파일 업로드")
        uploaded_json_file = st.file_uploader("문제가 담긴 JSON 파일을 업로드하세요", type=["json"])
        if uploaded_json_file is not None:
            try:
                file_content = uploaded_json_file.getvalue().decode("utf-8")
                parsed_temp = json.loads(file_content)
                st.session_state["json_input_text"] = json.dumps(parsed_temp, ensure_ascii=False, indent=4)
                st.success("📁 JSON 파일이 성공적으로 로드되었습니다! 아래 입력창에서 내용을 확인하신 뒤 DB 등록 버튼을 눌러주세요.")
                st.toast("JSON 파일 로드 완료!", icon="📂")
            except Exception as e:
                st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")

        st.markdown("---")
        st.subheader("✍️ JSON 데이터 입력 및 확인")

        # 텍스트 초기화 버튼
        if st.button("🗑️ 입력창 내용 비우기 (초기화)"):
            st.session_state["json_input_text"] = ""
            st.rerun()

        json_input_text = st.text_area("JSON 데이터 입력", value=st.session_state["json_input_text"], height=300, key="json_textarea_widget")
        
        # 텍스트 영역 값이 사용자에 의해 직접 수정될 때 세션 동기화
        if json_input_text != st.session_state["json_input_text"]:
            st.session_state["json_input_text"] = json_input_text

        if st.button("JSON 데이터 DB에 등록하기"):
            try:
                parsed_data = json.loads(st.session_state["json_input_text"])
                if not isinstance(parsed_data, list):
                    parsed_data = [parsed_data]
                
                current_existing = set(get_existing_question_numbers(round_name))
                input_nums = [q.get("question_number") for q in parsed_data if "question_number" in q]

                duplicates = [num for num in input_nums if num in current_existing]
                if len(input_nums) != len(set(input_nums)):
                    st.error("❌ 입력하신 JSON 데이터 내부에 중복된 문제 번호가 존재합니다.")
                elif duplicates:
                    st.error(f"❌ 이미 [{round_name}]에 존재하는 문제 번호(`{duplicates}`)가 포함되어 있어 등록이 취소되었습니다.")
                else:
                    count = 0
                    for q in parsed_data:
                        q_num = q.get("question_number")
                        q_text = q.get("question_text", "").strip()
                        opts = q.get("options", [])
                        full_content = json.dumps({"question": q_text, "options": opts}, ensure_ascii=False)
                        a_text = str(q.get("answer", "")).strip()
                        s_text = q.get("solution", "").strip()
                        
                        if q_text and q_num is not None:
                            save_question_direct(round_name, q_num, full_content, a_text, s_text)
                            count += 1

                    st.success(f"🎉 성공적으로 {count}개의 문제가 [{round_name}]에 등록되었습니다!")
                    st.toast("문제 등록 완료!", icon="✅")
                    st.rerun()

            except json.JSONDecodeError as e:
                st.error(f"JSON 형식이 올바르지 않습니다. 문법을 확인해주세요. 오류: {e}")
            except Exception as e:
                st.error(f"데이터 등록 중 오류가 발생했습니다: {e}")

        st.markdown("---")
        st.subheader("💾 데이터 백업 및 복구")
        
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
        
        try:
            conn = sqlite3.connect(DB_FILE)
            total_q_count = conn.execute("SELECT COUNT(*) FROM questions WHERE round = ?", (selected_round,)).fetchone()[0]
            has_history = conn.execute("SELECT COUNT(*) FROM user_progress WHERE round = ?", (selected_round,)).fetchone()[0] > 0
            conn.close()
        except sqlite3.OperationalError:
            init_db()
            total_q_count = 0
            has_history = False

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
            questions = conn.execute("SELECT * FROM questions WHERE round = ? ORDER BY question_number ASC", (selected_round,)).fetchall()
            conn.close()

            score = 0
            total_q = len(questions)

            if not questions:
                st.warning("해당 회차에 등록된 문제가 없습니다. '문제 등록 (JSON)' 메뉴에서 먼저 문제를 추가해주세요.")
            else:
                for q in questions:
                    q_id = q[0]
                    q_num = q[2]
                    raw_content = q[3]
                    correct_ans = q[4]
                    solution = q[5]

                    try:
                        content_dict = json.loads(raw_content)
                        q_text = content_dict.get("question", raw_content)
                        options = content_dict.get("options", [])
                    except:
                        q_text = raw_content
                        options = []

                    st.markdown(f"---")
                    st.markdown(f"**[문제 {q_num}번] (ID: {q_id})**")
                    st.markdown(q_text)
                    
                    saved_ans, saved_graded = load_progress(selected_round, q_id)
                    ans = saved_ans

                    if options:
                        default_idx = None
                        if saved_ans in options:
                            default_idx = options.index(saved_ans)

                        selected_option = st.radio(
                            f"보기 선택 ({q_num}번)", 
                            options, 
                            index=default_idx, 
                            key=f"radio_{q_id}"
                        )
                        
                        if selected_option and selected_option != saved_ans:
                            ans = selected_option
                            saved_graded = True
                            save_progress(selected_round, q_id, ans, saved_graded)
                    else:
                        ans = st.text_input(f"답안 입력 ({q_num}번)", value=saved_ans if saved_ans else "", key=f"ans_{q_id}")
                        if st.button(f"채점 및 확인 ({q_num}번)", key=f"grade_btn_{q_id}"):
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
        try:
            conn = sqlite3.connect(DB_FILE)
            wrongs = conn.execute("SELECT * FROM questions WHERE is_wrong = 1 ORDER BY round, question_number ASC").fetchall()
            conn.close()
        except sqlite3.OperationalError:
            init_db()
            wrongs = []

        if not wrongs:
            st.success("현재 틀린 문제가 없습니다. 아주 잘하고 계십니다!")
        else:
            st.info("틀린 문제들을 다시 풀고, 완벽히 맞히면 오답 노트에서 자동으로 해제됩니다.")
            for q in wrongs:
                q_id = q[0]
                round_name = q[1]
                q_num = q[2]
                raw_content = q[3]
                correct_ans = q[4]
                solution = q[5]

                try:
                    content_dict = json.loads(raw_content)
                    q_text = content_dict.get("question", raw_content)
                    options = content_dict.get("options", [])
                except:
                    q_text = raw_content
                    options = []

                st.markdown(f"---")
                st.markdown(f"**[{round_name}] 문제 {q_num}번 (ID: {q_id})**")
                st.markdown(q_text)

                saved_ans, saved_graded = load_wrong_progress(q_id)
                ans = saved_ans

                if options:
                    default_idx = None
                    if saved_ans in options:
                        default_idx = options.index(saved_ans)

                    selected_option = st.radio(
                        f"오답 다시 풀기 ({round_name} {q_num}번)", 
                        options, 
                        index=default_idx, 
                        key=f"wrong_radio_{q_id}"
                    )
                    
                    if selected_option and selected_option != saved_ans:
                        ans = selected_option
                        saved_graded = True
                        save_wrong_progress(q_id, ans, saved_graded)
                else:
                    ans = st.text_input(f"답안 입력 ({round_name} {q_num}번)", value=saved_ans if saved_ans else "", key=f"wrong_ans_{q_id}")
                    if st.button(f"정답 확인 ({round_name} {q_num}번)", key=f"wrong_btn_{q_id}"):
                        saved_graded = True
                        save_wrong_progress(q_id, ans, saved_graded)

                if saved_graded and ans:
                    is_correct = (ans.strip() == correct_ans.strip()) or (ans.strip()[:1] == correct_ans.strip()[:1])
                    if is_correct:
                        st.success(f"정답입니다! 🎉 완벽하게 이해하셨네요.")
                        mark_wrong(q_id, 0)
                        if st.button(f"🔄 오답노트에서 즉시 삭제하기 ({round_name} {q_num}번)", key=f"del_now_{q_id}"):
                            st.toast("오답노트에서 삭제되었습니다.", icon="🗑️")
                            st.rerun()
                    else:
                        st.error(f"오답입니다! (선택한 답: {ans}) / 정답: {correct_ans}")
                        st.info(f"해설: {solution}")

    # ================= 4. 문제 관리/수정 =================
    elif menu == "문제 관리/수정":
        st.header("🛠 문제 내용 및 정답/해설 수정")
        st.info("문제를 개별적으로 관리하고, 보기를 선택해 정답을 간편하게 수정할 수 있습니다.")
        
        # --- 회차별 데이터 초기화 구역 (안전 장치 포함) ---
        with st.expander("⚠️ 위험 구역: 회차별 데이터 초기화"):
            reset_round_target = st.selectbox("초기화할 회차 선택", ROUND_OPTIONS, key="reset_target_round")
            confirm_checkbox = st.checkbox(f"[{reset_round_target}]의 모든 문제와 풀이 기록을 영구적으로 삭제하는 것에 동의합니다.")
            
            if st.button(f"🗑️ [{reset_round_target}] 데이터 완전 초기화 실행"):
                if confirm_checkbox:
                    reset_round_questions(reset_round_target)
                    st.success(f"[{reset_round_target}]의 모든 데이터와 기록이 초기화되었습니다!")
                    st.toast("초기화 완료!", icon="🗑️")
                    st.rerun()
                else:
                    st.error("❌ 초기화를 진행하려면 상단의 동의 체크박스를 체크해주세요.")

        st.markdown("---")

        try:
            conn = sqlite3.connect(DB_FILE)
            questions = conn.execute("SELECT * FROM questions ORDER BY round, question_number ASC").fetchall()
            conn.close()
        except sqlite3.OperationalError:
            init_db()
            questions = []

        if not questions:
            st.info("수정할 문제가 없습니다.")
        else:
            for q in questions:
                q_id = q[0]
                round_name = q[1]
                q_num = q[2]
                raw_content = q[3]
                current_ans = q[4]
                current_sol = q[5]

                try:
                    cd = json.loads(raw_content)
                    q_text = cd.get("question", raw_content)
                    options = cd.get("options", [])
                except:
                    q_text = raw_content
                    options = []

                with st.expander(f"[{round_name}] 문제 {q_num}번 (ID: {q_id}) 수정하기"):
                    new_content_text = st.text_area("문제 내용", value=q_text, key=f"c_text_{q_id}")
                    new_sol = st.text_area("해설 수정", value=current_sol, key=f"s_{q_id}")
                    
                    if st.button(f"문제 내용 및 해설 저장 ({round_name} {q_num}번)", key=f"save_content_{q_id}"):
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
                        
                        if st.button(f"선택한 보기로 정답 변경 ({round_name} {q_num}번)", key=f"save_ans_{q_id}"):
                            update_question_answer(q_id, selected_new_ans)
                            st.success(f"🎉 정답이 '{selected_new_ans}'로 변경되었습니다!")
                            st.toast("정답 변경 완료!", icon="✨")
                            st.rerun()
                    else:
                        new_ans_text = st.text_input("정답 직접 입력", value=current_ans, key=f"edit_ans_input_{q_id}")
                        if st.button(f"정답 변경 ({round_name} {q_num}번)", key=f"save_ans_txt_{q_id}"):
                            update_question_answer(q_id, new_ans_text)
                            st.success("🎉 정답이 성공적으로 변경되었습니다!")
                            st.toast("정답 변경 완료!", icon="✨")
                            st.rerun()
