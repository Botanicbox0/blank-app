import streamlit as st
import whisper
import tempfile
import os
import json
import requests
import numpy as np
from datetime import datetime
import time
import re
from io import BytesIO
import base64

# 페이지 설정
st.set_page_config(page_title="브랜드 세일즈 미팅록 자동화", page_icon="🎙️", layout="wide")

# 브랜드 이름 추출 함수 (함수 정의를 상단으로 이동)
def extract_brand_name(text):
    # 브랜드명 추출 시도
    brand_patterns = [
        r'브랜드(?:명|는|측)?\s*(?:은|는|:)?\s*[\"\'"]?([^,\.\"\']+)[\"\'"]?',
        r'([^,\.]+)?\s*브랜드',
        r'([^,\.]+)?\s*회사'
    ]
    
    for pattern in brand_patterns:
        matches = re.findall(pattern, text)
        if matches:
            # 가장 긴 매치를 선택 (보통 더 완전한 이름)
            return max(matches, key=len).strip()
    
    return "미확인 브랜드"

# 요약 함수 (Claude API 사용) (함수 정의를 상단으로 이동)
def summarize_with_claude(transcript, api_key, meeting_info):
    if not api_key:
        return "Claude API 키가 제공되지 않았습니다."
    
    # 미팅 정보 구성
    company_name = meeting_info.get("company_name", "브랜더진")
    our_participants = meeting_info.get("our_participants", "")
    meeting_date = meeting_info.get("meeting_date", datetime.now().strftime("%Y-%m-%d"))
    brand_name = meeting_info.get("brand_name", "")
    
    # Claude API 요청 데이터
    prompt = f"""
너에게 브랜드 세일즈 미팅록을 전달했어. 너는 브랜드 세일즈 미팅록을 요약하여 세일즈포스에 기입할거야. 적절하게 우리의 Knowledge로 만들 수 있도록 요약본을 만들어 줘야해.

(초반에 {company_name}에 대해 설명하는 Participant는 우리 세일즈맨이야. 우리 팀원 얘기 보다는 다른 Participant(고객) 목소리를 좀 더 담아서 요약 부탁.)

💡 요약 시 포함할 내용:
1. 미팅 개요: 미팅 날짜({meeting_date}), 참석자 (우리 측 & 브랜드 측), 브랜드명 및 담당자 역할
2. 브랜드 배경: 브랜드의 마케팅 및 세일즈 현황, 현재 고민 또는 니즈
3. (이 내역은 각각 구조화해서 작성해줘.) 
   A. 마케터 인원수 혹은 구성 
   B. 전체 마케팅 중 인플루언서 마케팅의 비중은 어느 정도인지 
   C. 예산 책정 방식 
   D. 이외에 어떤 마케팅을 전개하고 있는지 / 어떤 업무에 리소스를 투여하고 있는지
4. 미팅 주요 논의 사항: 브랜드가 관심을 가진 서비스, 협업 가능성, 가격 협상 여부, 요청 사항
5. 결론 및 액션 아이템: 브랜드의 관심 수준 (Hot, Warm, Cold), 다음 단계, 우리가 해야 할 일, 브랜드가 해야 할 일

📌 간결하고 핵심적인 내용으로 정리하되, 의미가 명확하게 전달될 수 있도록 작성할 것.
📌 목록 형식(Bullet Points) 또는 구조화된 섹션으로 정리하여 가독성을 높일 것.

우리 측 참석자: {our_participants}
브랜드명: {brand_name}

미팅록 내용:
{transcript}
"""
    
    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }
    
    data = {
        "model": "claude-3-haiku-20240307",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 4000
    }
    
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=data
        )
        response.raise_for_status()
        
        result = response.json()
        summary = result["content"][0]["text"]
        return summary
    except Exception as e:
        return f"요약 생성 중 오류 발생: {str(e)}"

# Whisper 모델 로드
@st.cache_resource
def load_whisper_model(model_size):
    try:
        return whisper.load_model(model_size)
    except Exception as e:
        st.error(f"모델 로드 실패: {e}")
        return None

