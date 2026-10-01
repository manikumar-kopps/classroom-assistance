import os, base64, uuid, requests
from flask import Flask, request, jsonify, send_file
from dotenv import load_dotenv
from openai import OpenAI

from models import db, User
from routes import main as main_blueprint
from auth import hash_password

load_dotenv()

def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    
    # Configure Flask app
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-flask-secret-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
    app.config['JWT_SECRET'] = os.getenv('JWT_SECRET', 'default-jwt-secret-key')
    app.config['ATTENDANCE_THRESHOLD'] = int(os.getenv('ATTENDANCE_THRESHOLD', '75'))
    
    # Initialize SQLAlchemy db
    db.init_app(app)
    
    # Register blueprint
    app.register_blueprint(main_blueprint)

    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return jsonify(error="Not found"), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify(error="Internal server error"), 500
        
    with app.app_context():
        db.create_all()
        from models import Teacher, Student, Class, Subject, Enrollment

        # 1. Default Admin
        admin = User.query.filter_by(email='admin@school.edu').first()
        if not admin:
            new_admin = User(
                name='System Admin',
                email='admin@school.edu',
                password_hash=hash_password('admin123'),
                role='admin'
            )
            db.session.add(new_admin)
            db.session.commit()
            print("Default admin ready: admin@school.edu / admin123")

        # 2. Default Class
        default_class = Class.query.first()
        if not default_class:
            default_class = Class(class_name='MCA-A', semester=1, department='Computer Applications')
            db.session.add(default_class)
            db.session.commit()

        # 3. Default Teacher (teacher1@school.edu)
        teacher_user = User.query.filter_by(email='teacher1@school.edu').first()
        if not teacher_user:
            teacher_user = User(
                name='Dr. Robert Chen',
                email='teacher1@school.edu',
                password_hash=hash_password('teacher123'),
                role='teacher'
            )
            db.session.add(teacher_user)
            db.session.flush()
            t_profile = Teacher(user_id=teacher_user.user_id, department='Computer Applications')
            db.session.add(t_profile)
            db.session.commit()
            print("Default teacher ready: teacher1@school.edu / teacher123")
        else:
            # Ensure Teacher profile exists
            if not Teacher.query.filter_by(user_id=teacher_user.user_id).first():
                t_profile = Teacher(user_id=teacher_user.user_id, department='Computer Applications')
                db.session.add(t_profile)
                db.session.commit()

        # 4. Default Subject for teacher
        t_obj = Teacher.query.filter_by(user_id=teacher_user.user_id).first()
        if t_obj:
            existing_subj = Subject.query.filter_by(subject_code='CS101').first()
            if not existing_subj:
                subj = Subject(subject_name='Python Programming', subject_code='CS101', teacher_id=t_obj.teacher_id)
                db.session.add(subj)
                db.session.commit()
            elif existing_subj.teacher_id != t_obj.teacher_id:
                # Assign CS101 to teacher1
                existing_subj.teacher_id = t_obj.teacher_id
                db.session.commit()

        # 5. Default Student (student1@school.edu)
        student_user = User.query.filter_by(email='student1@school.edu').first()
        if not student_user:
            student_user = User(
                name='John Smith',
                email='student1@school.edu',
                password_hash=hash_password('student123'),
                role='student'
            )
            db.session.add(student_user)
            db.session.flush()
            s_profile = Student(user_id=student_user.user_id, roll_number='2024MCA101',
                                class_id=default_class.class_id, department='Computer Applications')
            db.session.add(s_profile)
            db.session.commit()
            print("Default student ready: student1@school.edu / student123")
        else:
            if not Student.query.filter_by(user_id=student_user.user_id).first():
                s_profile = Student(user_id=student_user.user_id, roll_number='2024MCA101',
                                    class_id=default_class.class_id, department='Computer Applications')
                db.session.add(s_profile)
                db.session.commit()

    # ===== AI Features Integration (from original app) =====
    
    AOAI_ENDPOINT=os.getenv("AZURE_OPENAI_ENDPOINT","").rstrip("/")
    AOAI_KEY=os.getenv("AZURE_OPENAI_API_KEY","")
    TEXT_MODEL=os.getenv("TEXT_MODEL_DEPLOYMENT","")
    VISION_MODEL=os.getenv("VISION_MODEL_DEPLOYMENT") or TEXT_MODEL
    IMAGE_MODEL=os.getenv("IMAGE_MODEL_DEPLOYMENT","")
    SPEECH_ENDPOINT=os.getenv("SPEECH_ENDPOINT","").rstrip("/")
    SPEECH_KEY=os.getenv("SPEECH_API_KEY","")
    SPEECH_REGION=os.getenv("SPEECH_REGION","eastus")
    CONTENT_ENDPOINT=os.getenv("CONTENT_ENDPOINT","").rstrip("/")
    CONTENT_KEY=os.getenv("CONTENT_API_KEY","")
    CONTENT_API_VERSION=os.getenv("CONTENT_API_VERSION","2025-11-01")

    def client():
        if not AOAI_ENDPOINT or not AOAI_KEY:
            raise RuntimeError("Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY in .env")
        endpoint = AOAI_ENDPOINT.removesuffix("/openai/v1").rstrip("/")
        return OpenAI(api_key=AOAI_KEY, base_url=f"{endpoint}/openai/v1/")

    def image_client():
        if not CONTENT_ENDPOINT or not CONTENT_KEY:
            raise RuntimeError("Set CONTENT_ENDPOINT and CONTENT_API_KEY in .env")
        endpoint = CONTENT_ENDPOINT.removesuffix("/openai/v1").removesuffix("/openai").rstrip("/")
        return OpenAI(
            api_key=CONTENT_KEY,
            base_url=f"{endpoint}/openai/v1/",
            default_query={"api-version": "preview"},
        )

    def text_response(prompt, system="You are a helpful AI assistant."):
        r=client().responses.create(model=TEXT_MODEL, instructions=system, input=prompt)
        return r.output_text

    @app.post("/api/chat")
    def api_chat():
        try:
            p=(request.json or {}).get("message","").strip()
            if not p: return jsonify(error="Enter a message."),400
            return jsonify(reply=text_response(p))
        except Exception as e: return jsonify(error=str(e)),500

    @app.post("/api/vision")
    def api_vision():
        try:
            f=request.files.get("image")
            prompt=request.form.get("prompt","Describe this image in detail.").strip()
            if not f: return jsonify(error="Upload an image."),400
            data=base64.b64encode(f.read()).decode()
            mime=f.mimetype or "image/jpeg"
            r=client().responses.create(
                model=VISION_MODEL,
                input=[{"role":"user","content":[
                    {"type":"input_text","text":prompt},
                    {"type":"input_image","image_url":f"data:{mime};base64,{data}"}
                ]}]
            )
            return jsonify(result=r.output_text)
        except Exception as e: return jsonify(error=str(e)),500

    @app.post("/api/image-generation")
    def api_image_generation():
        try:
            prompt=(request.json or {}).get("prompt","").strip()
            if not prompt: return jsonify(error="Enter a prompt."),400
            if not IMAGE_MODEL:
                raise RuntimeError("Set IMAGE_MODEL_DEPLOYMENT to your FLUX-1.1-pro deployment name.")
            r=image_client().images.generate(model=IMAGE_MODEL,prompt=prompt,n=1,size="1024x1024")
            item=r.data[0]
            if getattr(item,"b64_json",None):
                raw=base64.b64decode(item.b64_json)
                name=f"{uuid.uuid4().hex}.png"; path=os.path.join("uploads",name)
                os.makedirs("uploads", exist_ok=True)
                open(path,"wb").write(raw)
                return jsonify(url=f"/uploads/{name}")
            return jsonify(url=getattr(item,"url",None))
        except Exception as e: return jsonify(error=str(e)),500

    @app.post("/api/speech")
    def api_speech():
        try:
            f=request.files.get("audio")
            if not f: return jsonify(error="Upload an audio file."),400
            if not SPEECH_KEY: raise RuntimeError("Set SPEECH_API_KEY.")
            language=request.form.get("language","en-US")
            url=f"{SPEECH_ENDPOINT}/speechtotext/v3.2/transcriptions:transcribe?api-version=2024-11-15"
            headers={"Ocp-Apim-Subscription-Key":SPEECH_KEY}
            files={"audio":(f.filename,f.stream,f.mimetype or "audio/wav")}
            data={"definition":'{"locales":["'+language+'"],"profanityFilterMode":"Masked"}'}
            r=requests.post(url,headers=headers,files=files,data=data,timeout=120)
            if not r.ok:
                return jsonify(error=f"Speech service returned {r.status_code}: {r.text}"),r.status_code
            return jsonify(result=r.json())
        except Exception as e: return jsonify(error=str(e)),500

    @app.post("/api/content-understanding")
    def api_content():
        try:
            f=request.files.get("file")
            analyzer=request.form.get("analyzer","prebuilt-documentSearch")
            if not f: return jsonify(error="Upload a file."),400
            if not CONTENT_ENDPOINT or not CONTENT_KEY:
                raise RuntimeError("Set CONTENT_ENDPOINT and CONTENT_API_KEY.")
            url=f"{CONTENT_ENDPOINT}/contentunderstanding/analyzers/{analyzer}:analyze?api-version={CONTENT_API_VERSION}"
            headers={"Ocp-Apim-Subscription-Key":CONTENT_KEY}
            r=requests.post(url,headers=headers,files={"file":(f.filename,f.stream,f.mimetype)},timeout=180)
            if not r.ok:
                return jsonify(error=f"Content Understanding returned {r.status_code}: {r.text}"),r.status_code
            return jsonify(result=r.json())
        except Exception as e: return jsonify(error=str(e)),500

    @app.get("/uploads/<name>")
    def uploads(name): 
        return send_file(os.path.join("uploads",name))

    @app.get("/health")
    def health():
        return jsonify(text_model=bool(TEXT_MODEL), vision_model=bool(VISION_MODEL),
                       image_model=bool(IMAGE_MODEL), speech=bool(SPEECH_KEY),
                       content_understanding=bool(CONTENT_KEY))
                       
    return app

app = create_app()


if __name__ == '__main__':
    import socket

    def is_port_in_use(port_num):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port_num)) == 0

    # Default to 5050 to prevent macOS AirPlay Receiver (port 5000) collision
    target_port = int(os.environ.get('PORT', 5050))

    if is_port_in_use(target_port):
        for candidate in [5050, 5001, 8000, 8080]:
            if not is_port_in_use(candidate):
                target_port = candidate
                break

    print("\n" + "=" * 65)
    print("  CLASSROOM ATTENDANCE ASSISTANT IS LIVE!")
    print(f"  Open in Browser: http://127.0.0.1:{target_port}/login")
    print("  (Port used to avoid macOS AirPlay Receiver conflicts)")
    print("=" * 65 + "\n")

    app.run(
        debug=True,
        host='127.0.0.1',
        port=target_port
    )
