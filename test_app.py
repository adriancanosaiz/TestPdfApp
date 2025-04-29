from flask import Flask, render_template, request, redirect, url_for, flash, session
import PyPDF2
import requests
import json
from datetime import datetime
import os
from PyPDF2 import PdfReader
from dotenv import load_dotenv
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, DateField
from wtforms.validators import DataRequired, Email, Length
from urllib.parse import urlparse


# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mysecretkey'  # Cambia esto en producción


# Cargar la URL de conexión desde las variables de entorno
mysql_url = os.getenv('MYSQL_URL')

# Analizar la URL
url = urlparse(mysql_url)

# Configuración de MySQL usando los valores de la URL
app.config['MYSQL_HOST'] = url.hostname
app.config['MYSQL_USER'] = url.username
app.config['MYSQL_PASSWORD'] = url.password
app.config['MYSQL_DB'] = url.path[1:]  # Eliminar el primer '/' en la ruta
app.config['MYSQL_PORT'] = url.port

# Inicializar MySQL
mysql = MySQL(app)

# Formularios
class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8, message="La contraseña debe tener al menos 8 caracteres")])
    centro = StringField('Centro de estudios', validators=[DataRequired()])
    fecha_nacimiento = DateField('Fecha de nacimiento', format='%Y-%m-%d', validators=[DataRequired()])

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])

# Funciones auxiliares
def extraer_texto_pdf(pdf_data):
    try:
        # Usamos PyPDF2 directamente con los datos binarios
        reader = PyPDF2.PdfReader(pdf_data)
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
        centro = form.centro.data
        fecha_nacimiento = form.fecha_nacimiento.data

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        cur = mysql.connection.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s', (email,))
        if cur.fetchone():
            flash('Este correo ya está en uso.', 'danger')
            return redirect(url_for('register'))

        cur.execute('INSERT INTO users (username, email, password, centro, fecha_nacimiento) VALUES (%s, %s, %s, %s, %s)',
                    (username, email, hashed_password, centro, fecha_nacimiento))
        mysql.connection.commit()
        cur.close()

        flash('User registered successfully!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data
        password = form.password.data

        cur = mysql.connection.cursor()
        cur.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cur.fetchone()
        cur.close()

        if user and check_password_hash(user[3], password):
            flash('Login successful!', 'success')
            session['logged_in'] = True
            session['username'] = user[1]  # Guardar el nombre en la sesión
            session['email'] = user[2]  # Guardar el email en la sesión
            session['user_id'] = user[0]  # Guardar el user_id en la sesión
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password', 'danger')

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

@app.route('/index', methods=['GET', 'POST'])
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'pdf' not in request.files:
            return 'No file part'

        pdf_file = request.files['pdf']
        if pdf_file.filename == '':
            return 'No selected file'

        if pdf_file:
            pdf_data = pdf_file.read()  # Leer el contenido del PDF en binario

            # Guardar el PDF en la base de datos (en el campo BLOB)
            user_id = session['user_id']
            nombre_archivo = pdf_file.filename
            fecha_subida = datetime.now().strftime('%Y-%m-%d %H:%M:%S')  # Fecha de subida

            cur = mysql.connection.cursor()
            cur.execute('INSERT INTO pdf_uploads (user_id, nombre_archivo, archivo_pdf, fecha_subida) VALUES (%s, %s, %s, %s)',
                        (user_id, nombre_archivo, pdf_data, fecha_subida))
            mysql.connection.commit()
            cur.close()

            # Extraer el texto del PDF
            texto = extraer_texto_pdf(pdf_data)  # Aquí ya no es necesario guardar el archivo físicamente

            preguntas = generar_preguntas(texto)
            return render_template('test.html', preguntas=preguntas)

    return render_template('index.html')

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

    # Guardar en la base de datos
    user_id = session.get('user_id')
    if user_id:
        cur = mysql.connection.cursor()
        
        # Insertar el test general en test_results y obtener el test_result_id
        cur.execute('INSERT INTO test_results (user_id, fecha, total_preguntas, aciertos, nota) VALUES (%s, %s, %s, %s, %s)',
                    (user_id, fecha, total_preguntas, correctas, round(nota, 2)))
        mysql.connection.commit()
        
        # Obtener el test_result_id generado
        test_result_id = cur.lastrowid

        # Insertar las respuestas individuales en test_answers
        for res in resultado_respuestas:
            cur.execute('INSERT INTO test_answers (test_result_id, pregunta, respuesta_seleccionada, respuesta_correcta, es_correcta) VALUES (%s, %s, %s, %s, %s)',
                        (test_result_id, res['pregunta'], res['seleccionada'], res['correcta'], res['es_correcta']))
        mysql.connection.commit()

    return render_template("test_resultado.html", resultado=resultado, respuestas=resultado_respuestas)

if __name__ == "__main__":
    app.run(debug=True)