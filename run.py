"""เริ่มระบบจัดทำงานวิจัย

รัน:  python run.py   แล้วเปิด http://127.0.0.1:5000
ตัวแปรแวดล้อม:  HOST (ค่าเริ่มต้น 127.0.0.1; ใช้ 0.0.0.0 เพื่อให้เครื่องอื่นในเครือข่ายเข้าใช้)  PORT (5000)
               GEMINI_API_KEY (ใช้เมื่อยังไม่ได้ตั้งค่าในหน้าผู้ดูแลระบบ)
"""
import os
import sys
import threading
import webbrowser

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from app.server import create_app  # noqa: E402

if __name__ == "__main__":
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "5000"))
    app = create_app()
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"ระบบจัดทำงานวิจัย -> http://{host}:{port}")
    try:
        from waitress import serve
    except ImportError:  # ยังไม่ได้ติดตั้ง waitress: ใช้เซิร์ฟเวอร์ของ Flask (เหมาะกับผู้ใช้จำนวนน้อย)
        print("(แนะนำ: pip install waitress เพื่อรองรับผู้ใช้พร้อมกันหลายคน)")
        app.run(host=host, port=port, debug=False, threaded=True)
    else:
        # คำขอบางอย่างรอ AI หรือ Word นานเป็นนาที จึงเผื่อเธรดไว้ให้หน้าเว็บของผู้ใช้อื่นยังตอบสนอง
        serve(app, host=host, port=port, threads=int(os.environ.get("THREADS", "32")))
