from flask import Flask, render_template, request, redirect, url_for
from deepface import DeepFace
import mysql.connector
import os
from datetime import datetime
import uuid  

app = Flask(__name__)
UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# MySQL DB 설정
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '111111',  
    'database': 'emotion'  
}

# 영어 감정을 한국어로 매핑
EMOTION_KR = {
    'angry': '화남',
    'disgust': '역겨움',
    'fear': '두려움',
    'happy': '행복',
    'sad': '슬픔',
    'surprise': '놀람',
    'neutral': '보통'
}

# 이미지 업로드 + 감정 분석 + 일기 저장
@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    image_filename = None
    if request.method == 'POST':
        file = request.files['image']
        diary_text = request.form.get('diary')  # 사용자가 쓴 일기

        if file:
            # 파일명을 UUID로 안전하게 변환 (한글/특수문자 문제 해결)
            ext = os.path.splitext(file.filename)[1]
            safe_filename = f"{uuid.uuid4()}{ext}"
            filepath = os.path.join(UPLOAD_FOLDER, safe_filename)
            file.save(filepath)
            image_filename = safe_filename

            # DeepFace 감정 분석 (정확도 높이기)
            try:
                analysis = DeepFace.analyze(
                    img_path=filepath,
                    actions=['emotion'],
                    enforce_detection=True,      # 얼굴 없으면 분석 실패
                    detector_backend='mtcnn'     # 정확한 얼굴 검출
                )

                if isinstance(analysis, list):
                    analysis = analysis[0]

                emotions = analysis['emotion']
                dominant_emotion = max(emotions, key=emotions.get)
                confidence = emotions[dominant_emotion]

                # 슬픔 보정 로직 (neutral → sad)
                if dominant_emotion == 'neutral':
                    sad_prob = emotions.get('sad', 0)
                    # 슬픔 확률이 꽤 높으면 슬픔으로 간주
                    if sad_prob > 0.25:  # 25% 이상이면 슬픔으로
                        dominant_emotion = 'sad'
                        confidence = sad_prob

                emotion_kr = EMOTION_KR.get(dominant_emotion, dominant_emotion)
                result = f"분석 결과: {emotion_kr} (신뢰도: {confidence:.2f})"

                # DB 저장
                conn = mysql.connector.connect(**DB_CONFIG)
                c = conn.cursor()
                c.execute(
                    "INSERT INTO emotion_records (filename, emotion, confidence, diary, upload_time) VALUES (%s, %s, %s, %s, %s)",
                    (safe_filename, emotion_kr, confidence, diary_text, datetime.now())
                )
                conn.commit()
                conn.close()

            except Exception as e:
                result = f"분석 중 오류 발생: {str(e)}"

    return render_template('index.html', result=result, image_filename=image_filename)

# 한 달 감정 통계
@app.route('/month_stats', methods=['GET'])
def month_stats():
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)

    conn = mysql.connector.connect(**DB_CONFIG)
    c = conn.cursor()

    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{month+1:02d}-01"

    query = """
        SELECT emotion, COUNT(*) 
        FROM emotion_records 
        WHERE upload_time >= %s AND upload_time < %s
        GROUP BY emotion
    """
    c.execute(query, (start_date, end_date))
    stats = c.fetchall()
    conn.close()

    years = list(range(2023, datetime.now().year+1))

    return render_template('month_stats.html', stats=stats, years=years, 
                           selected_year=year, selected_month=month)

# 오늘의 감정 히스토리 보기
@app.route('/history')
def history():
    today = datetime.now().strftime("%Y-%m-%d")

    conn = mysql.connector.connect(**DB_CONFIG)
    c = conn.cursor(dictionary=True)
    c.execute(
        "SELECT id, filename, emotion, diary, upload_time FROM emotion_records WHERE DATE(upload_time) = %s ORDER BY upload_time DESC",
        (today,)
    )
    records = c.fetchall()
    conn.close()

    return render_template('history.html', date=today, records=records)


# 일기 수정 (GET: 폼 표시, POST: 수정 저장)
@app.route('/edit/<int:record_id>', methods=['GET', 'POST'])
def edit_record(record_id):
    conn = mysql.connector.connect(**DB_CONFIG)
    c = conn.cursor(dictionary=True)

    if request.method == 'POST':
        new_diary = request.form.get('diary')
        c.execute("UPDATE emotion_records SET diary=%s WHERE id=%s", (new_diary, record_id))
        conn.commit()
        conn.close()
        return redirect(url_for('history'))

    # GET 요청일 때 기존 데이터 불러오기
    c.execute("SELECT * FROM emotion_records WHERE id=%s", (record_id,))
    record = c.fetchone()
    conn.close()
    return render_template('edit.html', record=record)


# 일기 삭제
@app.route('/delete/<int:record_id>', methods=['POST'])
def delete_record(record_id):
    conn = mysql.connector.connect(**DB_CONFIG)
    c = conn.cursor()
    c.execute("DELETE FROM emotion_records WHERE id=%s", (record_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('history'))


if __name__ == "__main__":
    app.run(debug=True)