# 실시간 녹음을 위한 JavaScript 코드
def get_audio_recorder_html():
    return """
    <style>
    .button {
        background-color: #4CAF50;
        border: none;
        color: white;
        padding: 15px 32px;
        text-align: center;
        text-decoration: none;
        display: inline-block;
        font-size: 16px;
        margin: 4px 2px;
        cursor: pointer;
        border-radius: 8px;
    }
    .button.recording {
        background-color: #f44336;
    }
    .time-display {
        font-size: 24px;
        margin: 15px 0;
    }
    </style>
    <div id="audio-recorder">
        <button id="record-button" class="button">녹음 시작</button>
        <div id="time-display" class="time-display">00:00:00</div>
        <audio id="audio-playback" controls style="display:none;"></audio>
        <a id="download-link" style="display:none; margin-top: 15px;" class="button">녹음 다운로드</a>
        <p id="instruction" style="display:none; margin-top: 15px; font-weight: bold; color: #4CAF50;">
            1. 녹음 파일을 다운로드한 후 <br>
            2. '파일 업로드' 탭으로 이동하여 방금 다운로드한 파일을 업로드하세요.
        </p>
    </div>

    <script>
        const recordButton = document.getElementById('record-button');
        const timeDisplay = document.getElementById('time-display');
        const audioPlayback = document.getElementById('audio-playback');
        const downloadLink = document.getElementById('download-link');
        const instruction = document.getElementById('instruction');
        
        let mediaRecorder;
        let audioChunks = [];
        let startTime;
        let timerInterval;
        let audioBlob;
        
        function updateTimer() {
            const now = new Date();
            const elapsedTime = now - startTime;
            const hours = Math.floor(elapsedTime / 3600000).toString().padStart(2, '0');
            const minutes = Math.floor((elapsedTime % 3600000) / 60000).toString().padStart(2, '0');
            const seconds = Math.floor((elapsedTime % 60000) / 1000).toString().padStart(2, '0');
            timeDisplay.textContent = `${hours}:${minutes}:${seconds}`;
        }
        
        recordButton.addEventListener('click', async () => {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                // 녹음 중지
                mediaRecorder.stop();
                recordButton.textContent = '새로 녹음하기';
                recordButton.classList.remove('recording');
                clearInterval(timerInterval);
            } else {
                // 녹음 시작
                audioChunks = [];
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                
                mediaRecorder.ondataavailable = (event) => {
                    audioChunks.push(event.data);
                };
                
                mediaRecorder.onstop = () => {
                    // 녹음된 오디오 처리
                    audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                    const audioUrl = URL.createObjectURL(audioBlob);
                    audioPlayback.src = audioUrl;
                    audioPlayback.style.display = 'block';
                    
                    // 다운로드 링크 생성
                    downloadLink.href = audioUrl;
                    downloadLink.download = 'recording.wav';
                    downloadLink.style.display = 'block';
                    downloadLink.textContent = '녹음 파일 다운로드';
                    
                    // 안내 메시지 표시
                    instruction.style.display = 'block';
                    
                    // 오디오 트랙 중지
                    stream.getTracks().forEach(track => track.stop());
                };
                
                mediaRecorder.start(100);  // 100ms마다 데이터 수집
                startTime = new Date();
                timerInterval = setInterval(updateTimer, 1000);
                recordButton.textContent = '녹음 중지';
                recordButton.classList.add('recording');
                
                // 녹음 시작 시 재생 및 다운로드 요소 숨기기
                audioPlayback.style.display = 'none';
                downloadLink.style.display = 'none';
                instruction.style.display = 'none';
            }
        });
    </script>
    """

# 타이틀 및 설명
st.title("🎙️ Brandazine Sales Meeting Notetaker")
st.markdown("""
이 앱은 브랜드 세일즈 미팅을 실시간으로 녹음하거나 기존 녹음을 업로드하여 텍스트로 변환하고 요약합니다. (Created by 윤병삼)
1. 녹음을 진행하고 오디오 파일을 다운로드합니다.
2. 업로드 탭에서 오디오 파일을 업로드하여 텍스트로 변환하고 요약합니다.
3. 또는 텍스트를 직접 입력하여 요약을 생성할 수 있습니다.
""")

