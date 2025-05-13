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
import subprocess
import shutil

# FFmpeg가 있는지 확인하는 함수
def check_ffmpeg():
    try:
        # FFmpeg 버전 확인 (설치 확인용)
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        st.success("FFmpeg가 정상적으로 설치되어 있습니다.")
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        st.error("FFmpeg를 찾을 수 없습니다. packages.txt 파일을 확인해주세요.")
        return False

# 페이지 설정
st.set_page_config(page_title="브랜드 세일즈 미팅록 자동화", page_icon="🎙️", layout="wide")

# 타이틀 및 설명
st.title("🎙️ 브랜드 세일즈 미팅록 자동화")
st.markdown("""
이 앱은 브랜드 세일즈 미팅을 실시간으로 녹음하거나, 기존 녹음을 업로드하여 텍스트로 변환하고 요약합니다.
1. 실시간 녹음을 시작하거나 기존 오디오/텍스트 파일을 업로드하세요.
2. 녹음이 끝나면 자동으로 텍스트로 변환됩니다.
3. 변환된 텍스트를 이용해 Claude를 통해 구조화된 브랜드 미팅 요약을 생성할 수 있습니다.
""")

# FFmpeg 확인
ffmpeg_available = check_ffmpeg()

# 세션 상태 초기화
if "audio_data" not in st.session_state:
    st.session_state["audio_data"] = None
if "transcript_text" not in st.session_state:
    st.session_state["transcript_text"] = None
if "summary_result" not in st.session_state:
    st.session_state["summary_result"] = None
if "recorder_status" not in st.session_state:
    st.session_state["recorder_status"] = "idle"  # 상태: idle, transcribed

# 탭 생성
tab1, tab2, tab3 = st.tabs(["실시간 녹음", "파일 업로드", "텍스트 직접 입력"])

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

# Whisper 모델 로드
@st.cache_resource
def load_whisper_model(model_size):
    try:
        return whisper.load_model(model_size)
    except Exception as e:
        st.error(f"모델 로드 실패: {e}")
        return None

# 브랜드 이름 추출 함수
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

# WAV를 MP3로 변환하는 함수 (FFmpeg 사용)
def convert_audio_format(input_file, output_format="mp3"):
    if not ffmpeg_available:
        st.warning("FFmpeg가 설치되어 있지 않아 변환을 건너뜁니다. 원본 파일을 사용합니다.")
        return input_file
    
    try:
        output_file = input_file.rsplit('.', 1)[0] + f".{output_format}"
        
        # FFmpeg 명령어 구성
        cmd = [
            'ffmpeg',
            '-i', input_file,  # 입력 파일
            '-y',  # 출력 파일 덮어쓰기
            '-vn',  # 비디오 스트림 제거
            '-ar', '44100',  # 샘플링 레이트
            '-ac', '2',  # 오디오 채널 수
            '-b:a', '192k',  # 비트레이트
            output_file  # 출력 파일
        ]
        
        # 명령어 실행
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        st.success(f"오디오 파일이 {output_format} 형식으로 변환되었습니다.")
        return output_file
    except Exception as e:
        st.error(f"오디오 변환 중 오류 발생: {str(e)}")
        return input_file

