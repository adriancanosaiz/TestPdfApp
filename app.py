from flask import Flask, render_template, request, redirect, url_for, flash, session
import PyPDF2
import requests
import json
from datetime import datetime
import os
from dotenv import load_dotenv
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField
from wtforms.validators import DataRequired, Email

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mysecretkey'  # Cambia esto en producción

# Configuración de MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '300704.a'  # Ajusta tu contraseña
app.config['MYSQL_DB'] = 'flask_app'

# Inicializar MySQL
mysql = MySQL(app)

# Formularios
class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])

# Funciones auxiliares
def extraer_texto_pdf(pdf_file):
    try:
        reader = PyPDF2.PdfReader(pdf_file)
        texto = ""
        for page in reader.pages:
            texto += page.extract_text()
        return texto
    except Exception as e:
        print(f"Error al leer el PDF: {e}")
        return ""

def generar_preguntas(texto):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("La clave de API de Gemini no se ha cargado correctamente.")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-pro:generateContent?key={api_key}"

    prompt = f"""Crea 10 preguntas tipo test basadas en el siguiente texto:
{texto}

Para cada pregunta, proporciona:
- "pregunta" (el enunciado),
- "opciones" (una lista de 3 o más opciones),
- "respuesta_correcta" (la respuesta correcta).

La respuesta debe ser estrictamente un JSON válido.
No incluyas comentarios, explicaciones, ni bloques de código como ```json o similares.
Solo responde con el JSON directamente, limpio y listo para parsear.
"""

    data = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        content = response.json()

        texto_generado = content['candidates'][0]['content']['parts'][0]['text']
        print("Respuesta cruda de Gemini:", texto_generado)

        # Limpieza extra si empieza por ```
        if texto_generado.startswith("```"):
            texto_generado = texto_generado.strip().lstrip("```json").lstrip("```").rstrip("```").strip()

        preguntas = json.loads(texto_generado)

        # Guardar preguntas en un archivo
        with open('test.json', 'w', encoding='utf-8') as f:
            json.dump(preguntas, f, indent=4, ensure_ascii=False)
        return preguntas
    except Exception as e:
        print(f"Error al generar las preguntas: {e}")
        return []

# Rutas
@app.route("/register", methods=['GET', 'POST'])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data
        email = form.email.data
        password = form.password.data

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        cur = mysql.connection.cursor()
        cur.execute('INSERT INTO users (username, email, password) VALUES (%s, %s, %s)', (username, email, hashed_password))
        mysql.connection.commit()
        cur.close()

        flash('User registered successfully!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        cur = mysql.connection.cursor()
        cur.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user[3], password):  # user[3] es el campo password
            flash('Login successful!', 'success')
            session['logged_in'] = True
            session['username'] = username  # Guardar el nombre en la sesión
            session['email'] = user[2]  # Guardar el email en la sesión
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html', form=form)

@app.route("/logout")
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('home'))

@app.route("/home", methods=["GET"])
def home():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return render_template("home.html")

@app.route("/index", methods=["GET", "POST"])
def index():
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    if request.method == "POST":
        pdf_file = request.files["pdf"]
        texto = extraer_texto_pdf(pdf_file)
        if not texto:
            flash("No se pudo extraer texto del PDF.", 'danger')
            return redirect(url_for('index'))
        preguntas = generar_preguntas(texto)
        if preguntas:
            return redirect(url_for('test'))
        flash("No se generaron preguntas correctamente.", 'danger')
    return render_template("index.html")

# Añadir la ruta del perfil
@app.route("/profile")
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    
    username = session['username']
    cur = mysql.connection.cursor()
    cur.execute('SELECT * FROM users WHERE username = %s', (username,))
    user = cur.fetchone()
    cur.close()

    return render_template('profile.html', user=user)

@app.route("/test", methods=["GET"])
def test():
    preguntas = []
    if os.path.exists('test.json'):
        with open('test.json', 'r', encoding='utf-8') as f:
            preguntas = json.load(f)
    return render_template("test.html", preguntas=preguntas)

@app.route("/test/resultado", methods=["POST"])
def test_resultado():
    correctas = 0
    total_preguntas = 0
    resultado_respuestas = []

    i = 1
    while True:
        pregunta_texto = request.form.get(f'pregunta_texto_{i}')
        respuesta_correcta = request.form.get(f'respuesta_correcta_{i}')
        seleccionada = request.form.get(f'pregunta_{i}')
        if not pregunta_texto:
            break

        es_correcta = (seleccionada == respuesta_correcta)
        if es_correcta:
            correctas += 1

        resultado_respuestas.append({
            'pregunta': pregunta_texto,
            'correcta': respuesta_correcta,
            'seleccionada': seleccionada,
            'es_correcta': es_correcta
        })

        total_preguntas += 1
        i += 1

    fecha = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    nota = (correctas / total_preguntas) * 100 if total_preguntas else 0
    resultado = {
        'fecha': fecha,
        'total_preguntas': total_preguntas,
        'aciertos': correctas,
        'nota': round(nota, 2)
    }

    return render_template("test_resultado.html", resultado=resultado, respuestas=resultado_respuestas)

if __name__ == "__main__":
    app.run(debug=True)