# 탭 생성
tab1, tab2, tab3 = st.tabs(["녹음하기", "파일 업로드", "텍스트 직접 입력"])

# Claude API 키 입력
with st.sidebar:
    st.header("설정")
    claude_api_key = st.text_input("Claude API 키", type="password")
    st.markdown("---")
    st.subheader("Whisper 모델 (음성 변환용)")
    model_size = st.selectbox("모델 크기", ["tiny", "base", "small", "medium", "large"], index=1)
    st.markdown("---")
    st.subheader("브랜드 미팅 정보")
    our_company_name = st.text_input("자사명", value="브랜더진")
    our_participants = st.text_input("자사 참석자 (쉼표로 구분)")
    meeting_date = st.date_input("미팅 날짜", datetime.now())
    brand_name = st.text_input("브랜드명 (자동 추출되지 않을 경우 사용)")

# 녹음 탭
with tab1:
    st.header("녹음하기")
    st.markdown("아래 버튼을 클릭하여 브랜드 미팅을 녹음하세요. 녹음이 완료되면 다운로드 링크가 나타납니다.")
    
    # 오디오 레코더 HTML 삽입
    st.components.v1.html(get_audio_recorder_html(), height=250)
    
    st.markdown("""
    ---
    ### 📝 사용 방법
    1. **녹음 시작** 버튼을 클릭하여 녹음을 시작합니다.
    2. 녹음이 끝나면 **녹음 중지** 버튼을 클릭합니다.
    3. 녹음 파일을 다운로드합니다.
    4. **파일 업로드** 탭으로 이동하여 방금 다운로드한 파일을 업로드합니다.
    """)

# 파일 업로드 탭
with tab2:
    st.header("파일 업로드")
    
    # 안내 메시지 추가
    st.info("녹음 파일 또는 기존 오디오 파일을 업로드하여 텍스트로 변환하고 요약합니다.")
    
    uploaded_file = st.file_uploader("오디오 파일(.mp3, .wav, .m4a) 또는 텍스트 파일(.txt) 선택", 
                                     type=["mp3", "wav", "m4a", "txt"])
    
    if uploaded_file is not None:
        file_extension = uploaded_file.name.split('.')[-1].lower()
        
        # 처리 버튼
        process_button = st.button("텍스트 변환 및 요약 시작", key="process_upload")
        
        if process_button:
            if file_extension in ['mp3', 'wav', 'm4a']:
                # 오디오 파일 처리
                st.success(f"오디오 파일 '{uploaded_file.name}'을(를) 처리합니다.")
                
                # 임시 파일로 저장
                with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_extension}") as temp_file:
                    temp_file.write(uploaded_file.getbuffer())
                    temp_filename = temp_file.name
                
                # Whisper 모델 로드
                model = load_whisper_model(model_size)
                if not model:
                    st.error("Whisper 모델을 로드할 수 없습니다.")
                else:
                    # 오디오 파일에서 텍스트 변환
                    with st.spinner("오디오를 텍스트로 변환 중..."):
                        result = model.transcribe(temp_filename, language="ko")
                        transcript = result["text"]
                        
                        # 텍스트 표시
                        st.subheader("변환된 텍스트")
                        st.text_area("전체 텍스트", transcript, height=200)
                        
                        # 브랜드명 추출 시도
                        extracted_brand_name = extract_brand_name(transcript)
                        final_brand_name = brand_name or extracted_brand_name
                        
                        # 미팅 정보 구성
                        meeting_info = {
                            "company_name": our_company_name,
                            "our_participants": our_participants,
                            "meeting_date": meeting_date.strftime("%Y-%m-%d"),
                            "brand_name": final_brand_name
                        }
                        
                        # 요약 생성
                        if claude_api_key:
                            with st.spinner("Claude API로 요약 생성 중..."):
                                summary = summarize_with_claude(transcript, claude_api_key, meeting_info)
                            
                            st.subheader("📋 브랜드 세일즈 미팅 요약")
                            st.markdown(summary)
                            
                            # 요약본 다운로드 버튼
                            col1, col2 = st.columns(2)
                            with col1:
                                st.download_button(
                                    label="요약본 다운로드 (.txt)",
                                    data=summary,
                                    file_name=f"브랜드미팅요약_{meeting_date.strftime('%Y%m%d')}_{final_brand_name}.txt",
                                    mime="text/plain"
                                )
                            with col2:
                                st.download_button(
                                    label="요약본 다운로드 (.md)",
                                    data=summary,
                                    file_name=f"브랜드미팅요약_{meeting_date.strftime('%Y%m%d')}_{final_brand_name}.md",
                                    mime="text/markdown"
                                )
                        else:
                            st.warning("요약을 생성하려면 Claude API 키를 입력하세요.")
                
                # 임시 파일 삭제
                try:
                    os.remove(temp_filename)
                except:
                    pass
            
            elif file_extension == 'txt':
                # 텍스트 파일 처리
                text_content = uploaded_file.read().decode('utf-8')
                
                # 텍스트 표시
                st.subheader("업로드된 텍스트")
                st.text_area("전체 텍스트", text_content, height=200)
                
                # 브랜드명 추출 시도
                extracted_brand_name = extract_brand_name(text_content)
                final_brand_name = brand_name or extracted_brand_name
                
                # 미팅 정보 구성
                meeting_info = {
                    "company_name": our_company_name,
                    "our_participants": our_participants,
                    "meeting_date": meeting_date.strftime("%Y-%m-%d"),
                    "brand_name": final_brand_name
                }
                
                # 요약 생성
                if claude_api_key:
                    with st.spinner("Claude API로 요약 생성 중..."):
                        summary = summarize_with_claude(text_content, claude_api_key, meeting_info)
                    
                    st.subheader("📋 브랜드 세일즈 미팅 요약")
                    st.markdown(summary)
                    
                    # 요약본 다운로드 버튼
                    col1, col2 = st.columns(2)
                    with col1:
                        st.download_button(
                            label="요약본 다운로드 (.txt)",
                            data=summary,
                            file_name=f"브랜드미팅요약_{meeting_date.strftime('%Y%m%d')}_{final_brand_name}.txt",
                            mime="text/plain"
                        )
                    with col2:
                        st.download_button(
                            label="요약본 다운로드 (.md)",
                            data=summary,
                            file_name=f"브랜드미팅요약_{meeting_date.strftime('%Y%m%d')}_{final_brand_name}.md",
                            mime="text/markdown"
                        )
                else:
                    st.warning("요약을 생성하려면 Claude API 키를 입력하세요.")