# 복사 버튼을 위한 JavaScript 함수
def get_copy_button_html():
    return """
    <style>
    .copy-btn {
        background-color: #4CAF50;
        border: none;
        color: white;
        padding: 10px 20px;
        text-align: center;
        text-decoration: none;
        display: inline-block;
        font-size: 16px;
        margin: 4px 2px;
        cursor: pointer;
        border-radius: 4px;
    }
    .copy-area {
        border: 1px solid #ddd;
        border-radius: 4px;
        padding: 15px;
        margin: 10px 0;
        background-color: #f9f9f9;
        white-space: pre-wrap;
        font-family: sans-serif;
    }
    </style>
    
    <div>
        <div id="summary-area" class="copy-area">%s</div>
        <button class="copy-btn" onclick="copySummary()">텍스트 복사</button>
    </div>
    
    <script>
    function copySummary() {
        const summaryText = document.getElementById('summary-area').innerText;
        
        // 클립보드에 복사
        navigator.clipboard.writeText(summaryText)
            .then(() => {
                // 복사 성공 시 버튼 텍스트 변경
                const btn = document.querySelector('.copy-btn');
                const originalText = btn.innerText;
                btn.innerText = '복사 완료!';
                
                // 2초 후 원래 텍스트로 복원
                setTimeout(() => {
                    btn.innerText = originalText;
                }, 2000);
            })
            .catch(err => {
                console.error('복사 실패:', err);
                alert('복사에 실패했습니다. 직접 텍스트를 선택하여 복사해주세요.');
            });
    }
    </script>
    """

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
    .status-message {
        margin-top: 10px;
        padding: 10px;
        border-radius: 4px;
        min-height: 50px;
        max-width: 100%;
        white-space: normal;
        word-wrap: break-word;
    }
    .info {
        background-color: #e7f3fe;
        border-left: 6px solid #2196F3;
    }
    .success {
        background-color: #ddffdd;
        border-left: 6px solid #4CAF50;
    }
    .download-link {
        display: inline-block;
        margin: 10px 0;
        padding: 10px 15px;
        background-color: #4CAF50;
        color: white;
        text-decoration: none;
        border-radius: 4px;
        cursor: pointer;
    }
    </style>
    <div id="audio-recorder">
        <button id="record-button" class="button">녹음 시작</button>
        <div id="time-display" class="time-display">00:00:00</div>
        <div id="audio-container">
            <audio id="audio-playback" controls style="display:none;"></audio>
            <div id="download-container"></div>
        </div>
        <div id="status-message" class="status-message"></div>
    </div>

    <script>
        const recordButton = document.getElementById('record-button');
        const timeDisplay = document.getElementById('time-display');
        const audioPlayback = document.getElementById('audio-playback');
        const statusMessage = document.getElementById('status-message');
        const downloadContainer = document.getElementById('download-container');
        
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
                recordButton.textContent = '녹음 시작';
                recordButton.classList.remove('recording');
                clearInterval(timerInterval);
                
                // 상태 메시지 업데이트
                statusMessage.className = "status-message info";
                statusMessage.textContent = "녹음 처리 중...";
            } else {
                // 녹음 시작
                audioChunks = [];
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    
                    // 가능한 오디오 형식 확인
                    const mimeType = 'audio/webm';
                    mediaRecorder = new MediaRecorder(stream, { mimeType });
                    
                    mediaRecorder.ondataavailable = (event) => {
                        audioChunks.push(event.data);
                    };
                    
                    mediaRecorder.onstop = () => {
                        // 녹음된 오디오 처리
                        audioBlob = new Blob(audioChunks, { type: mimeType });
                        const audioUrl = URL.createObjectURL(audioBlob);
                        audioPlayback.src = audioUrl;
                        audioPlayback.style.display = 'block';
                        
                        // 다운로드 링크 생성
                        // 이전 다운로드 링크 제거
                        while (downloadContainer.firstChild) {
                            downloadContainer.removeChild(downloadContainer.firstChild);
                        }
                        
                        // 새로운 다운로드 링크 추가
                        const downloadLink = document.createElement('a');
                        downloadLink.href = audioUrl;
                        downloadLink.download = `recording_${new Date().toISOString().replace(/[:.]/g, '-')}.mp3`;
                        downloadLink.textContent = '녹음 파일 다운로드 (MP3)';
                        downloadLink.className = 'download-link';
                        downloadContainer.appendChild(downloadLink);
                        
                        // 상태 메시지 업데이트
                        statusMessage.className = "status-message success";
                        statusMessage.textContent = "녹음이 완료되었습니다! 파일을 다운로드하고 '파일 업로드' 탭에서 업로드해주세요.";
                        
                        // 오디오 트랙 중지
                        stream.getTracks().forEach(track => track.stop());
                    };
                    
                    mediaRecorder.start(100);  // 100ms마다 데이터 수집
                    startTime = new Date();
                    timerInterval = setInterval(updateTimer, 1000);
                    recordButton.textContent = '녹음 중지';
                    recordButton.classList.add('recording');
                    
                    // 상태 메시지 초기화
                    statusMessage.className = "status-message info";
                    statusMessage.textContent = "녹음 중입니다. '녹음 중지' 버튼을 클릭하여 녹음을 완료하세요.";
                } catch (err) {
                    console.error('마이크 접근 오류:', err);
                    statusMessage.className = "status-message error";
                    statusMessage.textContent = "마이크 접근이 거부되었습니다. 브라우저 설정에서 마이크 권한을 확인해주세요.";
                }
            }
        });
    </script>
    """

# 결과 표시를 위한 컨테이너
result_container = st.container()

# 실시간 녹음 탭
with tab1:
    st.header("실시간 녹음")
    st.markdown("아래 버튼을 클릭하여 브랜드 미팅을 실시간으로 녹음하세요. 녹음이 완료되면 파일을 다운로드하고 '파일 업로드' 탭에서 업로드해주세요.")
    
    # API 키 확인 메시지
    if not claude_api_key:
        st.warning("요약 기능을 사용하려면 사이드바에 Claude API 키를 입력해주세요. API 키가 없어도 텍스트 변환은 가능합니다.")
    
    # 오디오 레코더 HTML 삽입
    st.components.v1.html(get_audio_recorder_html(), height=300)

# 파일 업로드 탭
with tab2:
    st.header("파일 업로드")
    st.markdown("""
    오디오 파일(.mp3, .wav, .m4a, .webm) 또는 텍스트 파일(.txt)을 업로드하세요.
    업로드 후 '텍스트 변환 시작' 버튼을 클릭하면 변환이 시작됩니다.
    텍스트로 변환된 후에는 'Claude 요약 시작' 버튼이 나타납니다.
    """)
    
    uploaded_file = st.file_uploader("오디오 파일(.mp3, .wav, .m4a, .webm) 또는 텍스트 파일(.txt) 선택", 
                                     type=["mp3", "wav", "m4a", "webm", "txt"])
    
    if uploaded_file is not None:
        file_extension = uploaded_file.name.split('.')[-1].lower()
        
        if file_extension in ['mp3', 'wav', 'm4a', 'webm']:
            # 오디오 파일 처리
            st.success(f"오디오 파일 '{uploaded_file.name}'이(가) 업로드되었습니다.")
            
            # 임시 파일로 저장
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_extension}") as temp_file:
                temp_file.write(uploaded_file.getbuffer())
                temp_filename = temp_file.name
            
            # MP3로 변환
            if ffmpeg_available and file_extension != 'mp3':
                with st.spinner(f"{file_extension} 파일을 MP3로 변환 중..."):
                    mp3_filename = convert_audio_format(temp_filename, "mp3")
                    st.session_state["audio_file"] = mp3_filename
            else:
                st.session_state["audio_file"] = temp_filename
            
            # 텍스트 변환 버튼
            if st.button("텍스트 변환 시작", key="convert_audio"):
                process_audio_to_text()
        
        elif file_extension == 'txt':
            # 텍스트 파일 처리
            st.success(f"텍스트 파일 '{uploaded_file.name}'이(가) 업로드되었습니다.")
            
            # 파일 내용 읽기
            text_content = uploaded_file.read().decode('utf-8')
            st.session_state["transcript_text"] = text_content
            st.session_state["recorder_status"] = "transcribed"
            
            # 텍스트 미리보기
            with st.expander("텍스트 미리보기"):
                st.text(text_content[:1000] + ("..." if len(text_content) > 1000 else ""))
            
            # 텍스트 표시
            display_transcript()

# 텍스트 직접 입력 탭
with tab3:
    st.header("텍스트 직접 입력")
    transcript_text = st.text_area("미팅 내용을 여기에 붙여넣기하세요", height=300)
    if st.button("텍스트 저장"):
        if transcript_text:
            st.session_state["transcript_text"] = transcript_text
            st.session_state["recorder_status"] = "transcribed"
            st.success("텍스트가 저장되었습니다.")
            display_transcript()
        else:
            st.error("텍스트를 입력해주세요.")

# 녹음 자동 처리 함수
def process_recording_data(audio_data, audio_format="webm"):
    if not audio_data:
        return False
    
    try:
        # Base64 데이터를 파일로 저장
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{audio_format}") as temp_file:
            decoded_data = base64.b64decode(audio_data)
            temp_file.write(decoded_data)
            temp_filename = temp_file.name
        
        st.session_state["audio_file"] = temp_filename
        
        # MP3로 변환 (FFmpeg 사용)
        if ffmpeg_available and audio_format != 'mp3':
            with st.spinner(f"{audio_format} 파일을 MP3로 변환 중..."):
                mp3_filename = convert_audio_format(temp_filename, "mp3")
                st.session_state["audio_file"] = mp3_filename
        
        return True
    except Exception as e:
        st.error(f"오디오 처리 중 오류 발생: {e}")
        return False

# 오디오를 텍스트로 변환하는 함수
def process_audio_to_text():
    if "audio_file" in st.session_state and st.session_state["audio_file"]:
        # Whisper 모델 로드
        model = load_whisper_model(model_size)
        if not model:
            st.error("Whisper 모델을 로드할 수 없습니다.")
            st.session_state["recorder_status"] = "error"
            return False
        
        # 오디오 파일에서 텍스트 변환
        try:
            with st.spinner("오디오를 텍스트로 변환 중..."):
                # 오디오 파일 확인
                audio_file = st.session_state["audio_file"]
                
                if not os.path.exists(audio_file):
                    st.error(f"파일을 찾을 수 없습니다: {audio_file}")
                    st.session_state["recorder_status"] = "error"
                    return False
                
                # 파일 크기 확인
                file_size = os.path.getsize(audio_file)
                if file_size == 0:
                    st.error("오디오 파일이 비어 있습니다.")
                    st.session_state["recorder_status"] = "error"
                    return False
                
                # 텍스트 변환
                st.info(f"오디오 파일 '{audio_file}' 변환 중... (크기: {file_size}바이트)")
                transcript = transcribe_audio(audio_file, model)
                
                if transcript:
                    st.session_state["transcript_text"] = transcript
                    st.session_state["recorder_status"] = "transcribed"
                    display_transcript()
                    return True
                else:
                    st.error("텍스트 변환에 실패했습니다.")
                    st.session_state["recorder_status"] = "error"
        except Exception as e:
            st.error(f"텍스트 변환 처리 중 오류 발생: {e}")
            import traceback
            st.error(f"상세 오류: {traceback.format_exc()}")
            st.session_state["recorder_status"] = "error"
    
    return False

# 오디오 파일을 텍스트로 변환 (Whisper 사용)
def transcribe_audio(audio_file, model):
    try:
        # 텍스트 변환
        result = model.transcribe(audio_file, language="ko")
        return result["text"]
    except Exception as e:
        st.error(f"텍스트 변환 중 오류 발생: {str(e)}")
        import traceback
        st.error(f"상세 오류: {traceback.format_exc()}")
        return None

# 요약 함수 (Claude API 사용)
def summarize_text_with_claude():
    if "transcript_text" not in st.session_state or not st.session_state["transcript_text"]:
        st.error("요약할 텍스트가 없습니다.")
        return False
    
    if not claude_api_key:
        st.error("Claude API 키가 입력되지 않았습니다. 요약을 진행할 수 없습니다.")
        return False
    
    transcript = st.session_state["transcript_text"]
    
    # 텍스트에서 브랜드명 추출
    extracted_brand_name = extract_brand_name(transcript)
    
    # 사이드바에서 입력한 브랜드명이 있으면 그것을 우선 사용
    final_brand_name = brand_name or extracted_brand_name
    
    # 미팅 정보 구성
    meeting_info = {
        "company_name": our_company_name,
        "our_participants": our_participants,
        "meeting_date": meeting_date.strftime("%Y-%m-%d"),
        "brand_name": final_brand_name
    }
    
    # 요약 생성
    with st.spinner("Claude API로 요약 생성 중..."):
        summary = summarize_with_claude(transcript, claude_api_key, meeting_info)
    
    if summary:
        # 요약 결과 저장
        st.session_state["summary_result"] = summary
        display_summary()
        return True
    
    return False

# 요약 함수 (Claude API 사용)
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

# 텍스트 변환 후 표시 함수
def display_transcript():
    if "transcript_text" in st.session_state and st.session_state["transcript_text"]:
        transcript = st.session_state["transcript_text"]
        
        # 텍스트 표시 영역
        transcript_container = st.container()
        with transcript_container:
            st.subheader("변환된 텍스트")
            st.text_area("전체 텍스트", transcript, height=200)
            
            # Claude API 키가 있으면 요약 버튼 표시
            if claude_api_key:
                if st.button("Claude 요약 시작", key="summary_button"):
                    summarize_text_with_claude()
            else:
                st.warning("요약을 생성하려면 Claude API 키를 입력하세요.")
        
        return True
    
    return False

# 요약 결과 표시 함수
def display_summary():
    if "summary_result" in st.session_state and st.session_state["summary_result"]:
        summary = st.session_state["summary_result"]
        
        # 브랜드명 추출 (파일명용)
        final_brand_name = brand_name
        if not final_brand_name and "transcript_text" in st.session_state:
            final_brand_name = extract_brand_name(st.session_state["transcript_text"])
        
        summary_container = st.container()
        with summary_container:
            st.subheader("브랜드 세일즈 미팅 요약")
            
            # 1. 마크다운으로 표시
            st.markdown(summary)
            
            # 2. 복사 가능한 영역과 복사 버튼 추가
            st.components.v1.html(get_copy_button_html() % summary, height=500)
            
            # 3. 다운로드 버튼
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
        
        return True
    
    return False

# 디버깅 정보 표시 영역
with st.expander("디버깅 정보", expanded=False):
    st.write(f"FFmpeg 설치 상태: {'설치됨' if ffmpeg_available else '설치되지 않음'}")
    
    if "audio_file" in st.session_state:
        st.write(f"오디오 파일 경로: {st.session_state['audio_file']}")
        if os.path.exists(st.session_state["audio_file"]):
            st.write(f"파일 크기: {os.path.getsize(st.session_state['audio_file'])} 바이트")
        else:
            st.write("파일이 존재하지 않습니다.")
    
    st.write(f"현재 상태: {st.session_state['recorder_status']}")
    st.write(f"텍스트 변환 여부: {'있음' if 'transcript_text' in st.session_state and st.session_state['transcript_text'] else '없음'}")

# 임시 파일 정리
def cleanup_temp_files():
    if "audio_file" in st.session_state and st.session_state["audio_file"]:
        try:
            os.remove(st.session_state["audio_file"])
        except:
            pass

# 앱 종료 시 임시 파일 정리
import atexit
atexit.register(cleanup_temp_files)