# 텍스트 직접 입력 탭
with tab3:
    st.header("텍스트 직접 입력")
    transcript_text = st.text_area("미팅 내용을 여기에 붙여넣기하세요", height=300)
    
    # 처리 버튼
    process_text_button = st.button("텍스트 변환 및 요약 시작", key="process_text")
    
    if process_text_button and transcript_text:
        # 브랜드명 추출 시도
        extracted_brand_name = extract_brand_name(transcript_text)
        final_brand_name = brand_name or extracted_brand_name
        
        # 미팅 정보 구성
        meeting_info = {
            "company_name": our_company_name,
            "our_participants": our_participants,
            "meeting_date": meeting_date.strftime("%Y-%m-%d"),
            "brand_name": final_brand_name
        }
        
        # 요약 생성
        if claude_api_key:
            with st.spinner("Claude API로 요약 생성 중..."):
                summary = summarize_with_claude(transcript_text, claude_api_key, meeting_info)
            
            st.subheader("📋 브랜드 세일즈 미팅 요약")
            st.markdown(summary)
            
            # 요약본 다운로드 버튼
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    label="요약본 다운로드 (.txt)",
                    data=summary,
                    file_name=f"브랜드미팅요약_{meeting_date.strftime('%Y%m%d')}_{final_brand_name}.txt",
                    mime="text/plain"
                )
            with col2:
                st.download_button(
                    label="요약본 다운로드 (.md)",
                    data=summary,
                    file_name=f"브랜드미팅요약_{meeting_date.strftime('%Y%m%d')}_{final_brand_name}.md",
                    mime="text/markdown"
                )
        else:
            st.warning("요약을 생성하려면 Claude API 키를 입력하세요.")
    elif process_text_button:
        st.error("텍스트를 입력해주세요.")
